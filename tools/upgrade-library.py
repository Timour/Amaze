#!/usr/bin/env python3
"""Check and upgrade an Amaze library's schema: `upgrade-library.py <library-dir>` reports and writes nothing, `--rehearse` runs the whole upgrade on a throwaway COPY, and `--write` rehearses first, refuses unless every row survives, backs the databases up beside the library, upgrades in a FRESH process and proves the real run row by row against the rehearsal - exit 0 reported-or-proven, 1 rows moved, 2 refused."""
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile

LEGACY_CONTAINERS = ("snippets", "cops", "gradients")  # pre-assets row homes; this build's engine does not re-home them, so a document carrying rows there must refuse rather than stamp


def _names() -> tuple:
    """The database roster, read from the product itself - a copy here goes silently stale the day a fifth section database lands, and this tool's whole job is completeness."""
    return _connector().DATABASES


def _package_root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "scripts", "python")


def _connector():
    if _package_root() not in sys.path:
        sys.path.insert(0, _package_root())
    from amaze.core import database
    return database


def _read_raw(directory: str) -> dict:
    """{filename: document} for every database present, read as plain json - a file that will not parse reads as {"version": None}, which every mode downstream refuses."""
    found = {}
    for name in _names():
        path = os.path.join(directory, name)
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8-sig") as handle:
                    loaded = json.load(handle)
                found[name] = loaded if isinstance(loaded, dict) \
                    else {"version": None}
            except (OSError, ValueError):
                found[name] = {"version": None}
    return found


def _dict_rows(document: dict) -> list:
    return [r for r in document.get("assets", []) if isinstance(r, dict)]


def _legacy_rows(document: dict) -> int:
    """Rows living under a pre-assets container while `assets` holds none."""
    if _dict_rows(document):
        return 0
    return sum(len(document.get(key, []))
               for key in LEGACY_CONTAINERS
               if isinstance(document.get(key), list))


def _positional_diff(before: dict, after: dict) -> dict:
    """lost / gained / changed between two documents, rows compared BY POSITION - migrations mutate rows in place and never reorder, so position is the identity that survives a migration ADDING the id field itself."""
    old = _dict_rows(before)
    new = _dict_rows(after)
    changed = []
    for index in range(min(len(old), len(new))):
        if old[index] != new[index]:
            fields = {k: (old[index].get(k), new[index].get(k),
                          k in old[index], k in new[index])
                      for k in set(old[index]) | set(new[index])
                      if old[index].get(k) != new[index].get(k)}
            changed.append((index, old[index].get("name", ""), fields))
    return {
        "lost": max(0, len(old) - len(new)),
        "gained": max(0, len(new) - len(old)),
        "changed": changed,
        "rows": (len(old), len(new)),
        "versions": (before.get("version"), after.get("version")),
    }


def _comparable(diffs: dict) -> dict:
    """The diff with every NEW value reduced to its presence - a migration that MINTS a value (an id) generates it fresh each run, so the rehearsal proves which rows and fields move and what they held before, never the minted bytes."""
    out = {}
    for name, diff in diffs.items():
        out[name] = {
            "lost": diff["lost"], "gained": diff["gained"],
            "rows": diff["rows"], "versions": diff["versions"],
            "changed": [(index, sorted(fields),
                         {f: old for f, (old, _n, _po, _pn)
                          in fields.items()},
                         {f: present_new for f, (_o, _n, _po, present_new)
                          in fields.items()})
                        for index, _label, fields in diff["changed"]],
        }
    return out


def _print_diffs(diffs: dict) -> bool:
    clean = True
    for name in sorted(diffs):
        diff = diffs[name]
        print("%-15s v%s -> v%s   rows %d -> %d   lost %d  gained %d  "
              "changed %d" % ((name,) + diff["versions"] + diff["rows"]
                              + (diff["lost"], diff["gained"],
                                 len(diff["changed"]))))
        for index, label, fields in diff["changed"][:8]:
            shown = {f: (old, new) for f, (old, new, _po, _pn)
                     in fields.items()}
            print("    row %d (%s): %s" % (index, label, shown))
        if diff["lost"] or diff["gained"]:
            clean = False
    return clean


def _preflight(docs: dict, code: int) -> dict:
    """{filename: refusal sentence} for everything no mode may touch: unreadable, newer than the build, a chain gap, or rows stranded in a pre-assets container."""
    database = _connector()
    refusals = {}
    for name, doc in docs.items():
        version = doc.get("version")
        if not isinstance(version, int):
            refusals[name] = "cannot be read as an Amaze database"
            continue
        if version > code:
            refusals[name] = ("is at v%d, NEWER than this build's v%d - "
                              "upgrade Amaze instead" % (version, code))
            continue
        missing = [step for step in range(version, code)
                   if step not in database._MIGRATIONS]
        if missing:
            refusals[name] = ("has a migration chain gap at %s"
                              % missing)
            continue
        stranded = _legacy_rows(doc)
        if stranded:   # whatever the stamp says: the app's own save re-stamps a legacy-shaped file to current while its migrations only touch `assets`, so a current version is no proof the rows were ever re-homed
            refusals[name] = ("keeps %d rows under a pre-assets container "
                              "this build's engine cannot re-home - the "
                              "rows are stranded, whatever the version "
                              "stamp says" % stranded)
    return refusals


