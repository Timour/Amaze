"""What each test runs and opens, per def: the map tools/select-tests.py reads."""
import ast
import hashlib
import json
import os
import subprocess
import sys
import time
import unittest

MAP_VAR = "AMAZE_IMPACT_MAP"
FORMAT = 3
LOADING = "_load"    # imports before the first test: what runs or opens here reaches every test
EFFECTS = ""    # the module-level statements that do more than bind a name
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))


def digest(data) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.blake2b(data, digest_size=8).hexdigest()


def def_name(qualname) -> str:
    """The def a code object runs inside: `f.<locals>.<lambda>` is `f`, a module's own code ""."""
    parts = qualname.split(".")
    while parts and parts[-1].startswith("<"):
        parts.pop()
    return ".".join(parts)


def _canon(node) -> str:
    """ast.dump without what differs between Pythons: empty fields are left out."""
    if isinstance(node, ast.AST):
        return "%s(%s)" % (type(node).__name__, ",".join(
            "%s=%s" % (name, _canon(value)) for name, value in ast.iter_fields(node)
            if value is not None and value != []))
    if isinstance(node, list):
        return "[%s]" % ",".join(_canon(item) for item in node)
    return repr(node)


def _is_doc(statement) -> bool:
    return (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str))


def _undocumented(body):
    return body[1:] if body and _is_doc(body[0]) else body


def _identifiers(nodes) -> set:
    """Every name the code mentions: variables, attributes, imports, identifier-like strings."""
    found = set()
    for top in nodes:
        for node in ast.walk(top):
            if isinstance(node, ast.Name):
                found.add(node.id)
            elif isinstance(node, ast.Attribute):
                found.add(node.attr)
            elif isinstance(node, ast.alias):
                found.update(node.name.split("."))
                if node.asname:
                    found.add(node.asname)
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.update(node.module.split("."))
            elif (isinstance(node, ast.Constant) and isinstance(node.value, str)
                  and node.value.isidentifier()):
                found.add(node.value)
    return found


