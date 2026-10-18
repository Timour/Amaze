#!/usr/bin/env python3
"""What the app did, from its own log: run it FIRST on any report. --all, --recent [hours]"""

import collections
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts", "python"))


def recent(rows, hours=72.0) -> list:
    """The last `hours` of the log in a few lines: what went wrong, then updates and open times."""
    since = time.time() - hours * 3600
    recs = [r for r in rows if (r.get("t") or 0) >= since]

    def when(record):
        return time.strftime("%b %d %H:%M", time.localtime(record.get("t") or 0))

    out = ["Amaze log, last %g h: %d records, %d sessions"
           % (hours, len(recs), len({r.get("session") for r in recs}))]
    for cat, label in (("exception", "unhandled exceptions"), ("refuse", "refusals"),
                       ("note", "notes")):
        hits = [r for r in recs if r.get("cat") == cat]
        if hits:
            out.append("  %d %s:" % (len(hits), label))
            for r in hits[-5:]:
                value = str((r.get("data") or {}).get("value", "")).replace("\n", " ")
                out.append("    %s  %s %s" % (when(r), str(r.get("msg", ""))[:70], value[:110]))
    if len(out) == 1:
        out.append("  no unhandled exceptions, refusals or notes")
    applied = [when(r) for r in recs
               if r.get("cat") == "updater" and r.get("msg") == "update applied"]
    if applied:
        out.append("  %d updates applied: %s" % (len(applied), ", ".join(applied)))
    opens = [r.get("data") or {} for r in recs
             if r.get("cat") == "session" and r.get("msg") == "panel ready"]
    if opens:
        out.append("  pane opens, code load / build ms: " + ", ".join(
            "%d/%d" % (d.get("module_body_ms") or 0, d.get("construction_ms") or 0)
            for d in opens[-6:]))
    return out


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
    if "--recent" in sys.argv:
        hours = sys.argv[sys.argv.index("--recent") + 1:][:1] or ["72"]
        print("\n".join(recent(rows, float(hours[0]))))
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
