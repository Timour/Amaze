"""The debug engine: a structured session log, off unless asked for.

One JSON Lines file - `amaze_debug.jsonl` in the per-OS log dir
`hostos` resolves - so a session can be filtered by category, counted
and diffed rather than read as prose. A `print()` reaches only the
terminal Houdini was launched from, and PySide swallows exceptions
raised in Qt slots, so neither survives in a log the user can send.

THREE WRITERS, TWO OF THEM ALWAYS ON:

* the crash recorder, armed by `install()`, writes any UNCAUGHT
  exception with the environment header even with Debug Mode off;
* `prefs_snapshot()` also writes with Debug off, deliberately - it is
  the recovery route `prefs.py`'s dialog points at when settings.json
  will not parse, and that session is exactly the one nobody had Debug
  Mode on for;
* `event()` / `note()` / `exception()` are gated on Debug Mode
  (Preferences -> Debug), and off means off - one boolean test.

A quiet session with Debug off therefore writes one settings record per
panel open and nothing else.

Use:
    from amaze.core import debug

    debug.note("thumbnail missing", path=p)      # prints AND logs
    debug.event("import", "shader wired", node=n.path())
    debug.exception("import_record")             # full traceback
    with debug.timed("thumbs", "render all", count=n):
        ...
"""

from __future__ import annotations

import datetime
import json
import os
import platform
import shutil
import sys
import threading
import time
import traceback
from contextlib import contextmanager

from amaze.helpers import hostos

#: Default location: the OS-integration engine's per-OS log dir.
#: Deliberately NOT the library folder (which is cloud-synced) nor the
#: repo - a log is local-machine state, same reasoning as the caches.
#:
#: $AMAZE_LOG_DIR overrides it, read ONCE here at import so a whole
#: process can be isolated before any module has logged anything - the
#: test runner sets it. That matters because guarded() and the
#: excepthook record crashes with Debug Mode OFF: the suite's
#: DELIBERATE failures were landing in the user's real log as
#: genuine-looking crash records, until the count (18,975) could no
#: longer be read as "the app crashed".
DEFAULT_DIR = os.environ.get("AMAZE_LOG_DIR", "").strip() or hostos.log_root()
DEFAULT_NAME = "amaze_debug.jsonl"
#: The pre-rename filename; _migrate_legacy_log() renames it once.
LEGACY_NAME = "assetlib_debug.jsonl"


def _migrate_legacy_log(directory: str) -> None:
    """Carry the existing log forward under the new name, once. A
    failure here must never cost logging - worst case the old file
    stays behind and a fresh log starts."""
    hostos.migrate_legacy_file(directory, LEGACY_NAME, DEFAULT_NAME)


_migrate_legacy_log(DEFAULT_DIR)

import atexit  # noqa: E402 - registered once, below the log path setup

#: Start a fresh file once the old one passes this, so a forgotten
#: Debug Mode can't fill a disk.
MAX_BYTES = 32 * 1024 * 1024

_enabled = False
_path = os.path.join(DEFAULT_DIR, DEFAULT_NAME)
_session = ""
_seq = 0
#: SURVIVES RELOAD, deliberately - see _install_excepthook. panel.py
#: reloads this module on every panel open, and importlib.reload
#: re-executes the body into the SAME module dict, so a plain
#: `= False` here re-arms an installer whose hook is already live.
_excepthook_installed = globals().get("_excepthook_installed", False)
_crash_counts: dict = {}

#: Records of an identical repeating failure to keep in full before
#: switching to counting. Five is enough to see the pattern.
FLOOD_VERBATIM = 5
#: After that, one marker every N so the log still shows it is ongoing
#: without the volume. A stale callback in a paint/timer path once
#: wrote 8,973 identical records in a single session.
FLOOD_MARKER_EVERY = 1000


#: A key that has been quiet this long is treated as a NEW occurrence.
#: Without it, _crash_counts is process-global and cleared nowhere: a
#: failure that fired five times during panel setup and then recurred
#: from a different user action hours later wrote NOTHING AT ALL, and
#: the log said the app had five exceptions.
FLOOD_DECAY_SECONDS = 300

#: How many records were actually written per key, so "suppressed" can
#: be the truth rather than an estimate.
_crash_recorded: dict = globals().get("_crash_recorded", {})
#: Last time each key fired, for the decay above.
_crash_last_seen: dict = globals().get("_crash_last_seen", {})


def _flood_check(kind: str, exc_type_name: str, tb_text: str):
    """Rate-limit an identical, repeating failure.

    Returns (record_it, count). Identity is the exception type plus its
    deepest frame, so the same bug re-firing per event-loop tick
    collapses to a handful of records and periodic markers, while a
    DIFFERENT failure is never suppressed by a noisy neighbour.

    Two things this must NOT do, both of which it used to:

    * Hide the magnitude. Markers fired only at exact multiples of 1000,
      so 6 occurrences wrote 5 records, 100 wrote 5, and 999 wrote 5 -
      with nothing anywhere saying there had been more. tools/log-check
      then reported "EXCEPTIONS: 5" for a session with a thousand.
      Markers now also fire at each POWER OF TEN (10, 100, 1000...), so
      a small flood is visible immediately, while the existing
      1000-multiple markers keep a large one current. Three thousand
      occurrences cost ten records rather than five, and the atexit
      flush closes the last gap with the exact total.

    * Lose a recurrence outright. See FLOOD_DECAY_SECONDS.
    """
    frame = ""
    lines = tb_text.splitlines()
    if len(lines) >= 2:
        frame = lines[-2].strip()
    key = "%s|%s|%s" % (kind, exc_type_name, frame)

    now = time.monotonic()
    last = _crash_last_seen.get(key)
    if last is not None and now - last > FLOOD_DECAY_SECONDS:
        # Quiet for long enough that this is a fresh event, not a flood.
        _flush_repeat(key)
        _crash_counts.pop(key, None)
        _crash_recorded.pop(key, None)
    _crash_last_seen[key] = now

    count = _crash_counts.get(key, 0) + 1
    _crash_counts[key] = count
    if count <= FLOOD_VERBATIM:
        _crash_recorded[key] = _crash_recorded.get(key, 0) + 1
        return True, count
    # A power of ten (10, 100, 1000 ...) so a small flood is visible at
    # once, plus the original every-1000 so a large one stays current.
    power_of_ten = count == 10 ** (len(str(count)) - 1)
    if power_of_ten or count % FLOOD_MARKER_EVERY == 0:
        _crash_recorded[key] = _crash_recorded.get(key, 0) + 1
        return True, count
    return False, count