def report(directory: str) -> int:
    """What an upgrade WOULD do - read-only, plain json."""
    database = _connector()
    docs = _read_raw(directory)
    if not docs:
        print("no Amaze database found in %s" % directory)
        return 2
    code = database.SCHEMA_VERSION
    print("code schema: %d" % code)
    refusals = _preflight(docs, code)
    waiting = False
    for name in sorted(docs):
        doc = docs[name]
        version = doc.get("version")
        rows = len(_dict_rows(doc))
        if name in refusals:
            print("%-15s v%s rows %d  REFUSE: %s"
                  % (name, version, rows, refusals[name]))
        elif version == code:
            print("%-15s v%d rows %d  up to date" % (name, version, rows))
        else:
            print("%-15s v%d rows %d  will climb to v%d"
                  % (name, version, rows, code))
            waiting = True
    if refusals:
        return 2
    print("VERDICT:", "an upgrade is waiting - run again with --write"
          if waiting else "nothing to do")
    return 0


def _migrate_inplace(directory: str, skip_current: bool = True) -> dict:
    """Load and save every database through the product's own connector, so the live migration chain runs with its own guards - {filename: refusal sentence}, empty when all landed. Meant to run in a FRESH process per phase: the connectors are per-filename singletons whose disk baselines must never carry from a rehearsal copy into the real library (▸p/one-file-one-table is the sibling rule)."""
    database = _connector()
    code = database.SCHEMA_VERSION
    refusals = {}
    for name in _names():
        path = os.path.join(directory, name)
        if not os.path.exists(path):
            continue
        if skip_current:
            try:
                with open(path, encoding="utf-8-sig") as handle:
                    if json.load(handle).get("version") == code:
                        continue
            except (OSError, ValueError):
                refusals[name] = "could not be read"
                continue
        connector = database.DatabaseConnector(name)
        try:
            connector.load(os.path.join(directory, ""))
        except Exception as exc:                         # noqa: BLE001
            refusals[name] = "could not be read: %s" % exc
            continue
        if getattr(connector, "_migration_incomplete", False):
            refusals[name] = ("the migration chain has a gap, so the "
                              "stamp is held back")
            continue
        if getattr(connector, "_write_blocked", False):
            refusals[name] = "writing is blocked on earlier damage"
            continue
        if getattr(connector, "_format_ahead", False):
            refusals[name] = ("was written by a NEWER Amaze - upgrade "
                              "Amaze instead")
            continue
        try:
            if not connector.save():
                refusals[name] = "the connector refused the save"
        except Exception as exc:                         # noqa: BLE001
            refusals[name] = "the save failed: %s" % exc
    return refusals


def _phase(directory: str) -> dict:
    """One migration pass in a FRESH python process, so nothing - connector singletons, disk baselines, loaded-id sets - carries between the rehearsal and the real run."""
    result = subprocess.run(
        [sys.executable, os.path.abspath(__file__), directory, "--inner"],
        capture_output=True, text=True)
    if result.returncode not in (0, 2):
        return {"*": "the migration process died: %s"
                % (result.stderr.strip()[-300:] or "no detail")}
    for line in reversed(result.stdout.splitlines()):
        if line.startswith(_MARK):  # the host interpreter may print banners of its own around ours, so the payload line carries a marker instead of trusting position
            try:
                return json.loads(line[len(_MARK):])
            except ValueError:
                break
    return {"*": "the migration process answered nothing readable"}


_MARK = "AMAZE-UPGRADE-RESULT:"


def _inner(directory: str) -> int:
    refusals = _migrate_inplace(directory)
    print(_MARK + json.dumps(refusals))
    return 2 if refusals else 0


def _rehearse(directory: str) -> tuple:
    """The upgrade on a throwaway COPY of the four documents: (diffs, refusals) - what --write will do, proven before anything real is touched."""
    work = tempfile.mkdtemp(prefix="amaze_upgrade_rehearsal_")
    copy = os.path.join(work, "lib")
    os.makedirs(copy)
    for name in _names():
        path = os.path.join(directory, name)
        if os.path.exists(path):
            shutil.copy2(path, os.path.join(copy, name))
    before = _read_raw(copy)
    refusals = _phase(copy)
    after = _read_raw(copy)
    diffs = {name: _positional_diff(before[name], after.get(name, {}))
             for name in before}
    shutil.rmtree(work, ignore_errors=True)
    return diffs, refusals


