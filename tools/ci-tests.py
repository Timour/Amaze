"""The Houdini-less test slice, one process per module: a pinned module going quiet is a failure, and a new green module must join the pin ▸p/prefs-hou-choke"""

import glob
import os
import re
import subprocess
import sys

PINNED = {  # PROVEN green without Houdini, 2026-08-29; may only grow
    "test_category", "test_comment_budget", "test_conversion",
    "test_dead_cover", "test_event_pumps", "test_harness_reset",
    "test_library_prefs", "test_log_export", "test_messages",
    "test_prefs_per_user", "test_prefs_shared", "test_shaderball_assets",
    "test_shell_gates", "test_tooltips", "test_ui_labels",
    "test_unbound_names", "test_upgrade_tool",
}

HERE = os.path.dirname(os.path.abspath(__file__))
CODE = os.path.join(os.path.dirname(HERE), "scripts", "python")


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
    if argv:  # named modules only, no pin bookkeeping - the fast lane
        status = 0
        for name in argv:
            verdict, ran, out = run_module(name.removeprefix("amaze.tests."))
            print("%-34s %s  (%d tests)" % (name, verdict, ran))
            if verdict != "green":
                status = 1
                print(out)
        return status
    names = sorted(
        os.path.basename(path)[:-3]
        for path in glob.glob(
            os.path.join(CODE, "amaze", "tests", "test_*.py")))
    names.remove("test_support")  # the harness itself holds no tests
    green, skipped, failed = [], [], []
    total = 0
    for name in names:
        verdict, ran, out = run_module(name)
        if verdict == "green":
            green.append(name)
            total += ran
        elif verdict == "hou":
            skipped.append(name)
        else:
            failed.append(name)
            print("=== %s ===" % name)
            print(out)
    print("green %d modules / %d tests, %d need Houdini, %d failed"
          % (len(green), total, len(skipped), len(failed)))
    quiet = sorted(PINNED - set(green))
    fresh = sorted(set(green) - PINNED)
    if failed:
        return 1
    if quiet:
        print("pinned modules no longer green: " + " ".join(quiet))
        return 1
    if fresh:
        print("green but unpinned - add to PINNED in tools/ci-tests.py: "
              + " ".join(fresh))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
