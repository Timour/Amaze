"""Run unittest, report, LEAVE via sys.exit ▸r/windows-exit; the path insert lives here and nowhere else ▸p/checkout-not-install"""
import json
import os
import sys
import unittest

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))

SKIP_REPORT_VAR = "AMAZE_SKIP_REPORT"


def write_skip_report(result, path: str, houdini: str = "") -> None:
    """Record what this run skipped, for the dead-cover check. `houdini` is passed in, never read from the environment here. ▸p/skip-report"""
    report = {
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
        try:
            write_skip_report(program.result, report_path,
                              os.environ.get("AMAZE_HOUDINI", ""))
        except Exception as exc:                             # noqa: BLE001
            print("run_suite: could not write the skip report to %s (%s) - "
                  "the dead-cover check will refuse rather than guess"
                  % (report_path, exc), file=sys.stderr)
    # Houdini runs Python during shutdown, so flush while we still can.
    sys.stdout.flush()
    sys.stderr.flush()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main(sys.argv[1:])