def _bound(statement):
    """The names a module-level statement binds; None when it does more than bind them."""
    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [statement.name]
    if isinstance(statement, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
        names = []
        for target in targets:
            for node in ast.walk(target):
                if isinstance(node, (ast.Attribute, ast.Subscript)):
                    return None    # it changes another object
                if isinstance(node, ast.Name):
                    names.append(node.id)
        return names
    if _is_doc(statement):
        return []    # a bare string does nothing
    return None


class Code:
    """One .py file as code: a hash per def and per module-level name, and what each mentions."""

    def __init__(self, source):
        tree = ast.parse(source)
        self.mentions = _identifiers([tree])
        self.defs, self.def_uses = {}, {}
        self._hollow(tree, "")
        self.names, self.imports, self.level_uses = {}, {}, {}
        self.spans = []    # (first line, last line, what it binds) of each module-level statement
        effects = []
        for index, statement in enumerate(tree.body):
            if index == 0 and _is_doc(statement):
                continue
            first = min([statement.lineno] + [decorator.lineno for decorator
                                              in getattr(statement, "decorator_list", ())])
            if isinstance(statement, (ast.Import, ast.ImportFrom)) and all(
                    alias.name != "*" for alias in statement.names):
                for alias in statement.names:
                    name = alias.asname or alias.name.split(".")[0]
                    text = "%s|%s|%s" % (getattr(statement, "module", None),
                                         getattr(statement, "level", 0), _canon(alias))
                    self.imports[name] = digest(self.imports.get(name, "") + text)
                    self.level_uses.setdefault(name, set()).update(
                        _identifiers([alias]) | set((getattr(statement, "module", None)
                                                     or "").split(".")) - {""})
                self.spans.append((first, statement.end_lineno, sorted(
                    alias.asname or alias.name.split(".")[0] for alias in statement.names)))
                continue
            bound = _bound(statement)
            text = _canon(statement)
            uses = _identifiers([statement])
            self.spans.append((first, statement.end_lineno, [EFFECTS] if bound is None else bound))
            for name in ([EFFECTS] if bound is None else bound):
                self.level_uses.setdefault(name, set()).update(uses)
                if name == EFFECTS:
                    effects.append(text)
                else:
                    self.names[name] = digest(self.names.get(name, "") + text)
        self.effects = digest("\n".join(effects))

    def _hollow(self, node, prefix) -> None:
        """Hash each def under `node` without its docstring or inner defs' bodies, innermost first."""
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = prefix + child.name
                self._hollow(child, name + ".<locals>.")
                child.body = _undocumented(child.body)
                self.def_uses.setdefault(name, set()).update(_identifiers(child.body))
                self.defs[name] = digest(self.defs.get(name, "") + _canon(child))
                child.body = []
            elif isinstance(child, ast.ClassDef):
                self._hollow(child, prefix + child.name + ".")
                child.body = _undocumented(child.body)
            else:
                self._hollow(child, prefix)

    def shape(self) -> dict:
        return {"defs": self.defs, "names": self.names, "imports": self.imports,
                "effects": self.effects}


def _incidental(frame) -> bool:
    """A read no test depends on: an import's, PySide's `__feature__` look, a traceback's lines."""
    if frame.f_code.co_filename.startswith("<frozen importlib"):
        return True
    cached = inspected = False
    for _ in range(24):
        if frame is None:
            break
        if "shibokensupport" in frame.f_code.co_filename:
            return True
        if frame.f_code.co_filename.endswith("linecache.py"):
            cached = True
        elif cached and frame.f_code.co_name in ("getsource", "getsourcelines"):
            inspected = True    # code read as text, unless PySide is the reader
        frame = frame.f_back
    return cached and not inspected


def repository_files(root) -> list:
    """The files git keeps or would keep under `root`, as repo-relative paths."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}    # ▸r/git-hook-surface
    listed = subprocess.run(("git", "-C", root, "ls-files", "-z", "-co", "--exclude-standard"),
                            capture_output=True, env=env, check=True).stdout
    return sorted({path for path in listed.decode("utf-8").split("\0") if path})


def snapshot(root, paths) -> dict:
    """{path: {"sha", and "shape" for code}} of the files as they stand now."""
    files = {}
    for rel in paths:
        try:
            with open(os.path.join(root, rel), "rb") as handle:
                data = handle.read()
        except OSError:
            continue
        entry = files[rel] = {"sha": digest(data)}
        if rel.endswith(".py"):
            try:
                code = Code(data.decode("utf-8"))
            except (SyntaxError, ValueError):
                continue
            entry["shape"], entry["spans"] = code.shape(), code.spans
    return files


def _bound_at(spans, line) -> list:
    """What the module-level statement around `line` binds; EFFECTS when it binds nothing found."""
    for first, last, names in spans:
        if first <= line <= last:
            return names or [EFFECTS]
    return [EFFECTS]


class Recorder:
    """sys.monitoring sees each def once per test; an audit hook sees what is read."""

    def __init__(self, root=ROOT, tool=None):
        self.root = os.path.join(os.path.abspath(root), "")
        self.tool = tool
        self.running = False
        self.current = LOADING
        self.ran, self.opened, self.listed, self.seconds = {}, {}, {}, {}
        self.tests = []
        self.anchors = {}    # (file, def) run, or ("", file) read, while loading -> {(file, line)}
        self.clock = time.perf_counter
        self._since = None
        self._rel = {}

    def _charge_time(self) -> None:
        now = self.clock()
        if self._since is not None:
            self.seconds[self.current] = self.seconds.get(self.current, 0.0) + now - self._since
        self._since = now

    def _relative(self, path) -> str:
        rel = self._rel.get(path)
        if rel is None:
            full = os.path.abspath(path)
            rel = os.path.relpath(full, self.root).replace(os.sep, "/") \
                if full.startswith(self.root) else ""
            self._rel[path] = rel
        return rel

    def enter(self, key) -> None:
        """Charge what runs from now to `key`: a test's id, or its class's or module's for fixtures."""
        if key != self.current:
            self._charge_time()
            self.current = key
            sys.monitoring.restart_events()

    def begin(self, test_id) -> None:
        self.tests.append(test_id)
        self.enter(test_id)

    def _anchor(self, key) -> None:
        """While loading: note the module-level statement running, by its innermost import."""
        frame = sys._getframe(2)
        while frame is not None:
            if frame.f_code.co_name == "<module>":
                rel = self._relative(frame.f_code.co_filename)
                if rel:
                    self.anchors.setdefault(key, set()).add((rel, frame.f_lineno))
                    return
            frame = frame.f_back

    def _started(self, code, _offset):
        rel = self._relative(code.co_filename)
        if not rel:
            return sys.monitoring.DISABLE
        name = def_name(code.co_qualname)
        self.ran.setdefault(self.current, {}).setdefault(rel, set()).add(name)
        if self.current != LOADING or not name:
            return sys.monitoring.DISABLE
        self._anchor((rel, name))
        return None    # every call while loading, each from its own statement

    def _audit(self, event, args) -> None:
        if not (self.running and event in ("open", "os.listdir", "os.scandir") and args
                and isinstance(args[0], str)):
            return
        if _incidental(sys._getframe(1)):
            return
        rel = self._relative(args[0])
        if rel:
            into = self.opened if event == "open" else self.listed
            into.setdefault(self.current, set()).add(rel)
            if event == "open" and self.current == LOADING:
                self._anchor(("", rel))

    def start(self, audit=True) -> bool:
        """False on a Python without sys.monitoring (before 3.12), or with the tool id taken."""
        monitoring = getattr(sys, "monitoring", None)
        if monitoring is None:
            return False
        self.tool = monitoring.PROFILER_ID if self.tool is None else self.tool
        try:
            monitoring.use_tool_id(self.tool, "amaze-impact")
        except ValueError:
            return False
        monitoring.register_callback(self.tool, monitoring.events.PY_START, self._started)
        monitoring.set_events(self.tool, monitoring.events.PY_START)
        self.running = True
        self._charge_time()
        if audit:
            sys.addaudithook(self._audit)
        return True

    def stop(self) -> None:
        """Stop charging anything; an audit hook cannot be removed, so it goes quiet."""
        self._charge_time()
        self.running = False
        sys.monitoring.set_events(self.tool, 0)
        sys.monitoring.free_tool_id(self.tool)

    def build(self, files, tests_run) -> dict:
        """The map: who ran each def and opened each file, beside the files' hashes."""
        keys = sorted(set(self.ran) | set(self.opened) | set(self.listed))
        index = {key: number for number, key in enumerate(keys)}
        for key, by_file in self.ran.items():
            for rel, names in by_file.items():
                defs = files.get(rel, {}).get("shape", {}).get("defs", {})
                for name in names & defs.keys():
                    files[rel].setdefault("ran", {}).setdefault(name, []).append(index[key])
        for key, paths in self.opened.items():
            for rel in paths & files.keys():
                files[rel].setdefault("opened", []).append(index[key])
        for (rel, name), spots in self.anchors.items():    # what loading built: who to ask instead of all
            bound = sorted({(at, bound) for at, line in spots if at in files
                            for bound in _bound_at(files[at].get("spans", ()), line)})
            if rel and rel in files:
                files[rel].setdefault("loaded", {})[name] = bound
            elif not rel and name in files:
                files[name]["read_on_load"] = bound
        for entry in files.values():
            entry.pop("spans", None)
        dirs = {}
        for key, paths in self.listed.items():
            for rel in paths:
                dirs.setdefault(rel, []).append(index[key])
        return {"format": FORMAT, "made": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "testsRun": tests_run, "python": sys.version.split()[0],
                "keys": keys, "tests": self.tests, "files": files, "dirs": dirs,
                "seconds": {key: round(spent, 3) for key, spent in self.seconds.items()}}

    def save(self, path, tests_run) -> None:
        """Write the map whole, through a scratch file, so a reader never sees half of one."""
        if self.running:
            self.stop()    # the map's own reads are no module's
        found = self.build(snapshot(self.root, repository_files(self.root)), tests_run)
        with open(path + ".writing", "w", encoding="utf-8") as handle:
            json.dump(found, handle, sort_keys=True)
        os.replace(path + ".writing", path)


def follow_tests(recorder) -> None:
    """Charge each test to its id, and a module's or class's fixtures to the module or class."""
    suite = unittest.suite.TestSuite
    outer = []

    def counts(result) -> bool:
        """Only the suite's own run: a test may run a small suite of its own inside it."""
        if not outer:
            outer.append(result)
        return result is outer[0]

    def module_fixture(self, test, result, _original=suite._handleModuleFixture):
        previous = getattr(result, "_previousTestClass", None)
        if counts(result) and (previous is None
                               or previous.__module__ != test.__class__.__module__):
            recorder.enter(test.__class__.__module__)
        return _original(self, test, result)

    def class_setup(self, test, result, _original=suite._handleClassSetUp):
        if counts(result) and getattr(result, "_previousTestClass", None) is not test.__class__:
            recorder.enter("%s.%s" % (test.__class__.__module__, test.__class__.__qualname__))
        return _original(self, test, result)

    def start_test(self, test, _original=unittest.TestResult.startTest):
        if counts(self):
            recorder.begin(test.id())
        return _original(self, test)

    suite._handleModuleFixture = module_fixture
    suite._handleClassSetUp = class_setup
    unittest.TestResult.startTest = start_test


def recorder(path):
    """A started Recorder when `path` asks for a map and this Python can record one, else None."""
    if not path:
        return None
    found = Recorder()
    if not found.start():
        return None
    follow_tests(found)
    return found
