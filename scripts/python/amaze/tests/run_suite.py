"""Run unittest, report, exit via `sys.exit` ▸r/windows-exit; the only path insert is here."""
import json
import os
import sys
import unittest

import impact_map

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))

SKIP_REPORT_VAR = "AMAZE_SKIP_REPORT"


def write_skip_report(result, path: str, houdini: str = "") -> None:
    """Record what this run skipped, for the dead-cover check; `houdini` is passed in. ▸p/skip-report"""
    report = {
        "houdini": houdini,
        "testsRun": result.testsRun,
        "ok": result.wasSuccessful(),
        "skipped": sorted([test.id(), reason]
                          for test, reason in result.skipped),
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=1)


def host_line() -> str:
    """Names the Houdini this run is on, from the suite's own hython: a separate start costs 8-20 s."""
    try:
        import hou
        return "suite host: Houdini %s, Python %s" % (
            hou.applicationVersionString(), sys.version.split()[0])
    except Exception as exc:                                 # noqa: BLE001
        return "suite host: UNKNOWN - hython could not report its version (%s)" % exc


def close_qt_windows() -> None:
    """Delete the run's widgets and windows while Python runs; at exit a QML view's hide crashed."""
    try:
        from PySide6 import QtCore, QtGui, QtWidgets
    except ImportError:
        return
    app = QtWidgets.QApplication.instance()
    if app is None:
        return
    for window in app.topLevelWidgets() + [w for w in QtGui.QGuiApplication.topLevelWindows()
                                           if isinstance(w, QtGui.QWindow) and w.isVisible()]:
        window.close()
        window.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def main(argv) -> None:
    print(host_line(), flush=True)
    map_path = os.environ.get(impact_map.MAP_VAR)
    recorder = impact_map.recorder(map_path)
    program = unittest.main(module=None, argv=["unittest"] + list(argv),
                            exit=False)
    ok = program.result.wasSuccessful()
    if recorder is not None and ok:    # a failing run may have stopped before code a passing run reaches
        try:
            recorder.save(map_path, program.result.testsRun)
        except Exception as exc:                             # noqa: BLE001
            print("run_suite: could not write the impact map to %s (%s)"
                  % (map_path, exc), file=sys.stderr)
    report_path = os.environ.get(SKIP_REPORT_VAR)
    if report_path:
        try:
            write_skip_report(program.result, report_path,
                              os.environ.get("AMAZE_HOUDINI", ""))
        except Exception as exc:                             # noqa: BLE001
            print("run_suite: could not write the skip report to %s (%s) - "
                  "the dead-cover check will refuse rather than guess"
                  % (report_path, exc), file=sys.stderr)
    close_qt_windows()    # ▸r/suite-exit-crash
    # Houdini runs Python during shutdown, so flush while we still can.
    sys.stdout.flush()
    sys.stderr.flush()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main(sys.argv[1:])