def _suppressed_for(kind: str, exc_type_name: str, tb_text: str, count: int) -> int:
    """How many of this key's occurrences never reached the log.

    Was `count - FLOOD_VERBATIM`, which forgets that the marker records
    themselves were kept - so it over-reported by one per marker (at
    1000 it claimed 995 suppressed when 994 were). Counted, not
    inferred."""
    frame = ""
    lines = tb_text.splitlines()
    if len(lines) >= 2:
        frame = lines[-2].strip()
    key = "%s|%s|%s" % (kind, exc_type_name, frame)
    return max(count - _crash_recorded.get(key, 0), 0)


def _flush_repeat(key: str) -> None:
    """Write a final count for a key whose last occurrence was never
    recorded, so the log ends up carrying the EXACT total rather than
    the last decade marker."""
    count = _crash_counts.get(key)
    if not count:
        return
    recorded = _crash_recorded.get(key, 0)
    if count <= FLOOD_VERBATIM:
        return          # every one of them was written verbatim
    kind, _, rest = key.partition("|")
    exc_name, _, frame = rest.partition("|")
    _ensure_session()
    # The category follows the KEY, not the writer. This used to be a
    # hardcoded "exception", from when the flood guard rate-limited
    # exceptions only. It grew to cover every event kind and the
    # category did not follow, so `event:geo: thumbnail (final count)`
    # - 255 perfectly ordinary thumbnails - was filed as a crash.
    # Measured on a Windows log: five of its six "exceptions" were
    # flood summaries of normal operation, and they were reported as
    # six crashes before anyone read them. The log is this project's
    # primary instrument; a crash count it inflates itself is worse
    # than no count.
    cat = "flood"
    if kind.startswith("event:"):
        cat = kind.split(":", 1)[1].strip() or "flood"
    elif kind:
        cat = kind.strip()
    _write({
        "cat": cat,
        "msg": "%s: %s (final count)" % (kind, exc_name),
        "data": {
            "repeat_count": count,
            "suppressed": count - recorded,
            "frame": frame,
        },
    })


def flush_repeats() -> None:
    """Write the final count for every rate-limited failure. Registered
    at exit so a session that ended mid-flood still says how bad it
    got."""
    for key in list(_crash_counts):
        try:
            _flush_repeat(key)
        except Exception:               # noqa: BLE001 - never block exit
            pass
        _crash_counts.pop(key, None)
        _crash_recorded.pop(key, None)
#: Both survive reload for the same reason as _excepthook_installed:
#: the hook closure reads _previous_excepthook out of this very dict at
#: call time, so resetting it here while the old hook is still
#: sys.excepthook is what made the recorder chain to itself.
_previous_excepthook = globals().get("_previous_excepthook")
_installed = globals().get("_installed", False)
#: Set when the file is over MAX_BYTES but could not be rotated (a
#: reader's handle blocks both rename and truncate on Windows). Verbose
#: records are dropped for the session so the cap still holds; crash
#: records (rare, flood-guarded) keep writing.
_rotation_blocked = False

#: Spend per NAMED PASS, survives the module reload like the rest.
_pass_spent: dict = globals().get("_pass_spent", {})


def begin_pass(name: str) -> None:
    """Start a pass, giving its per-item records a fresh allowance."""
    _pass_spent[name] = 0


def pass_budget(name: str, cap: int) -> bool:
    """True while this pass may still record a per-item diagnostic.

    `event()`'s flood guard keys on (category, message) and nothing
    else, so per-item records written in a loop share ONE key and go
    dark after `FLOOD_VERBATIM` for the rest of the SESSION - the
    geometry thumbnail pass recorded 5 of 273, and the survivors were
    always the first five files rather than a sample. Keying the guard
    on the data instead would defeat it, since every one of those
    records is unique.

    A per-pass budget keeps both properties: bounded volume, and a
    fresh allowance each time the pass runs. `dragengine` has its own
    richer version of this with a separate reserve for picks that hit.
    """
    if _pass_spent.get(name, 0) >= cap:
        return False
    _pass_spent[name] = _pass_spent.get(name, 0) + 1
    return True


