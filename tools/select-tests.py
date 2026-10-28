"""The tests a change reaches, by the last green full run's map, or ALL. [FILE ...]"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = "scripts/python/amaze/tests/"
MAP_NAME = "amaze-test-impact.json"
EVERYTHING = (TESTS + "run_suite.py", TESTS + "start_test.sh", TESTS + "impact_map.py")
GATE_TESTS = ("test_shell_gates", "test_shell_gates_more", "test_dead_cover")

_spec = importlib.util.spec_from_file_location(
    "impact_map", os.path.join(REPO, TESTS, "impact_map.py"))
impact_map = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(impact_map)


class Everything(Exception):
    """Only the whole suite can answer; the message says why."""


def git(*args):
    return subprocess.run(("git", "-C", REPO) + args, capture_output=True,
                          text=True, check=True).stdout.strip()


def map_path():
    """Where the map lives: beside the repository's own git data, shared by its worktrees."""
    return os.path.join(git("rev-parse", "--path-format=absolute", "--git-common-dir"),
                        MAP_NAME)


def suite_modules():
    """The module list start_test.sh runs, read from it."""
    with open(os.path.join(REPO, TESTS, "start_test.sh"), encoding="utf-8") as handle:
        body = handle.read().split('MODULES="', 1)[1].split('"', 1)[0]
    return body.replace("\\", " ").split()


def load(path):
    """The map, or None when there is none this selector can read."""
    try:
        with open(path, encoding="utf-8") as handle:
            found = json.load(handle)
    except (OSError, ValueError):
        return None
    return found if found.get("format") == impact_map.FORMAT else None


def reader(root):
    """read(path): a file's text now, or None when it is gone."""
    def read(path):
        try:
            with open(os.path.join(root, path), "rb") as handle:
                return handle.read().decode("utf-8", "replace")
        except OSError:
            return None
    return read


def changed_files(impact, root=REPO):
    """The paths whose bytes differ from the map's, and those only one side has."""
    known = impact["files"]
    changed = []
    for path in sorted(set(impact_map.repository_files(root)) | set(known)):
        try:
            with open(os.path.join(root, path), "rb") as handle:
                sha = impact_map.digest(handle.read())
        except OSError:
            sha = None
        if sha != known.get(path, {}).get("sha"):
            changed.append(path)
    return changed


def module_name(path):
    name = os.path.splitext(os.path.basename(path))[0]
    return os.path.basename(os.path.dirname(path)) if name == "__init__" else name


class Selection:
    """Each change, followed to the tests that ran or read it: by id, or a class or module whole."""

    def __init__(self, impact, read, suite):
        self.keys = impact["keys"]
        self.files = impact["files"]
        self.dirs = impact.get("dirs", {})
        self.read = read
        self.suite = suite
        self.picked = set()
        self.untested = []
        self._code = {}
        self._python = None
        self._followed = set()

    def take(self, indexes, why, built=()):
        """Pick these tests; what ran while the suite loaded is asked about what it `built`."""
        names = {self.keys[index] for index in indexes}
        if impact_map.LOADING in names:
            names.discard(impact_map.LOADING)
            if not built:
                raise Everything(why + " runs or is read while the suite loads")
            for where, bound in built:
                if bound == impact_map.EFFECTS:
                    raise Everything("%s runs %s on import" % (where, why))
                self._follow(where, bound, False)
        self.picked |= names

    def take_def(self, path, qualname):
        entry = self.files.get(path, {})
        self.take(entry.get("ran", {}).get(qualname, ()), "%s %s" % (path, qualname),
                  entry.get("loaded", {}).get(qualname, ()))

    def code(self, path):
        """The file's Code as it stands now; None when it is gone."""
        if path not in self._code:
            source = self.read(path)
            try:
                self._code[path] = None if source is None else impact_map.Code(source)
            except (SyntaxError, ValueError):
                raise Everything(path + " does not parse") from None
        return self._code[path]

    def change(self, path):
        name = os.path.basename(path)
        if path in EVERYTHING:
            raise Everything(path + " runs every test")
        if path.startswith("tools/"):
            self.picked.update(GATE_TESTS)
            return
        entry = self.files.get(path)
        gone = self.read(path) is None
        if entry is None or gone:
            self.take(self.dirs.get(os.path.dirname(path), ()), path)
        if entry is not None:
            self.take(entry.get("opened", ()), path, entry.get("read_on_load", ()))
        module = name[:-3] if name.endswith(".py") else ""
        if path.startswith(TESTS) and module in self.suite:
            self._tests_changed(path, entry, module)
        elif path.endswith(".py"):
            self._code_changed(path, entry)
        elif entry is not None and not entry.get("opened") and not self._prose(path):
            raise Everything("no test was seen reading " + path)

    def _tests_changed(self, path, entry, module):
        """A test module: the tests whose code changed, or all of it when more than a def did."""
        before = (entry or {}).get("shape")
        code = self.code(path)
        if before is None or code is None:
            self.picked.add(module)
            return
        now = code.shape()
        if (now["effects"] != before["effects"] or _differ(before["names"], now["names"])
                or _differ(before["imports"], now["imports"])):
            self.picked.add(module)
            return
        for qualname in _differ(before["defs"], now["defs"]):
            self.take_def(path, qualname)

    @staticmethod
    def _prose(path):
        return path.startswith("docs/") or path.endswith((".md", ".txt"))

    def _code_changed(self, path, entry):
        if entry is None:
            raise Everything(path + " is new code")
        before = entry.get("shape")
        if before is None:
            raise Everything(path + " did not parse when the map was made")
        code = self.code(path)
        now = code.shape() if code is not None else {
            "defs": {}, "names": {}, "imports": {}, "effects": before["effects"]}
        if now["effects"] != before["effects"]:
            raise Everything(path + " changes what its module does on import")
        ran = entry.get("ran", {})
        for qualname in _differ(before["defs"], now["defs"]):
            self.take_def(path, qualname)
            if not ran.get(qualname) and qualname in now["defs"]:
                self.untested.append("%s %s" % (path, qualname))
        for name in _differ(before["names"], now["names"]):
            self._follow(path, name, False)
        for name in _differ(before["imports"], now["imports"]):
            self._follow(path, name, True)

    def python(self):
        """The code the map knows: new code never reaches here, it runs every test."""
        if self._python is None:
            self._python = sorted(path for path in self.files if path.endswith(".py"))
        return self._python

    def _follow(self, path, name, local):
        """Every def that uses a changed module-level `name` of `path`, through what binds it on."""
        work = [(path, name, local)]
        while work:
            where, name, local = work.pop()
            if (where, name) in self._followed:
                continue
            self._followed.add((where, name))
            for qualname in list(self.files.get(where, {}).get("ran", {})):
                if qualname.startswith(name + "."):
                    self.take_def(where, qualname)    # a class: all it does
            module = module_name(where)
            for other in [where] if local else self.python():
                code = self.code(other)
                if code is None or (other != where and module not in code.mentions):
                    continue
                for qualname, uses in code.def_uses.items():
                    if name in uses:
                        self.take_def(other, qualname)
                for bound, uses in code.level_uses.items():
                    if name not in uses or (other == where and bound == name):
                        continue
                    if bound == impact_map.EFFECTS:
                        raise Everything("%s runs %s on import" % (other, name))
                    work.append((other, bound, bound in code.imports))