def rehearse_only(directory: str) -> int:
    """The whole upgrade on a throwaway copy of the four documents, the library itself untouched - what --write will do, shown first."""
    database = _connector()
    docs = _read_raw(directory)
    if not docs:
        print("no Amaze database found in %s" % directory)
        return 2
    refusals = _preflight(docs, database.SCHEMA_VERSION)
    if refusals:
        for name, why in sorted(refusals.items()):
            print("WOULD REFUSE: %s %s" % (name, why))
        return 2
    diffs, refusals = _rehearse(directory)
    for name, why in sorted(refusals.items()):
        print("WOULD REFUSE: %s %s" % (name, why))
    clean = _print_diffs(diffs)
    if refusals:
        return 2
    print("VERDICT:", "every row survives - safe to run with --write"
          if clean else "rows would be lost or invented - --write "
          "will refuse")
    return 0 if clean else 1


def _landed_state(directory: str, code: int) -> None:
    """After a failed real run: which databases actually climbed, so the recovery instruction is specific rather than a shrug."""
    for name, doc in sorted(_read_raw(directory).items()):
        version = doc.get("version")
        print("  %-15s now v%s  %s"
              % (name, version,
                 "CLIMBED - restore this one from the backup if you "
                 "want the old state back" if version == code
                 else "still as it was"))


def write(directory: str) -> int:
    """Upgrade in place: rehearse in one fresh process, refuse loudly, back up, run the real thing in another, and prove the real run matches the rehearsal."""
    database = _connector()
    code = database.SCHEMA_VERSION
    docs = _read_raw(directory)
    if not docs:
        print("no Amaze database found in %s" % directory)
        return 2
    refusals = _preflight(docs, code)   # BEFORE the nothing-to-do answer: a current stamp with stranded legacy rows must refuse, never read as done
    if refusals:
        for name, why in sorted(refusals.items()):
            print("REFUSED: %s %s" % (name, why))
        print("nothing was changed anywhere")
        return 2
    if all(d.get("version") == code for d in docs.values()):
        print("every database is already at v%d - nothing to do" % code)
        return 0

    print("rehearsing on a copy first...")
    diffs, refusals = _rehearse(directory)
    if refusals:
        for name, why in sorted(refusals.items()):
            print("REFUSED: %s %s" % (name, why))
        print("nothing was changed anywhere")
        return 2
    if not _print_diffs(diffs):
        print("REFUSED: the rehearsal lost or invented rows - "
              "nothing was changed anywhere")
        return 2

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = os.path.join(directory, "backup-before-v%d-%s" % (code, stamp))
    try:
        os.makedirs(backup)
        for name in docs:
            shutil.copy2(os.path.join(directory, name),
                         os.path.join(backup, name))
    except OSError as exc:
        print("REFUSED: the backup could not be written (%s) - "
              "nothing was changed anywhere" % exc)
        return 2
    print("backup: %s" % backup)

    refusals = _phase(directory)
    if refusals:
        for name, why in sorted(refusals.items()):
            print("REFUSED mid-write: %s %s" % (name, why))
        _landed_state(directory, code)
        print("the backup above holds every database as it was")
        return 2

    after = _read_raw(directory)
    real = {name: _positional_diff(docs[name], after.get(name, {}))
            for name in docs}
    print("the real run:")
    _print_diffs(real)
    if _comparable(real) != _comparable(diffs):
        print("VERDICT: the real run DIFFERS from the rehearsal - "
              "read the tables above; the backup holds what was there")
        _landed_state(directory, code)
        return 1
    print("VERDICT: upgraded and proven - the real run matched the "
          "rehearsal row for row")
    return 0


def main(argv) -> int:
    if sys.version_info < (3, 11):   # the app modules this drives need 3.11 (database.py imports typing.Self), and without the guard a stock macOS python3 answers every mode with an ImportError traceback and exit 1 - the code the contract reserves for rows moved
        print("REFUSED: this tool needs Python 3.11+ and this is %d.%d - "
              "run it with hython or a newer python3"
              % sys.version_info[:2])
        return 2
    flags = [a for a in argv[1:] if a.startswith("--")]
    args = [a for a in argv[1:] if not a.startswith("--")]
    unknown = [f for f in flags if f not in ("--write", "--rehearse",
                                             "--inner")]
    if len(args) != 1 or unknown or len(flags) > 1:
        if unknown:
            print("unknown flag(s): %s" % " ".join(unknown))
        print(__doc__)
        return 2
    directory = args[0]
    if not os.path.isdir(directory):
        print("no such directory: %s" % directory)
        return 2
    if "--inner" in flags:
        return _inner(directory)
    if "--write" in flags:
        return write(directory)
    if "--rehearse" in flags:
        return rehearse_only(directory)
    return report(directory)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