def guarded(where: str):
    """Decorator for Qt slot entry points (mouse handlers, drop
    events). PySide prints a slot's exception to stderr and SWALLOWS
    it - sys.excepthook never fires, so a crashing drag/drop is
    invisible in this log. This records the traceback ALWAYS (crash
    tier, Debug Mode or not), then re-raises so stderr still shows it."""
    def _wrap(fn):
        import functools

        @functools.wraps(fn)
        def _inner(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception:
                exc_type, exc_value, exc_tb = sys.exc_info()
                _ensure_session()
                tb_text = "".join(
                    traceback.format_exception(exc_type, exc_value, exc_tb)
                )
                # Flood-guarded like the excepthook: this wraps MOUSE
                # handlers, so a crash here re-fires per mouse event -
                # the fastest way there is to fill a log.
                keep, count = _flood_check(
                    "slot:%s" % where, exc_type.__name__, tb_text
                )
                if keep:
                    record = {
                        "cat": "exception",
                        "msg": "slot crash in %s: %s"
                               % (where, exc_type.__name__),
                        "data": {"value": str(exc_value)},
                        "traceback": tb_text,
                    }
                    if count > FLOOD_VERBATIM:
                        record["data"]["repeat_count"] = count
                        record["data"]["suppressed"] = _suppressed_for(
                            "slot:%s" % where, exc_type.__name__,
                            tb_text, count)
                    _write(record)
                raise
        return _inner
    return _wrap


def probe() -> dict:
    """Live engine state, for instrumentation events: which module
    object answered and what it believes. If a 'panel ready' probe ever
    disagrees with the session header's module_id, two debug module
    objects exist (reload split-brain) and one of them is silently
    dropping events."""
    return {
        "module_id": id(sys.modules.get(__name__)),
        "module_name": __name__,
        "enabled": _enabled,
        "session_id": _session,
        "path": _path,
    }


class ExportRefused(Exception):
    """The export could not be made, WITH the reason.

    A bare False here would be indistinguishable from "the log was
    empty", which is the failure shape this project keeps finding: an
    honest empty result and a failure reported identically.
    """


def export_log(dest_dir: str) -> str:
    """Copy the log to `dest_dir` under a name that identifies the
    machine, and return the new path.

    Naming: amaze-<machine>-<os>-hou<version>-<YYYYmmdd-HHMMSS>.jsonl
    Two machines' logs therefore never collide, which is the whole
    point - a cross-platform bug needs both logs side by side, and
    "amaze_debug.jsonl" twice tells you nothing about which is which.

    This is a SNAPSHOT, taken by an explicit user action, to a folder
    the user chose. Nothing is written anywhere on its own: the log
    stays in the per-OS location, and no continuous mirroring happens.
    Anyone reading the result gets the author's file paths, asset and
    material names - which is exactly why it takes a deliberate act
    each time rather than a setting that can be left on.

    Raises ExportRefused with a readable reason - never returns a bare
    empty value, so the caller can always tell the user WHY.
    """
    source = log_path()
    if not dest_dir:
        raise ExportRefused("No destination folder was chosen.")
    if not os.path.exists(source):
        raise ExportRefused(
            "There is no log yet at %s - turn Debug Mode on, reproduce "
            "the problem, then export." % source)
    try:
        if os.path.getsize(source) == 0:
            raise ExportRefused(
                "The log exists but is empty - turn Debug Mode on and "
                "reproduce the problem first.")
    except OSError as exc:
        raise ExportRefused("Could not read the log: %s" % exc)

    try:
        version = _houdini_version_tag()
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        name = "amaze-%s-%s-hou%s-%s.jsonl" % (
            hostos.machine_name(), hostos.os_tag(), version, stamp)
        target = os.path.join(dest_dir, name)
        # A timestamp to the second still collides if the button is
        # double-clicked. Never overwrite a previous export.
        suffix = 1
        while os.path.exists(target):
            target = os.path.join(
                dest_dir, name[:-6] + "-%d.jsonl" % suffix)
            suffix += 1
        os.makedirs(dest_dir, exist_ok=True)
        shutil.copyfile(source, target)
    except OSError as exc:
        raise ExportRefused(
            "Could not write to %s: %s" % (dest_dir, exc))
    event("prefs", "log exported",
          to=target, bytes=os.path.getsize(target))
    return target


def _houdini_version_tag() -> str:
    """The running Houdini version, filename-safe, or "unknown"."""
    try:
        import hou
        return str(hou.applicationVersionString()).replace(".", "-")
    except Exception:                                    # noqa: BLE001
        return "unknown"


def log_path() -> str:
    """Where the log is written (shown in Preferences)."""
    return _path


def clear_log() -> tuple:
    """Empty the log and reset the session with it.

    Returns (ok, reason) - reason is "" on success.

    Preferences' Clear Log used to just `os.remove` the file, which
    left the ENGINE believing the deleted log was still its own:

    * `_session` still held the id whose header went with the file, so
      `_ensure_session` did not write a new one. The fresh log then had
      no environment header at all, and `tools/log-check.py` - the
      first thing anyone runs on a report - falls back to printing
      "Amaze PRE-STAMP ? ?" for a session it cannot identify.
    * The flood guard's counters survived too. A user clears the log
      precisely BECAUSE something keeps failing, so the very next
      occurrences are the ones already past FLOOD_VERBATIM: the clean
      capture they just made room for recorded nothing about the
      failure until it had happened ten times.

    Clearing is a diagnosis step, so it has to leave the log in the
    state a diagnosis needs: empty, headed, and counting from zero.
    """
    global _session, _seq, _rotation_blocked
    try:
        if os.path.exists(_path):
            os.remove(_path)
    except OSError as exc:
        return False, str(exc)
    # Cleared, not flushed. flush_repeats() writes each key's final
    # count, which belongs to the log that was just deleted - and it
    # walks _crash_counts, so calling it after the clear does nothing
    # at all. Dropping the counters IS the whole job here.
    _crash_counts.clear()
    _crash_recorded.clear()
    _crash_last_seen.clear()
    _alerted.clear()
    _seq = 0
    _rotation_blocked = False
    # Cleared, not ended: the next record starts a new session and
    # writes the environment header in front of it.
    _session = ""
    _ensure_session()
    return True, ""


def is_on() -> bool:
    """Guard expensive data-gathering at the call site with this."""
    return _enabled


def install() -> None:
    """Arm the crash recorder: capture UNCAUGHT exceptions only,
    independent of Debug Mode. Call once at panel construction.

    A genuine crash - an exception that propagates uncaught (including
    ones PySide swallows inside a Qt slot) - is always worth a record, so
    it's the one thing logged with Debug Mode off. Everything else
    (event/note/handled-exception) stays gated: Debug Off means off."""
    global _installed
    if _installed:
        return
    _installed = True
    _install_excepthook()


def _ensure_session() -> None:
    """Start a session (and write its header) if one hasn't begun. Lets an
    error land in a crash-only log - Debug Mode never turned on - still
    carrying the environment header (Houdini version, which renderer
    plugins loaded, ...) that context needs."""
    global _session
    if not _session:
        _session = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        _rotate()
        _write_session_header()


def configure(enabled: bool, path: str = "") -> None:
    """Turn VERBOSE logging on or off. Called at panel setup and whenever
    Preferences closes, so the switch takes effect without a restart.
    Crash capture (install()) is separate and always on."""
    global _enabled, _path, _rotation_blocked, _session
    was_on = _enabled
    enabled = bool(enabled)
    if path and path != _path:
        # A path change is a new file: same reset as redirect(), plus a
        # fresh session, or the new file's records carry the OLD file's
        # session id and no environment header - and tools/log-check.py
        # filters on the session id, so they are invisible to the one
        # command meant to read the log.
        _path = path
        _session = ""
        _rotation_blocked = False
        _crash_counts.clear()
        _crash_recorded.clear()
        _crash_last_seen.clear()
        # _alerted is deliberately NOT cleared here. It exists so a
        # rare-and-important dialog interrupts once, which is a fact
        # about the USER's session, not about logging - and toggling
        # Debug Mode would otherwise re-show what they already dismissed.
    elif path:
        _path = path
    if was_on and not enabled:
        # The off-marker must be written while logging is still ON -
        # event() drops records once _enabled is False, and a session
        # log that just goes silent looks like a crash.
        event("session", "debug mode turned off")
    _enabled = enabled
    install()
    # WHENEVER there is no session, not only on the off->on edge.
    # configure(True, new_path) while already on cleared _session
    # (three lines above, deliberately) and then never re-
    # established it, so every record in the new file carried an
    # empty session id and the file got no environment header -
    # and tools/log-check.py builds its session list from non-empty
    # ids, so it reported the file as having zero sessions and
    # printed none of its records. Exactly the outcome the comment
    # above says the clear exists to prevent.
    if _enabled and not _session:
        _ensure_session()
        event("session", "debug mode on")


def redirect(path: str) -> None:
    """Point the log at a different FILE, leaving Debug Mode alone.

    configure() is the user's switch and turns verbose logging ON as a
    side effect; this is for a process that must not write the real log
    at all, whatever its Debug Mode setting - the test suite, whose
    deliberate failures are recorded by the always-on crash tier.

    Starts a fresh session, so the new file gets its own header rather
    than continuing a numbering that lives in another file."""
    global _path, _session, _seq, _rotation_blocked
    _path = str(path)
    _session = ""
    _seq = 0
    # Reset the per-FILE state, or the new log inherits the old one's
    # problems. _rotation_blocked is a latch that was set on a rotation
    # failure and cleared NOWHERE in the codebase: verified that with it
    # set, redirecting to a brand-new empty file and turning Debug Mode
    # on wrote ZERO records - a fresh log silenced for the rest of the
    # process by a failure on a file it no longer uses. The flood counts
    # are per-file too: five identical failures in file A used to
    # silence the first occurrence in file B.
    _rotation_blocked = False
    _crash_counts.clear()
    _crash_recorded.clear()
    _crash_last_seen.clear()


def _rotate() -> None:
    global _rotation_blocked
    try:
        if not (os.path.exists(_path) and os.path.getsize(_path) > MAX_BYTES):
            return
    except OSError:
        return
    try:
        os.replace(_path, _path + ".1")
        return
    except OSError:
        pass
    # On Windows a process holding the file open (tail, editor, indexer)
    # blocks the rename with a sharing violation, where POSIX renames
    # over open handles. Copy-then-truncate works on most open files.
    try:
        shutil.copyfile(_path, _path + ".1")
        open(_path, "w", encoding="utf-8").close()
    except OSError:
        # A deny-write reader blocks even the truncate; the only way
        # left to honour MAX_BYTES is to stop appending verbose records.
        _rotation_blocked = True


def _write(record: dict) -> None:
    global _seq
    with _write_lock:
        _seq += 1
        record["n"] = _seq
        _write_locked(record)
    _maybe_rotate_inline()


def _write_locked(record: dict) -> None:
    """The write itself, called with _write_lock held."""
    record["t"] = round(
        datetime.datetime.now().timestamp(), 3
    )
    record["clock"] = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    record["session"] = _session
    try:
        os.makedirs(os.path.dirname(_path), exist_ok=True)
        # encoding= is NOT optional. Text-mode open() without it is
        # cp1252 on Windows (wiki), so any record carrying an accented
        # path or an online material title raises UnicodeEncodeError -
        # which the except below swallows. The loss is selective: the
        # UNUSUAL records are exactly the ones that vanish, from the
        # one instrument this project is required to read first.
        with open(_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=_stringify) + "\n")
    except Exception:
        # A logger must never be the thing that breaks the app.
        pass


