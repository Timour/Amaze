"""The requirement tests without Houdini, one process per module, as GitHub runs them."""

import glob
import importlib.util
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CODE = os.path.join(os.path.dirname(HERE), "scripts", "python")

_spec = importlib.util.spec_from_file_location(
    "check_requirements", os.path.join(HERE, "check-requirements.py"))
check_requirements = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_requirements)


def environment():
    """The tests' environment on this Python, with Houdini's own PySide6 when it has none; or None."""
    env = dict(os.environ, PYTHONPATH=CODE)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    if not importlib.util.find_spec("PySide6"):
        hfs = os.environ.get("HFS", "")
        forced = glob.glob(os.path.join(sys.prefix, "lib", "python*", "site-packages-forced")) \
            + glob.glob(os.path.join(sys.prefix, "lib", "site-packages-forced"))
        plugins = [found for found in glob.glob(os.path.join(hfs, "*", "Qt_plugins"))
                   + glob.glob(os.path.join(hfs, "..", "*", "Qt_plugins"))
                   if glob.glob(os.path.join(found, "platforms", "*qoffscreen*"))]
        if not (hfs and forced and plugins):
            return None
        env["PYTHONPATH"] = os.pathsep.join((CODE, forced[0]))
        env["QT_PLUGIN_PATH"] = plugins[0]
    probe = subprocess.run([sys.executable, "-c", "from PySide6 import QtCore"],
                           capture_output=True, env=env, timeout=60)
    return env if probe.returncode == 0 else None


def run_module(names, env):
    """(verdict, tests run, output) for test ids of one module: green, skipped, hou or fail."""
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "-q"] + ["amaze.tests." + name for name in names],
        capture_output=True, text=True, timeout=300, env=env)
    out = (proc.stdout or "") + (proc.stderr or "")
    match = re.search(r"^Ran (\d+) test", out, re.M)
    ran = int(match.group(1)) if match else 0
    if proc.returncode == 0 and ran:
        return ("skipped" if "skipped=" in out else "green"), ran, out
    if "No module named 'hou'" in out:
        return "hou", 0, out
    return "fail", ran, out


def main(argv):
    """Run the named tests or every requirement module; `--rest FILE` lists what is left for hython."""
    rest_file, rest = None, []
    if argv[:1] == ["--rest"]:
        rest_file, argv = argv[1], argv[2:]
    names = [name.removeprefix("amaze.tests.") for name in argv] or check_requirements.modules()
    listed = set(check_requirements.modules())
    env = environment()
    modules = {}
    for name in names:
        if rest_file and (env is None or name.split(".")[0] not in listed):
            rest.append(name)
        else:
            modules.setdefault(name.split(".")[0], []).append(name)
    if env is None and modules:
        print("ci-tests: this Python has no PySide6 to run the tests with")
        return 1
    status = total = 0
    for module, ids in modules.items():
        verdict, ran, out = run_module(ids, env)
        if rest_file and verdict in ("hou", "skipped"):    # hython runs it whole, nothing skipped
            rest.extend(ids)
            continue
        print("%-34s %s  (%d tests)" % (module, verdict, ran))
        if verdict == "fail" or (verdict == "hou" and not rest_file):
            status = 1
            print(out)
        else:
            total += ran
    if rest_file:
        with open(rest_file, "w", encoding="utf-8") as handle:
            handle.write(" ".join(rest))
    if modules:
        print("Ran %d tests on Python %s, without Houdini" % (total, sys.version.split()[0]))
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
