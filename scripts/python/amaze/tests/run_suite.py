"""Run unittest, report, and LEAVE - without interpreter shutdown.

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

There is no Qt escape - the destructor waits whenever the process
state is still Running, and a deferred SIGKILL keeps it Running. So
the runner stops asking for a shutdown it does not need. The result
is already computed and printed; `os._exit` hands the status straight
to the shell.

WHAT THIS SKIPS, deliberately: atexit handlers, garbage collection
and static destructors. Nothing the suite's correctness rests on
lives there - unittest's own cleanups (tearDown, addCleanup,
tearDownModule) all run BEFORE this point, and the log-leak check is
a separate process that runs after. Streams are flushed by hand
because os._exit will not do it.
"""
import json
import os
import sys
import unittest

#: Where to record what this run SKIPPED. Unset for an ordinary run,
#: so a single-version suite behaves exactly as it always has.
SKIP_REPORT_VAR = "AMAZE_SKIP_REPORT"


def write_skip_report(result, path: str, houdini: str = "") -> None:
    """Record what this run skipped, for the dead-cover check.

    WRITTEN FROM THE RESULT, never parsed from stdout. `result.skipped`
    is the only place the skipped test IDS exist - the printed summary
    carries `skipped=3` and no names at all. Reading them back off the
    console would make the check a guess about formatting.

    WRITTEN BEFORE `os._exit`, deliberately. This module leaves without
    atexit or a flush (see the module docstring), so anything not
    closed by then is lost.

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
        # LOUD, then carry on to os._exit. A raise here would take the
        # normal interpreter shutdown this module exists to avoid - the
        # PySide teardown that parked three suites for eleven, twenty
        # and twenty-six minutes. And a report that was not written is
        # an ABSENT one, which check_dead_cover.py already refuses to
        # compare. Loud plus refuse, never a silent half-answer.
        try:
            write_skip_report(program.result, report_path,
                              os.environ.get("AMAZE_HOUDINI", ""))
        except Exception as exc:                             # noqa: BLE001
            print("run_suite: could not write the skip report to %s (%s) - "
                  "the dead-cover check will refuse rather than guess"
                  % (report_path, exc), file=sys.stderr)
    # By hand: os._exit skips the flush that a normal exit performs,
    # and a truncated last line would make a green run unreadable.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0 if ok else 1)


if __name__ == "__main__":
    main(sys.argv[1:])