#: Records between size checks. A getsize() per line would be silly; a
#: few hundred lines of slack against a 32MB cap is not.
_SIZE_CHECK_EVERY = 500

#: _write is reached from WORKER THREADS - _ConvertLoader.run calls
#: debug.event per item, in up to 8 of them - and it did an unlocked
#: `_seq += 1` plus an open/append per record. Concurrent converts could
#: duplicate sequence numbers and interleave large records, which is
#: exactly the log a reader has to trust. Survives reload for the same
#: reason the excepthook state does.
_write_lock = globals().get("_write_lock") or threading.Lock()


def _maybe_rotate_inline() -> None:
    """Enforce MAX_BYTES DURING a session, not only at its start.

    _rotate() was called from _ensure_session() alone, which runs once
    per process - so the cap held only at the NEXT launch. Measured with
    MAX_BYTES lowered to 4096: 400 events grew the file to 126,937 bytes
    with no rotation at all. The module docstring's promise that a
    forgotten Debug Mode "can't fill a disk" was true only across
    restarts, and a long Houdini session is exactly when it isn't."""
    if _seq % _SIZE_CHECK_EVERY:
        return
    try:
        if os.path.getsize(_path) > MAX_BYTES:
            _rotate()
    except OSError:
        pass


def _stringify(value):
    """Anything not JSON-native (hou.Node, QImage, Sdf.Path...) becomes
    its repr rather than killing the write."""
    try:
        return str(value)
    except Exception:
        return "<unserialisable>"


