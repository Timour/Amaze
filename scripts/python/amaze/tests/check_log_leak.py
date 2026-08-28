#!/usr/bin/env python3
"""Did a test run write to the REAL debug log? Byte size alone cannot answer it - a Houdini may be open and logging, which is not a leak - so only the bytes APPENDED during the run are parsed and each record is attributed to the process that wrote it. Pure stdlib, no Houdini import. Exit 0 clean, 1 leak, 2 could not be read.  `check_log_leak.py <byte-offset-before-the-run>`  ▸archive/check_log_leak.py"""

import json
import os
import sys

HEADLESS = ("hython", "hbatch", "hescape")


def real_log_path() -> str:
    """The log this machine's Amaze actually writes, through the same engine the app uses - never a second copy of the per-OS convention."""
    here = os.path.dirname(os.path.abspath(__file__))
    package_root = os.path.dirname(os.path.dirname(here))   # tests/ -> amaze/ -> python/
    sys.path.insert(0, package_root)
    from amaze.helpers import hostos
    from amaze.core import debug
    return os.path.join(hostos.log_root(), debug.DEFAULT_NAME)


def leaked_sessions(path: str, offset: int):
    """Sessions that appended after `offset` and were NOT a GUI Houdini. A session with no header anywhere started writing elsewhere and switched mid-run - a leak shape a product check alone misses."""
    products = {}
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            data = record.get("data")
            if record.get("cat") == "session" and isinstance(data, dict) \
                    and "product" in data:
                products[record.get("session")] = str(data["product"])

    appended = {}
    with open(path, encoding="utf-8", errors="replace") as handle:
        handle.seek(offset)
        for line in handle:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            session = record.get("session")
            product = products.get(session, "UNKNOWN")
            if product in HEADLESS or product == "UNKNOWN":
                appended[session] = (product, appended.get(session, ("", 0))[1] + 1)
    return [(s, p, n) for s, (p, n) in appended.items()]


def main() -> int:
    # --path: the runner needs the size before the run without duplicating this.
    if len(sys.argv) == 2 and sys.argv[1] == "--path":
        try:
            print(real_log_path())
            return 0
        except Exception as exc:                            # noqa: BLE001
            print("could not locate the real log: %s" % exc, file=sys.stderr)
            return 2
    if len(sys.argv) != 2:
        print(__doc__.strip().splitlines()[0], file=sys.stderr)
        print("usage: check_log_leak.py <byte-offset>", file=sys.stderr)
        return 2
    try:
        offset = int(sys.argv[1])
    except ValueError:
        print("offset must be a byte count, got %r" % sys.argv[1],
              file=sys.stderr)
        return 2
    try:
        path = real_log_path()
    except Exception as exc:                                # noqa: BLE001
        print("could not locate the real log: %s" % exc, file=sys.stderr)
        return 2
    if not os.path.exists(path):
        print("real debug log does not exist yet - nothing to leak into")
        return 0
    try:
        leaks = leaked_sessions(path, offset)
    except OSError as exc:
        print("could not read %s: %s" % (path, exc), file=sys.stderr)
        return 2

    if not leaks:
        print("real debug log clean: %s" % path)
        return 0
    print("LOG LEAK: a headless run wrote to your real debug log", file=sys.stderr)
    print("  %s" % path, file=sys.stderr)
    for session, product, count in sorted(leaks):
        print("  session %s (%s): %d record(s)" % (session, product, count),
              file=sys.stderr)
    print("  A test module is logging outside $AMAZE_LOG_DIR - it should "
          "import amaze.tests.test_support.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
