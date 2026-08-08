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
import os
import sys
import unittest


def main(argv) -> None:
    program = unittest.main(module=None, argv=["unittest"] + list(argv),
                            exit=False)
    ok = program.result.wasSuccessful()
    # By hand: os._exit skips the flush that a normal exit performs,
    # and a truncated last line would make a green run unreadable.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0 if ok else 1)


if __name__ == "__main__":
    main(sys.argv[1:])