def _app_version() -> str:
    """The released version, without importing branding at module load
    (debug.py sits below it in the import order)."""
    try:
        from amaze import branding

        return str(branding.APP_VERSION)
    except Exception:                                       # noqa: BLE001
        return "unknown"


def _write_session_header() -> None:
    """Everything about the environment that has ever mattered when
    diagnosing something here, recorded once per session."""
    info = {
        "module_id": id(sys.modules.get(__name__)),
        # Which BUILD this session was - the first question any bug
        # report from someone else raises, and one git log cannot
        # answer once the code has left this machine.
        "amaze_version": _app_version(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "assetlib_env": os.environ.get("AMAZE", os.environ.get("ASSETLIB", "")),
    }
    try:
        import hou

        info["houdini"] = hou.applicationVersionString()
        info["product"] = hou.applicationName()
        # UI scaling, all three numbers: what Houdini reports, what Qt
        # already applies, and what theme.ui_px() actually uses (the
        # H21-macOS double-scale fix resolves the first two into the
        # third - this is how a log proves which scale ran). Recorded
        # here instead of printed at import: on Windows any print pops
        # the Houdini Console window open.
        try:
            info["ui_scale"] = float(hou.ui.globalScaleFactor())
        except Exception:
            pass
        try:
            from PySide6 import QtGui

            screen = QtGui.QGuiApplication.primaryScreen()
            if screen is not None:
                info["device_pixel_ratio"] = float(screen.devicePixelRatio())
        except Exception:
            pass
        try:
            from amaze.helpers import theme

            info["effective_ui_scale"] = float(theme.UI_SCALE)
        except Exception:
            pass
        # Which renderer plugins actually loaded - "Invalid node type
        # name" bugs have twice turned out to be a missing plugin.
        for label, type_name in (
            ("redshift", "redshift_vopnet"),
            ("octane", "octane_vopnet"),
            ("mtlx", "mtlxstandard_surface"),
        ):
            info["has_" + label] = bool(
                hou.vopNodeTypeCategory().nodeTypes().get(type_name)
            )
    except Exception as exc:
        info["houdini_probe_failed"] = str(exc)
    # Written DIRECTLY (not via event()) so the header lands even when
    # Debug Mode is off - a crash-only log still needs its environment.
    info["debug_mode"] = _enabled
    _write({"cat": "session", "msg": "session start", "data": info})


def prefs_snapshot(preferences) -> None:
    """Record the COMPLETE settings state - every key that would be
    written to settings.json, plus the folder/favorite lists. Paths
    included: they are local paths in a local log, and 'which library
    was open' is routinely the answer.

    Completeness is the point, not curiosity: this record is the
    RESTORE SOURCE when settings.json is lost or corrupted. A
    hand-picked subset once left renderer toggles and folder lists
    unrecoverable after a corruption, so the snapshot mirrors the
    saved file instead of sampling it. Written to the file even when
    Debug Mode is off - it costs one line per session and is the only
    thing that makes a settings loss cheap."""
    if preferences is None:
        return
    # The restore record needs its session id and environment header:
    # idempotent, and free when a session already exists.
    _ensure_session()
    data = {}
    try:
        # refresh_data() is the single producer of the settings dict
        # (the same one save() writes) - no disk access.
        refresh = getattr(preferences, "refresh_data", None)
        snapshot = refresh() if callable(refresh) else getattr(
            preferences, "data", {}
        )
        data.update(dict(snapshot or {}))
    except Exception as exc:
        data["snapshot_failed"] = str(exc)
    # Belt and braces: the live attribute values for the keys that
    # matter most, in case .data is stale relative to the object.
    for key in ("dir", "view_mode"):
        try:
            data["live_" + key] = getattr(preferences, key)
        except Exception:
            pass
    # The remembered Filter-menu choice, per section - one key since
    # 2026-08-02, where "last_renderer" was one value for Materials
    # alone. A grid filtered to nothing is a routine support question,
    # and this is the setting that answers it.
    try:
        data["live_section_filters"] = dict(
            getattr(preferences, "_section_filters", {}))
    except Exception:
        pass
    _write({"cat": "session", "msg": "preferences", "data": data})


def event(category: str, message: str, /, **data) -> None:
    """Record a structured entry. Silent when Debug Mode is off.

    `category` and `message` are POSITIONAL-ONLY (the `/`): callers pass
    arbitrary keys in **data, and a key named `category`, `message` or
    `where` would otherwise collide with these parameters and raise
    TypeError. That happened immediately in real use - an import passing
    `category=record.category` raised inside a Qt slot, which PySide
    swallows, so the import silently did nothing."""
    if not _enabled or _rotation_blocked:
        return
    # event() had NO flood guard - _flood_check covered only exception()
    # and the crash hook - and it is called per item from
    # _ConvertLoader.run in up to 8 worker threads. One stuck category
    # could bury a session's real content.
    keep, count = _flood_check("event:%s" % category, message, "")
    if not keep:
        return
    if count > FLOOD_VERBATIM:
        data = dict(data, repeat_count=count)
    _write({"cat": category, "msg": message, "data": data})


def note(message: str, /, **data) -> None:
    """Say something to the user AND record it.

    The `Amaze: ...` prints are the project's established diagnostic
    convention; this keeps them visible live while also capturing them
    (with structure) in a file that can be read afterwards.

    NOT ON WINDOWS, where the wiki is explicit: *any* Python print()
    pops the Houdini Console window open, and the jsonl log is the only
    safe sink for normal-operation output. A message is worth less than
    a console window jumping in front of the user's scene, and the line
    is not lost - it is in the log either way, which is where the
    project reads its own diagnostics from.

    This function is the SINK, and as of 2026-07-30 it is the only one:
    every diagnostic in the package routes through here or through
    event(). The single remaining bare print is `helpers/hostos.py`'s
    fallback around `from amaze.core import debug` - the one site where
    this sink is unreachable by construction.
    """
    if _enabled and not _rotation_blocked:
        _write({"cat": "note", "msg": message, "data": data})
    try:
        from amaze.helpers import hostos
        if hostos.is_windows():
            return
    except Exception:                                    # noqa: BLE001
        # Unknown platform: keep the established behaviour rather than
        # silently going quiet on the machines this is developed on.
        pass
    print("Amaze: " + message)


#: Keys already shown by alert() this session, so a condition inside a
#: loop interrupts ONCE. Survives the module reload the panel does on
#: every open, or reopening the panel would re-show what was dismissed.
_alerted: set = globals().get("_alerted", set())


def alert(message: str, /, key: str = "", **data) -> bool:
    """Tell the user something RARE and IMPORTANT, and record it.

    The third sink, and it exists because the other two cannot do this.
    `event()` is the log only. `note()` prints - and on Windows it
    returns BEFORE the print, while its log write is gated on Debug
    Mode, so on Windows with Debug Mode off `note()` says nothing
    anywhere. Routing "your save did not happen" through it would turn a
    visible failure into a silent one on the platform the no-print rule
    exists to protect.

    WHEN TO USE THIS: rare AND important. Settled 2026-07-30.
    Rare, because a dialog seen often is a dialog dismissed unread.
    Important, because interrupting for less spends the budget the
    rare-and-important case depends on. "You think you saved something
    and you didn't" is the case that earned it: fully reversible, and it
    still has to interrupt. Everything else goes to event() or note().

    ONCE PER KEY PER SESSION. Several of the conditions this serves sit
    inside loops - one icon per tile, one save per edit - and ten naive
    dialogs is a fault of its own. `key` defaults to the message, so
    callers with a formatted message MUST pass a stable key or the
    aggregation silently stops working. Returns True when it actually
    showed, so a caller can count what it suppressed and say so.

    NEVER for a failure the user cannot act on, and never with an
    exception string in it - practice.md ▸ *Writing for the user*.
    """
    stable = key or message
    if _enabled and not _rotation_blocked:
        _write({"cat": "alert", "msg": message,
                "data": dict(data, key=stable,
                             repeat=stable in _alerted)})
    if stable in _alerted:
        return False
    _alerted.add(stable)
    try:
        import hou
        from PySide6 import QtCore

        # DEFERRED, NEVER SYNCHRONOUS, and research.md gives two
        # independent reasons - either alone is disqualifying:
        #
        # * "A modal dialog opened inside dropEvent receives the drag's
        #   release click" and phantom-accepts the default button. These
        #   conditions fire from save and icon paths a drop can reach.
        # * "Native dialogs land UNDER an active Qt modal exec loop" -
        #   a displayMessage raised while a modal QDialog is exec'd was
        #   INVISIBLE behind it, and the nested cross-toolkit modal loops
        #   crashed Houdini once, natively and log-silent. Preferences is
        #   non-modal for exactly this reason, and two of the conditions
        #   this serves (settings unreadable, tile icons) fire while a
        #   dialog is open.
        #
        # singleShot(0, ...) lands it after the current event returns, so
        # there is no release click to steal and no exec loop to nest
        # inside. The log write above already happened, so nothing is
        # lost if the deferred call never runs.
        # hou.ui PROVEN AT QUEUE TIME, not discovered at delivery. The
        # except below can only catch what raises HERE - a lambda queued
        # on a timer detonates later, inside whatever processEvents runs
        # next, and under headless hython WITH a QApplication (the suite,
        # the thumbnail harness) that was an AttributeError erupting in
        # an unrelated constructor. Measured: the content-guard alert
        # took down a thumbnail-shutdown test two modules later.
        if not hasattr(hou, "ui"):
            raise AttributeError("no hou.ui in this session")
        QtCore.QTimer.singleShot(0, lambda: hou.ui.displayMessage(
            message, severity=hou.severityType.Warning,  # type: ignore
            title="Amaze",
        ))
        return True
    except Exception:                                    # noqa: BLE001
        # No hou, or no UI (hython, a batch render). The log already has
        # it; fall back to a print so a headless run is not silent - and
        # this path is not the Windows-console case the rule is about,
        # because there is no interactive session to interrupt.
        print("Amaze: " + message)
        return True


def exception(where: str, exc: BaseException | None = None, /, **data) -> None:
    """Record a full traceback for a HANDLED exception. Debug-Mode gated,
    like event()/note() - it's diagnostic detail for a reproduced bug,
    and Debug Off means off.

    A genuine CRASH (an *uncaught* exception) is different: the installed
    hook always records that, Debug Mode or not - see install()."""
    if not _enabled or _rotation_blocked:
        return
    text = traceback.format_exc() if exc is None else "".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__)
    )
    # Handled, but not necessarily rare: an except block inside a
    # per-item loop repeats as fast as the loop does.
    keep, count = _flood_check(
        "handled:%s" % where,
        type(exc).__name__ if exc is not None else "Exception",
        text,
    )
    if not keep:
        return
    if count > FLOOD_VERBATIM:
        data = dict(data, repeat_count=count,
                    suppressed=_suppressed_for(
                        "handled:%s" % where,
                        type(exc).__name__ if exc is not None else "Exception",
                        text, count))
    _write({
        "cat": "exception",
        "msg": where,
        "data": data,
        "traceback": text,
    })


