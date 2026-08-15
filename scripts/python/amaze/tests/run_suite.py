"""Run unittest, report, and LEAVE.

WHY THIS EXISTS INSTEAD OF `hython -m unittest`. A thumbnail helper
that wedges in uninterruptible disk I/O outlives its SIGKILL, so
conversion.py parks it in a graveyard rather than blocking the frame
that spawned it. That keeps the RUN fast and moves the cost to the
EXIT: `_Py_Finalize` calls PySide's cleanup, which walks every living
QObject and destroys it, and `~QProcess` waits on any child still
running. Measured 2026-08-08 with three stack samples: three suites
printed `Ran 1741 tests OK` and then sat at 0% CPU in `poll()` for
eleven, twenty and twenty-six minutes before they were stopped by
hand. The tests had finished; only the exit had not.

That is why this used `os._exit`, and WHY IT NO LONGER DOES
(2026-08-15, ROADMAP line 17). On Windows `os._exit` is not a fast
exit, it is a CRASH: every run, green ones included, ends
`Fatal error: Segmentation fault` AFTER the summary prints, so the
status is unreadable and the runner's promote step can never fire
there. Houdini registers a CRT onexit handler - `UT_Exit::doExit` ->
`PYrunPythonStatements` - that runs PYTHON during process shutdown,
into the interpreter `os._exit` has just abandoned. It is not PySide:
a process building no QApplication at all segfaults identically, so no
Qt-side care could have fixed it. research.md > *`os._exit` IS THE
CRASH ON WINDOWS, AND PySide IS NOT INVOLVED*.

WHAT THE SWAP COSTS, measured rather than assumed: nothing here.
The full suite, 2176 tests, ran 3m41.458s with `sys.exit` against
3m41.578s with `os._exit` - Linux, H22.0.407, 2026-08-15. The
2026-08-08 hang was a QProcess still Running at teardown; nothing in
that run reproduced it.

STILL UNPROVEN, and it is the reason to read the timing above as one
data point rather than a clearance: **the hang was measured on macOS,
and macOS has not been re-measured since the swap.** If a suite ever
parks at 0% CPU after printing its summary again, this is the line
that changed and a Windows-only branch is the answer - at the price of
a second exit path to maintain.
"""
import json
import os
import sys
import unittest

# THE CHECKOUT IS WHAT GETS TESTED, and this is the one line that
# decides it. hython's own path holds the INSTALLED copy, so `import
# amaze` finds that unless the checkout is put in front of it first.
#
# Every test module carried its own copy of these three lines and five
# did not - and because the FIRST import to reach `amaze` binds the
# package for the whole process, a subset run led by one of those five
# tested the last-synced install and silently ignored the working
# tree. Measured 2026-08-10: sabotaging a function in the checkout and
# running its module alone stayed green, while the same sabotage under
# a module that did carry the lines failed as it should. The full
# suite was never affected - its first module carries them - which is
# why this survived.
#
# Here rather than in each module: this file is the only way in.
# `start_test.sh` runs `run_suite.py` for every module and every
# subset, so one insert covers all of them and cannot be forgotten by
# the next test written. `test_no_live_data` holds it to that.
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))

#: Where to record what this run SKIPPED. Unset for an ordinary run,
#: so a single-version suite behaves exactly as it always has.
SKIP_REPORT_VAR = "AMAZE_SKIP_REPORT"


def write_skip_report(result, path: str, houdini: str = "") -> None:
    """Record what this run skipped, for the dead-cover check.

    WRITTEN FROM THE RESULT, never parsed from stdout. `result.skipped`
    is the only place the skipped test IDS exist - the printed summary
    carries `skipped=3` and no names at all. Reading them back off the
    console would make the check a guess about formatting.

    WRITTEN BEFORE THE EXIT, deliberately, and it stays that way now
    the exit is an ordinary one: the report is the input to a SEPARATE
    process, so writing it while the result object is in hand costs
    nothing and never depends on shutdown ordering.

    AND ITS ABSENCE IS THE POINT. A suite that crashes never reaches
    here, so no file appears - and `check_dead_cover.py` refuses rather
    than comparing a partial list. Houdini's crash handler exits 0
    (practice.md), so "the run finished" cannot be read off the status.
    """
    report = {
        # PASSED IN, never read from the environment here. A test that
        # set AMAZE_HOUDINI and popped it in cleanup left this reading
        # empty for the whole run, because this executes AFTER every
        # test - so both hosts came back as `(newest install)`.
        "houdini": houdini,
        "testsRun": result.testsRun,
        "ok": result.wasSuccessful(),
        "skipped": sorted([test.id(), reason]
                          for test, reason in result.skipped),
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=1)


def main(argv) -> None:
    program = unittest.main(module=None, argv=["unittest"] + list(argv),
                            exit=False)
    ok = program.result.wasSuccessful()
    report_path = os.environ.get(SKIP_REPORT_VAR)
    if report_path:
        # LOUD, then carry on to the exit. A raise here would leave the
        # status to a traceback rather than to `ok`, and a report that
        # was not written is an ABSENT one, which check_dead_cover.py
        # already refuses to compare. Loud plus refuse, never a silent
        # half-answer.
        try:
            write_skip_report(program.result, report_path,
                              os.environ.get("AMAZE_HOUDINI", ""))
        except Exception as exc:                             # noqa: BLE001
            print("run_suite: could not write the skip report to %s (%s) - "
                  "the dead-cover check will refuse rather than guess"
                  % (report_path, exc), file=sys.stderr)
    # KEPT after the swap to `sys.exit`, which does flush: Houdini's own
    # shutdown handler runs Python on the way out, so the last thing
    # this file controls is the last point the summary is certainly on
    # the console. A truncated final line makes a green run unreadable,
    # and the flush costs nothing.
    sys.stdout.flush()
    sys.stderr.flush()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main(sys.argv[1:])
