"""The requirement tests without Houdini, one process per module, as GitHub runs them."""

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


def run_module(name):
    env = dict(os.environ, PYTHONPATH=CODE)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "-q", "amaze.tests." + name],
        capture_output=True, text=True, timeout=300, env=env)
    out = (proc.stdout or "") + (proc.stderr or "")
    match = re.search(r"^Ran (\d+) test", out, re.M)
    ran = int(match.group(1)) if match else 0
    if proc.returncode == 0 and ran:
        return "green", ran, out
    if "No module named 'hou'" in out:
        return "hou", 0, out
    return "fail", ran, out


def main(argv):
    """The named modules, or every module of the requirement lists; 1 when one is not green."""
    status = 0
    for name in argv or check_requirements.modules():
        verdict, ran, out = run_module(name.removeprefix("amaze.tests."))
        print("%-34s %s  (%d tests)" % (name, verdict, ran))
        if verdict != "green":
            status = 1
            print(out)
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
