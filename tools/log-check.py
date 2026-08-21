#!/usr/bin/env python3
"""What the app actually did in the user's last session. - Run this FIRST on any report - a bug, a change request, or an attempt that went wrong. Not because a rule says so: it has repeatedly held information the code cannot give. It once showed 38 unhandled exceptions from a stale module, and a `sources unavailable (URLError)` line that named a corrupted hostname while the UI looked completely normal. - It exists as a script because the reason the check got skipped was friction - writing a bespoke query each time. This is one command. - tools/log-check.py the last session tools/log-check.py --all every session in the file"""

import collections
import json
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts", "python"))


def main() -> int:
    from amaze.core import debug
    from amaze.helpers import hostos

    path = os.path.join(hostos.log_root(), debug.DEFAULT_NAME)
    if not os.path.exists(path):
        print("no log yet: %s" % path)
        print("(Debug Mode off, or Houdini not launched since it was archived)")
        return 0

    rows = []
    for line in open(path, encoding="utf-8", errors="replace"):
        if line.strip().startswith("{"):
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    if not rows:
        print("log is empty")
        return 0

    sessions = sorted({r.get("session") for r in rows if r.get("session")})
    wanted = sessions if "--all" in sys.argv else sessions[-1:]
    print("%s\n%d records, %d sessions\n" % (path, len(rows), len(sessions)))

    for session in wanted:
        recs = [r for r in rows if r.get("session") == session]
        head = next((r for r in recs if r.get("cat") == "session"
                     and isinstance(r.get("data"), dict)
                     and "product" in r["data"]), None)
        info = (head or {}).get("data", {})
        print("=== session %s  %s %s  Amaze %s" % (
            session, info.get("product", "?"), info.get("houdini", "?"),
            info.get("amaze_version", "PRE-STAMP")))

        exc = [r for r in recs if r.get("cat") == "exception"]
        if exc:
            kinds = collections.Counter(
                str(r.get("msg", ""))[:70] for r in exc)
            print("  EXCEPTIONS: %d" % len(exc))
            for msg, n in kinds.most_common(5):
                print("    x%-4d %s" % (n, msg))
                sample = next(r for r in exc if str(r.get("msg", "")).startswith(msg[:40]))
                for line in str(sample.get("traceback", "")).strip().splitlines()[-2:]:
                    print("           %s" % line.strip()[:100])
        else:
            print("  no exceptions")

        odd = [r for r in recs if r.get("cat") != "exception" and any(
            w in json.dumps(r).lower()
            for w in ("failed", "unavailable", "could not", "refused",
                      "storm", "missing", "leak"))]
        if odd:
            print("  NOTABLE:")
            for r in odd[:8]:
                print("    %-9s %-28s %s" % (
                    r.get("cat"), str(r.get("msg"))[:28],
                    str(r.get("data") or "")[:70]))
        print("  activity: %s" % dict(
            collections.Counter(r.get("cat") for r in recs).most_common(6)))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