@contextmanager
def timed(category: str, message: str, /, **data):
    """Time a block and record the duration - 'why is this slow' is a
    recurring question here (iconvert, Karma thumbnails, geometry
    renders)."""
    if not _enabled or _rotation_blocked:
        yield
        return
    start = datetime.datetime.now()
    failed = None
    try:
        yield
    except BaseException as exc:      # noqa: BLE001 - re-raised below
        failed = exc
        raise
    finally:
        ms = (datetime.datetime.now() - start).total_seconds() * 1000.0
        payload = dict(data)
        payload["ms"] = round(ms, 1)
        if failed is not None:
            payload["failed"] = str(failed)
        _write({"cat": category, "msg": message, "data": payload})


def image_stats(path: str) -> dict:
    """Measure a rendered image, so "it looks black" becomes a number.

    Added after a round where a thumbnail was reported black and there
    was no way to tell WHICH kind of black: an all-zero render, a
    transparent (zero-alpha) image, the missing-thumbnail placeholder, or
    a stale file from a previous attempt. Each has a different cause and
    they are indistinguishable by eye at tile size."""
    info = {"path": path}
    try:
        info["exists"] = os.path.exists(path)
        if not info["exists"]:
            return info
        info["bytes"] = os.path.getsize(path)
        info["mtime_age_s"] = round(
            datetime.datetime.now().timestamp() - os.path.getmtime(path), 1
        )
        from PySide6 import QtGui

        image = QtGui.QImage(path)
        if image.isNull():
            info["unreadable"] = True
            return info
        info["size"] = "%dx%d" % (image.width(), image.height())
        info["has_alpha"] = image.hasAlphaChannel()
        # Sample a grid rather than every pixel - cheap and plenty to
        # characterise a thumbnail.
        step = max(1, min(image.width(), image.height()) // 32)
        total = black = transparent = 0
        lum_sum = 0.0
        lum_max = 0.0
        for y in range(0, image.height(), step):
            for x in range(0, image.width(), step):
                colour = image.pixelColor(x, y)
                lum = (
                    0.2126 * colour.redF()
                    + 0.7152 * colour.greenF()
                    + 0.0722 * colour.blueF()
                )
                lum_sum += lum
                lum_max = max(lum_max, lum)
                if lum < 0.004:
                    black += 1
                if colour.alphaF() < 0.004:
                    transparent += 1
                total += 1
        if total:
            info["mean_luminance"] = round(lum_sum / total, 4)
            info["max_luminance"] = round(lum_max, 4)
            info["percent_black"] = round(100.0 * black / total, 1)
            info["percent_transparent"] = round(100.0 * transparent / total, 1)
            info["verdict"] = (
                "fully transparent" if transparent == total
                else "all black" if black == total
                else "mostly black" if black > total * 0.95
                else "has content"
            )
    except Exception as exc:
        info["stats_failed"] = str(exc)
    return info


def material_snapshot(shader, builder=None) -> dict:
    """What a shading network actually CONTAINS.

    Records the shader's effective input values, whether each is driven
    by a connection or a constant, and every texture path with whether
    the file is really on disk. Written after the imported-MaterialX
    round, where the question "is the material itself wrong, or only its
    thumbnail" could not be answered without opening it by hand."""
    if shader is None:
        return {}
    info = {}
    try:
        info["shader"] = shader.name()
        info["shader_type"] = shader.type().name()
        inputs = {}
        for name, source in zip(shader.inputNames(), shader.inputs()):
            parm = shader.parmTuple(name) or shader.parm(name)
            entry = {"driven_by": source.name() if source else None}
            if parm is not None:
                try:
                    entry["value"] = str(parm.eval())
                except Exception:
                    pass
            # A promoted parm that disagrees with the shader is the exact
            # shape of the opacity=0 bug.
            if builder is not None and source is not None and \
                    source.type().name() == "parameter":
                promoted = builder.parmTuple(name) or builder.parm(name)
                if promoted is not None:
                    try:
                        promoted_value = str(promoted.eval())
                        if promoted_value != entry.get("value"):
                            entry["promoted_DIFFERS"] = promoted_value
                    except Exception:
                        pass
            if source is not None or entry.get("value") not in (None, "(0.0,)"):
                inputs[name] = entry
        info["inputs"] = inputs
    except Exception as exc:
        info["snapshot_failed"] = str(exc)
    return info


def texture_snapshot(root) -> list:
    """Every file reference under a network, and whether it resolves.

    A texture path that does not exist renders black without any error
    Houdini would surface."""
    out = []
    if root is None:
        return out
    try:
        stack = [root]
        while stack:
            node = stack.pop()
            if node.isNetwork():
                stack.extend(node.children())
            for parm in node.parms():
                try:
                    template = parm.parmTemplate()
                    import hou

                    if not isinstance(template, hou.StringParmTemplate):
                        continue
                    if template.stringType() != hou.stringParmType.FileReference:
                        continue
                except Exception:
                    continue
                value = parm.eval()
                if not value:
                    continue
                out.append({
                    "node": node.name(),
                    "parm": parm.name(),
                    "path": value,
                    "exists": os.path.exists(value),
                })
    except Exception as exc:
        out.append({"snapshot_failed": str(exc)})
    return out


def node_snapshot(node, depth: int = 1) -> dict:
    """Describe a node the way these bugs need it: type, children and
    their types, and connectivity. Written for the material/builder
    questions that keep coming up ('is it actually a Karma builder',
    'what did editmaterial hand back', 'is the shader wired')."""
    if node is None:
        return {}
    try:
        info = {
            "path": node.path(),
            "type": node.type().name(),
            "is_network": node.isNetwork(),
        }
        try:
            info["shader_language"] = node.shaderLanguageName()
        except Exception:
            pass
        for parm_name in ("shader_rendercontextname", "tabmenumask"):
            parm = node.parm(parm_name)
            if parm is not None:
                info[parm_name] = parm.eval()
        if depth > 0 and node.isNetwork():
            children = []
            for child in node.children():
                entry = {
                    "name": child.name(),
                    "type": child.type().name(),
                }
                try:
                    entry["inputs"] = [
                        i.name() if i else None for i in child.inputs()
                    ]
                except Exception:
                    pass
                children.append(entry)
            info["children"] = children
            info["child_count"] = len(children)
        return info
    except Exception as exc:
        return {"snapshot_failed": str(exc)}


def _install_excepthook() -> None:
    """Capture unhandled exceptions that PROPAGATE (sys.excepthook).
    NOTE: exceptions inside Qt slots do NOT reach sys.excepthook -
    PySide prints and swallows them - so slot entry points use the
    guarded() decorator instead.

    A NOTE ON RELOAD, which broke this once: the flags above survive
    importlib.reload on purpose. panel.py reloads this module on every
    panel open, and reload re-executes the body into the SAME module
    dict - so a plain `_excepthook_installed = False` re-armed this
    installer while the PREVIOUS hook was still sys.excepthook. It then
    stored that hook as its own "previous", and since the closure reads
    _previous_excepthook out of the shared module dict at call time, the
    hook chained to itself: the next uncaught exception recursed until
    RecursionError and Houdini's own excepthook was never reached. The
    crash recorder died exactly when it was needed, from the second
    panel open onward. Reproduced, then fixed here.

    Keeping the FIRST hook installed loses nothing: every function it
    calls (_write, _flood_check, _ensure_session) is resolved through
    module globals at call time, so it picks up the reloaded code.
    """
    global _excepthook_installed, _previous_excepthook
    if _excepthook_installed:
        return
    # Belt and braces: never chain to a hook of our own, whatever the
    # flags say. This is the invariant; the flags are the optimisation.
    if getattr(sys.excepthook, "__module__", "") == __name__:
        _excepthook_installed = True
        return
    _previous_excepthook = sys.excepthook

    def hook(exc_type, exc_value, exc_tb):
        try:
            # ALWAYS captured, Debug Mode or not - this is the whole
            # point of the crash recorder. FLOOD-GUARDED: a crash inside
            # a timer/paint path can re-fire per event-loop tick (a
            # deleted-QLabel loop wrote 9000 identical records) - the
            # first few are recorded in full, then one count marker per
            # thousand.
            _ensure_session()
            tb_text = "".join(
                traceback.format_exception(exc_type, exc_value, exc_tb)
            )
            keep, count = _flood_check(
                "unhandled", exc_type.__name__, tb_text
            )
            if not keep:
                return
            record = {
                "cat": "exception",
                "msg": "unhandled: %s" % exc_type.__name__,
                "data": {"value": str(exc_value)},
                "traceback": tb_text,
            }
            if count > FLOOD_VERBATIM:
                record["data"]["repeat_count"] = count
                record["data"]["suppressed"] = _suppressed_for(
                    "unhandled", exc_type.__name__, tb_text, count)
            _write(record)
        finally:
            if _previous_excepthook is not None:
                _previous_excepthook(exc_type, exc_value, exc_tb)

    sys.excepthook = hook
    _excepthook_installed = True


# A session that ends mid-flood must still say how bad it got.
atexit.register(flush_repeats)