def _differ(before, now):
    return sorted(key for key in set(before) | set(now) if before.get(key) != now.get(key))


def _prefixes(test_id):
    """test_x, test_x.Class, test_x.Class.test: the keys that each stand for this test."""
    parts = test_id.split(".")
    return [".".join(parts[:end]) for end in range(1, len(parts) + 1)]


def arguments(picked, impact, suite):
    """start_test.sh's arguments for `picked`, in suite order: a whole module by name, else ids."""
    by_module = {}
    for test_id in impact["tests"]:
        by_module.setdefault(test_id.split(".", 1)[0], []).append(test_id)
    found = []
    for module in suite:
        tests = by_module.get(module, [])
        mine = [test_id for test_id in tests if picked.intersection(_prefixes(test_id))]
        if module in picked or (mine and len(mine) == len(tests)):
            found.append(module)
        else:
            found.extend(mine)
    return found


def cost(found, impact):
    """The seconds the last full run spent on these arguments, with their fixtures."""
    seconds = impact.get("seconds", {})
    keys = set()
    for argument in found:
        keys.update(_prefixes(argument))
        keys.update(key for key in seconds if key.startswith(argument + "."))
    return sum(seconds.get(key, 0) for key in keys)


def select(changed, impact, suite, read):
    """start_test.sh's arguments for `changed`; None when only the whole suite can say."""
    if impact is None:
        return None
    selection = Selection(impact, read, suite)
    try:
        for path in changed:
            selection.change(path)
    except Everything:
        return None
    return arguments(selection.picked, impact, suite)


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--map")
    parser.add_argument("files", nargs="*")
    args = parser.parse_args(argv)
    impact = load(args.map or map_path())
    if impact is None:
        print("select-tests: no map yet - a green full run writes one", file=sys.stderr)
        print("ALL")
        return
    changed = args.files or changed_files(impact)
    suite = suite_modules()
    selection = Selection(impact, reader(REPO), suite)
    try:
        for path in changed:
            selection.change(path)
    except Everything as why:
        print("select-tests: ALL - %s" % why, file=sys.stderr)
        print("ALL")
        return
    for where in selection.untested:
        print("select-tests: no test runs %s" % where, file=sys.stderr)
    found = arguments(selection.picked, impact, suite)
    tests = sum(1 for test_id in impact["tests"]
                if selection.picked.intersection(_prefixes(test_id)))
    print("select-tests: %d changed file(s) since the map of %s reach %d of %d tests, "
          "about %d s of the full run's %d s"
          % (len(changed), impact["made"], tests, len(impact["tests"]), cost(found, impact),
             sum(impact.get("seconds", {}).values())), file=sys.stderr)
    print(" ".join(found))


if __name__ == "__main__":
    main(sys.argv[1:])
