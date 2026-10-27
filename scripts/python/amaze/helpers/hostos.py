"""The OS-integration engine, and the package's atomic writes: nothing else in the codebase may test sys.platform, name an OS path convention, or reach for Houdini's bundled binaries. ▸r/platform-files"""

import atexit
import contextlib
import errno
import functools
import glob
import gzip
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import typing

APP_DIR = "Amaze"


def is_macos() -> bool:
    return sys.platform == "darwin"


def is_windows() -> bool:
    return sys.platform == "win32"


def is_linux() -> bool:
    return sys.platform.startswith("linux")


def _home(*parts: str) -> str:
    return os.path.join(os.path.expanduser("~"), *parts)


_HOME_PREFIX_RE = re.compile(r"^(?:[A-Za-z]:)?/(?:Users|home)/[^/]+(?=/)")  # where each OS puts a user's home, and THE ONLY place in the package that may know it


_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")    # `C:\` or `C:/`, the Windows absolute

_UNC_RE = re.compile(r"^[\\/]{2}[^\\/]")    # a Windows share, `\\server` or `//server` as the library stores it


def foreign_path(path: str) -> bool:
    """Whether `path` is spelled for a DIFFERENT platform than the one running - a shared library carries both spellings, and `os.path` silently answers nonsense about the other one rather than refusing."""
    raw = str(path or "")
    if not raw:
        return False
    windows_spelled = bool(_DRIVE_RE.match(raw) or _UNC_RE.match(raw))
    if is_windows():
        return raw.startswith("/") and not windows_spelled
    return windows_spelled


def volume_unreachable(path: str) -> bool:
    """The path's volume is not mounted, which `os.path.isdir` cannot tell from a deleted folder."""
    if foreign_path(path):
        return True    # the other platform's spelling cannot be judged here, so it is never gone
    path = os.path.abspath(path)
    if is_windows():
        drive = os.path.splitdrive(path)[0]
        return bool(drive) and not os.path.exists(drive + os.sep)
    if path.startswith("/Volumes/"):
        parts = path.split("/")
        root = "/".join(parts[:3])      # /Volumes/<name>
        return not os.path.exists(root)
    return False


def rehome(path: str) -> str:
    """A foreign absolute path re-pointed at THIS machine's home, or the path unchanged when the rewrite does not exist here."""
    clean = (path or "").replace("\\", "/")
    match = _HOME_PREFIX_RE.match(clean)  # a home outside /Users or /home - a redirected Windows profile, a studio /export/home/<name>, a macOS network home - is not recognised, so the path stays dead and the sidebar shows it missing
    home = os.path.expanduser("~").replace("\\", "/").rstrip("/")
    if not match or not home:
        return path
    candidate = home + clean[match.end():]
    if not os.path.exists(candidate):
        return path  # the pattern matches ANY two components under /home, so this check is what stops a briefly unreachable shared mount being rewritten into this user's home - it stops it most of the time, not always
    return candidate


def _ensure_dir(new_dir: str) -> str:
    """`new_dir`, made if missing; a failed write surfaces at the write site, not here."""
    check_sandbox(new_dir)
    try:
        os.makedirs(new_dir, exist_ok=True)
    except OSError:
        pass
    return new_dir


_cache_override = globals().get("_cache_override", "")  # user-chosen cache location (Preferences > Library > Local Cache), "" meaning this OS's own convention. Read through `globals()` so it SURVIVES the module reload panel.py does on every panel open - a plain `= ""` cleared it before the panel re-set it, so every module that freezes a cache path at IMPORT captured the default root for the session

CACHE_DIR_ENV = "AMAZE_CACHE_DIR"  # environment override, which BEATS a cleared user preference - the suite needs a cache root that survives a panel construction (a panel reload calls set_cache_override("") for fixture prefs), and a render node may want its cache on local scratch


_cache_generation = globals().get("_cache_generation", 0)  # bumped whenever the cache root moves; a caller that MEMOISES a derived path stores this number with its memo and re-resolves when it changes. A counter rather than a callback registry: hostos is the bottom of the import graph and must not know its callers


def cache_generation() -> int:
    """How many times the cache root has been repointed this session."""
    return _cache_generation


def set_cache_override(path: str) -> None:
    global _cache_override, _cache_generation
    _cache_override = str(path or "").strip()
    _cache_generation += 1


def cache_root() -> str:
    """The per-user cache directory: the user's override when set, then $AMAZE_CACHE_DIR, else this OS's convention."""
    for candidate in (_cache_override,
                      os.environ.get(CACHE_DIR_ENV, "").strip(),
                      _sandboxed_root("cache")):
        if not candidate:
            continue
        check_sandbox(candidate)
        try:
            os.makedirs(candidate, exist_ok=True)
            return candidate
        except OSError:
            continue  # unusable - fall through to the next
    return _ensure_dir(_real_cache_root())


def _real_cache_root() -> str:
    """This OS's own per-user cache folder, never made here."""
    if is_macos():
        return _home("Library", "Caches", APP_DIR)
    if is_windows():
        local = os.environ.get("LOCALAPPDATA") or _home("AppData", "Local")
        return os.path.join(local, APP_DIR, "Cache")
    base = os.environ.get("XDG_CACHE_HOME") or _home(".cache")
    return os.path.join(base, APP_DIR)


def config_root() -> str:
    """The per-user settings folder: the sandbox's stand-in when armed, else this OS's own."""
    return _ensure_dir(_sandboxed_root("config") or real_config_root())


def log_root() -> str:
    """The per-user log folder: the sandbox's stand-in when armed, else this OS's own."""
    return _ensure_dir(_sandboxed_root("logs") or real_log_root())


def real_config_root() -> str:
    """This OS's own per-user settings folder, never inside the install, and never made here."""
    if is_macos():
        new = _home("Library", "Preferences", APP_DIR)  # where Houdini keeps its own, so it is the familiar place to look
    elif is_windows():
        roaming = os.environ.get("APPDATA") or _home("AppData", "Roaming")
        new = os.path.join(roaming, APP_DIR)
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or _home(".config")
        new = os.path.join(base, APP_DIR)
    return new


def real_log_root() -> str:
    """This OS's own per-user log folder, never made here."""
    if is_macos():
        new = _home("Library", "Logs", APP_DIR)
    elif is_windows():
        local = os.environ.get("LOCALAPPDATA") or _home("AppData", "Local")
        new = os.path.join(local, APP_DIR, "Logs")
    else:
        base = os.environ.get("XDG_STATE_HOME") or _home(".local", "state")
        new = os.path.join(base, APP_DIR)
    return new


def os_tag() -> str:
    """Short, filename-safe name for this OS, for NAMING exported files - a branch belongs in one of the is_* predicates above or in a hostver capability, never here."""
    if is_macos():
        return "macos"
    if is_windows():
        return "windows"
    if is_linux():
        return "linux"
    return "unknown-os"


def machine_name() -> str:
    """This computer's name reduced to filename-safe characters and capped at 32, for telling two machines' exported logs apart."""
    raw = ""
    for source in (lambda: platform.node(),
                   lambda: os.environ.get("COMPUTERNAME", ""),
                   lambda: os.environ.get("HOSTNAME", "")):
        try:
            raw = (source() or "").strip()
        except Exception:                                # noqa: BLE001
            raw = ""
        if raw:
            break
    raw = raw.split(".")[0]
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", raw).strip("-")
    return cleaned[:32] or os_tag()  # the OS tag rather than "" - a filename that collides silently is worse than one that is merely vague


def open_path(path: str) -> None:
    """Open a file or folder with the system's default handler, falling back to revealing it in the file browser when nothing is associated. Never raises."""
    if is_macos():
        if _call(["open", path]) != 0:  # macOS and Linux report `no application for this type` as a non-zero EXIT CODE and do not raise; Windows raises instead
            reveal_path(path)
    elif is_windows():
        try:
            os.startfile(os.path.normpath(path))  # type: ignore[attr-defined]
        except OSError:
            reveal_path(path)  # `os.startfile` raises for an extension with no associated app - a .jsonl log or a .mat on a stock machine - which read as the button doing nothing
    else:
        if _call(["xdg-open", path]) != 0:
            reveal_path(path)


def _call(argv: list) -> int:
    """`subprocess.call` that really cannot raise: the program's exit code, or 1 when the program itself is missing."""
    try:
        return subprocess.call(argv)
    except OSError as exc:  # `subprocess.call` DOES raise when the PROGRAM is missing (FileNotFoundError, verified on an emptied PATH) - `xdg-open` is genuinely absent on a Linux box without xdg-utils, and an uncaught raise inside a Qt slot is swallowed by PySide, leaving a button that does nothing with no trace anywhere
        try:
            from amaze.core import debug  # imported HERE, not at module level: debug imports hostos, so the other direction would be circular

            debug.note("could not run %s" % argv[0], error=str(exc))
        except Exception:                           # noqa: BLE001
            print("Amaze: could not run %s (%s)" % (argv[0], exc))
        return 1


def reveal_path(path: str) -> None:
    """Show a file selected in the system file browser, or the folder itself for a directory - the right verb for a file no app is associated with."""
    path = os.path.normpath(path)
    if is_macos():
        _call(["open", "-R", path])
    elif is_windows():
        _call(["explorer", "/select," + path])  # ONE argument, no space: `["explorer", "/select,", path]` produces `explorer /select, C:\\...`, and Explorer's syntax has no separator there, so it ignores the parameter and opens a default window
    else:
        target = path if os.path.isdir(path) else os.path.dirname(path)
        _call(["xdg-open", target])


_session_snapshots = globals().get("_session_snapshots", {})  # {path: monotonic seconds of the last snapshot}. TIME, not a once-per-session set, or the rolling .bak-N ring captures at most ONE state per launch and a day of work has a single restore point. Read through `globals()` so it survives panel.py's reload, or three panel reopens rotate every good .bak-N out
if isinstance(_session_snapshots, set):
    _session_snapshots = {path: 0.0 for path in _session_snapshots}  # a reload can hand the OLD build's set to this build's dict logic

SNAPSHOT_INTERVAL = 30 * 60  # seconds between snapshots of one file: fine-grained enough that an afternoon leaves several restore points, coarse enough that a save storm (an import loop, Render All) cannot chew all three slots inside a minute


def preserve_unreadable(path: str, why: str = "") -> str:
    """Copy a file we could not parse to `<path>.unreadable` WRITE-ONCE, returning that copy's path or "" - which is exactly what a caller may claim to the user, since the path may be this call's copy or an earlier one's. Says nothing itself."""
    if not path or not os.path.isfile(path):
        return ""
    try:
        if os.path.getsize(path) == 0:  # a 0-byte SOURCE is never preserved: a sync placeholder is ordinary, so the one rescue copy stays free for real damage
            _record("rescue", "nothing preserved - the file is 0 bytes, "
                    "which is a sync placeholder rather than damaged "
                    "content, so the one rescue copy is left free for the "
                    "real thing", path=path, why=why)
            return ""
    except OSError:
        return ""
    keep = path + ".unreadable"
    check_sandbox(keep)
    try:
        existing = os.path.getsize(keep) if os.path.exists(keep) else -1
    except OSError:
        existing = -1
    if existing > 0:  # write-once, like `.bak-first`, EXCEPT that a 0-byte `.unreadable` is replaced - the SECOND failure is usually a write we caused, so the first copy is the one holding the original
        _record("rescue", "a copy of an earlier unreadable file is already "
                "beside it and is never overwritten - the SECOND failure is "
                "usually a write we caused, so the first copy is the one "
                "that holds the original", path=path, kept=keep, why=why)
        return keep
    try:
        shutil.copy2(path, keep)
    except OSError as exc:
        _record("rescue", "nothing preserved - the copy itself failed",
                path=path, why=why, error=str(exc))
        return ""
    _record("rescue", "kept a copy of the unreadable file", path=path,
            kept=keep, why=why, replaced_empty=existing == 0)
    return keep


def _record(kind: str, message: str, **data) -> None:
    """`debug.event` that cannot take the caller down with it."""
    try:
        from amaze.core import debug  # imported inside the function, not at module level: debug imports hostos, so the other direction would be circular
        debug.event(kind, message, **data)
    except Exception:                                    # noqa: BLE001
        pass


def parses_as_json(raw: bytes) -> bool:
    """Whether `raw` is a document this package could load - the health test the backup tiers gate on."""
    try:
        json.loads(raw.decode("utf-8-sig"))  # utf-8-sig, matching every reader of a library-owned JSON file: a BOM is an ordinary artifact of a Windows editor or a sync client's conflict helper and must not make a healthy file look like garbage. A reader that diverges from this makes the helper call a file healthy that its own loader then refuses
    except (UnicodeDecodeError, ValueError):
        return False
    return True


PEER_ABSENT = "absent"          # nothing there to merge with
PEER_UNCHANGED = "unchanged"    # the same bytes this caller last saw
PEER_CHANGED = "changed"        # `document` holds what is on disk now
PEER_UNREADABLE = "unreadable"  # it is there and will not parse - REFUSE, never write over it
PEER_HELD = "held"              # it is there and would not open just now - keep what you hold


class PeerFile(typing.NamedTuple):
    verdict: str
    document: dict | None
    fingerprint: tuple | None
    error: str = ""


def file_fingerprint(raw: bytes) -> tuple:
    """`(size, sha256)` of these bytes - the ONE identity every merge path compares. ▸r/peer-read"""
    return (len(raw), hashlib.sha256(raw).hexdigest())


def fingerprint_of(path: str):
    """`file_fingerprint` of what is at `path`, or None when it cannot be read - for a caller that wants the IDENTITY and not the document, so it does not pay for a parse. ▸r/peer-read"""
    try:
        with open(path, "rb") as handle:
            return file_fingerprint(handle.read())
    except OSError:
        return None


def peer_read(path: str, fingerprint=None) -> PeerFile:
    """Whether another writer changed `path` since `fingerprint`, with the document when they did - the verdict is CONTENT, never a stat, and it costs a read per call, so price it per door and not per lookup. ▸r/peer-read"""
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except (FileNotFoundError, NotADirectoryError):
        return PeerFile(PEER_ABSENT, None, None)
    except OSError as exc:    # a lock or a permission: the file is still there
        return PeerFile(PEER_HELD, None, None, str(exc))
    current = file_fingerprint(raw)
    if fingerprint is not None and tuple(fingerprint) == current:
        return PeerFile(PEER_UNCHANGED, None, current)
    try:
        loaded = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        return PeerFile(PEER_UNREADABLE, None, current, str(exc))
    if not isinstance(loaded, dict):
        return PeerFile(PEER_UNREADABLE, None, current,
                        "document is %s, not an object" % type(loaded).__name__)
    return PeerFile(PEER_CHANGED, loaded, current)


LOCK_TRIES = 20             # ~1s at 50ms; `msvcrt.LK_LOCK` blocks up to 10s and `LK_NBLCK` gives up at once, so neither is used
LOCK_WAIT = 0.05


def lock_path(path: str) -> str:
    """Where the lock for `path` lives: this machine's cache, never beside the file - the library folder holds library data and a stray there is what three suite guards refuse."""
    digest = hashlib.sha256(
        canonical_path_key(path).encode("utf-8")).hexdigest()[:16]
    folder = os.path.join(cache_root(), "locks")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, digest + ".lock")


def _take_lock(handle) -> None:
    """One non-blocking exclusive attempt; OSError when somebody else holds it, or when this filesystem cannot lock at all."""
    try:
        import fcntl
    except ImportError:
        import msvcrt
        handle.seek(0)    # SYMMETRIC with _drop_lock: msvcrt.locking works at the CURRENT position, and an "a+" handle is not always at 0 - lock and unlock at different bytes never releases
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _drop_lock(handle) -> None:
    try:
        import fcntl
    except ImportError:
        import msvcrt
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextlib.contextmanager
def file_lock(path: str):
    """Hold an exclusive lock for `path` while the body runs, yielding whether it was taken. THIS MACHINE ONLY - the lock lives in its cache, so two machines on one library are not serialised by it. NEVER raises and never skips the body: it narrows a window, and the merge is the real guard. ▸p/merge-needs-a-base"""
    handle = None
    held = False
    try:
        handle = open(lock_path(path), "a+", encoding="utf-8", newline="\n")    # never written: the lock is a byte range
    except OSError:
        handle = None
    if handle is not None:
        for attempt in range(LOCK_TRIES):
            try:
                _take_lock(handle)
                held = True
                break
            except OSError:
                if attempt + 1 < LOCK_TRIES:
                    time.sleep(LOCK_WAIT)
    try:
        yield held
    finally:
        if handle is not None:
            if held:
                try:
                    _drop_lock(handle)
                except OSError:
                    pass
            try:
                handle.close()
            except OSError:
                pass


def existed_before(path: str, markers: tuple = ()) -> str:
    """Name of ONE surviving trace proving `path` was here before, or "" when nothing says it ever was - so an absent database is only treated as new when no trace contradicts that."""
    found = existed_before_all(path, markers)
    return found[0] if found else ""


def existed_before_all(path: str, markers: tuple = ()) -> list:
    """EVERY surviving trace, not just the first - the list a refusal must name, since a real database carries four and naming one at a time spends a recovery copy per run. Order: the .bak tiers sorted, then .unreadable, then the markers."""
    if not path:
        return []
    traces = sorted(glob.glob(glob.escape(path) + ".bak-*"))  # glob, not a fixed .bak-1..3 list, because `keep` is a parameter of snapshot_before_write; `escape` because a library directory is user-chosen and may contain [ ] ? ▸r/glob-brackets
    unreadable = path + ".unreadable"
    if os.path.exists(unreadable):
        traces.append(unreadable)
    if traces:
        return [os.path.basename(trace) for trace in traces]
    directory = os.path.dirname(path)
    return [marker for marker in markers
            if marker and os.path.exists(os.path.join(directory, marker))]  # BOTH kinds of trace are needed: the copies this module writes cover a file that has been overwritten, and the caller's seed markers cover a database saved once and never rewritten - a .bak-only test fails OPEN on exactly those


HISTORY_DAYS = 90  # daily history entries kept per file; a database is ~40 KB gzipped, so 90 days of four databases is well under 15 MB and the limit is about tidiness, not space


def history_root(for_path: str) -> str:
    """The MACHINE-LOCAL history directory for a file's library - deliberately not beside the file, because the `.bak-*` tiers live inside the synced library they exist to protect it against."""
    library = os.path.dirname(os.path.abspath(for_path))  # keyed by a digest of the canonical path so two libraries cannot collide, with a readable prefix so the folder can be identified by eye
    key = canonical_path_key(library)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:10]
    label = safe_filename(os.path.basename(library) or "library")[:24]
    return os.path.join(config_root(), "history", "%s-%s" % (label, digest))


def record_history(path: str, days: int = HISTORY_DAYS) -> str:
    """Keep ONE gzipped copy of `path` per calendar day, machine-local, returning the entry's path or "" when nothing was written (today already recorded, the file absent or unreadable, or its content not parsing). Never blocks or fails a write."""
    try:
        if not os.path.exists(path):
            return ""
        stamp = time.strftime("%Y-%m-%d")
        folder = history_root(path)
        entry = os.path.join(folder,
                             "%s.%s.gz" % (os.path.basename(path), stamp))
        check_sandbox(entry)
        if os.path.exists(entry):
            return ""                      # today is already recorded
        with open(path, "rb") as handle:
            current = handle.read()
        if not parses_as_json(current):  # the same rule the .bak tier follows: restore refuses to put a non-parsing copy back, so recording one spends the day's slot on garbage while the good state ages out behind it
            _record("history", "no history entry - the file does not parse",
                    path=path)
            return ""
        os.makedirs(folder, exist_ok=True)
        with scratch_beside(entry) as scratch:
            with gzip.open(scratch, "wb") as out:
                out.write(current)
        _prune_history(folder, os.path.basename(path), days)
        return entry
    except OSError as exc:
        _record("history", "history entry not written",
                path=path, error=str(exc))
        return ""


def _prune_history(folder: str, name: str, days: int) -> None:
    """Keep the newest `days` entries for one file, sorted by NAME not mtime - the name carries the date the copy is OF, while a restore or a file copy rewrites mtime."""
    try:
        entries = sorted(n for n in os.listdir(folder)
                         if n.startswith(name + ".") and n.endswith(".gz"))
    except OSError:
        return
    for stale in entries[:-days] if days > 0 else []:
        try:
            os.remove(os.path.join(folder, stale))
        except OSError:
            pass


def seed_restore_floor(path: str) -> bool:
    """Mint the write-once `.bak-first` from a file that has just been CREATED, returning whether a floor was written - the one cure for a store written exactly once, which otherwise has no trace at all for `existed_before` to find."""
    first = path + ".bak-first"
    if not path or os.path.exists(first):
        return False  # write-once is preserved here: an existing floor is never replaced, unlike snapshot_before_write's unreadable-floor repair
    try:
        with open(path, "rb") as handle:
            current = handle.read()
    except OSError as exc:
        _record("backup", "no restore floor seeded - the new file could "
                "not be read back", path=path, error=str(exc))
        return False
    if not parses_as_json(current):  # a permanent floor made of garbage is worse than no floor, since the rolling ring ages every good state out behind it
        _record("backup", "no restore floor seeded - what was just "
                "written does not parse", path=path, bytes=len(current))
        return False
    check_sandbox(first)
    try:
        shutil.copy2(path, first)
    except OSError as exc:
        _record("backup", "no restore floor seeded", path=first,
                error=str(exc))
        return False
    _record("backup", "restore floor seeded from a newly created file",
            path=first)
    return True


def snapshot_before_write(path: str, keep: int = 3) -> None:
    """At most once per SNAPSHOT_INTERVAL per file, copy the CURRENT on-disk version to a rolling `.bak-N` beside it (bak-1 newest) plus a permanent `.bak-first`, and record the day's history entry. Best-effort: a failed snapshot never blocks the write."""
    check_sandbox(path)
    record_history(path)  # BEFORE the throttle marker: the daily entry is keyed by date, not by session, so it must get its chance on the first save of TODAY even in a session that started yesterday
    last = _session_snapshots.get(path)
    if last is not None and time.monotonic() - last < SNAPSHOT_INTERVAL:
        return
    if not os.path.exists(path):
        return  # do NOT set the marker for a file that does not exist yet - the first save of a fresh install CREATES it, and marking here left the file with no restore point for its whole first session
    _session_snapshots[path] = time.monotonic()
    try:
        with open(path, "rb") as handle:  # `with`, not a bare open: on Windows a handle still held is precisely what makes the os.replace below raise PermissionError, the case replace_file has to retry around
            current = handle.read()
    except OSError as exc:
        _session_snapshots.pop(path, None)  # DISCARD THE MARKER - this branch is the transient one (a sync-client hold, a share that dropped for a second), so keeping it would spend the whole interval's one chance on a failure that has already passed
        _record("backup", "no snapshot taken - the file could not be read",
                path=path, error=str(exc))
        return
    if not parses_as_json(current):  # PARSE BEFORE ROTATING: `.bak-first` is written once and never rotated, so one half-synced launch would mint the permanent floor from garbage and the rolling ring would then age the good states out behind it
        _session_snapshots.pop(path, None)  # discard for the same reason as above; a later healthy save must not find the file already snapshotted
        _record("backup", "no snapshot taken - the file on disk does not "
                "parse", path=path, bytes=len(current))  # event, not note: every caller on this path already tells the user the file could not be read, and backup internals are not separately actionable
        return
    try:
        first = path + ".bak-first"  # an immutable first-seen copy, never rotated, because the rolling set can age a good state out in three panel opens
        if not os.path.exists(first):
            shutil.copy2(path, first)
        else:
            try:
                with open(first, "rb") as handle:
                    floor_bytes = handle.read()
            except OSError:
                floor_bytes = None
            if floor_bytes is not None and not parses_as_json(floor_bytes):
                shutil.copy2(path, first)  # write-once EXCEPT against an unreadable floor: a healthy file may replace a broken floor, while a PARSEABLE floor with different content is never touched - that difference is the floor doing its job
                _record("backup", "an unreadable .bak-first was replaced "
                        "by the current healthy file", path=first)
        newest = path + ".bak-1"
        if os.path.exists(newest):
            try:
                with open(newest, "rb") as previous:
                    if previous.read() == current:
                        return  # rotate only when the content really differs - an identical rewrite must not consume a slot
            except OSError:
                pass
        for i in range(keep, 1, -1):
            older = "%s.bak-%d" % (path, i - 1)
            if os.path.exists(older):
                os.replace(older, "%s.bak-%d" % (path, i))
        shutil.copy2(path, newest)
    except OSError as exc:
        _record("backup", "no snapshot taken - the tier could not be "
                "rotated", path=path, error=str(exc))  # nothing is lost - the floor above never rotates and `record_history` already ran - but the tier stopped advancing and only the log says so


def replace_file(src: str, dst: str) -> None:
    """`os.replace` with a brief retry, then a final attempt that RAISES - so a persistent hold still reaches the caller's error path."""
    check_sandbox(dst)
    for wait in (0.05, 0.15, 0.35):
        try:
            os.replace(src, dst)
            return
        except PermissionError:  # on Windows a momentarily-open destination (a cloud-sync scanner on the library dir, a viewer holding a thumbnail) raises where POSIX just swaps; the retries cover only the transient hold
            time.sleep(wait)
    os.replace(src, dst)


_MKSTEMP_MODE = 0o600  # what `tempfile.mkstemp` creates with - right for a scratch file in a world-writable /tmp, wrong for the file it is about to become. Named because promote_scratch has to recognise it on a DESTINATION too, see there


def _default_file_mode() -> int:
    """Permissions a file this module CREATES should get, derived from the process umask exactly as a plain `open(path, "w")` would be. ▸r/atomic-writes"""
    mask = os.umask(0)  # `os.umask` is a get-and-set with no read-only form, so this opens a window in which another thread creating a file sees mask 0 - real (hostos is imported when the panel opens, long after Houdini started its thread pool), microseconds wide, and its worst outcome is one file MORE permissive than asked
    os.umask(mask)
    return 0o666 & ~mask


_DEFAULT_FILE_MODE = _default_file_mode()  # read ONCE at import rather than per save, to open the umask window once


def unique_scratch(path: str, suffix: str = ".writing",
                   create: bool = True) -> str:
    """A UNIQUELY-named scratch path beside `path`, created empty unless `create=False`. A fixed scratch name is one shared buffer: two writers of the same destination interleave into it and the result can parse while holding both their records. ▸r/atomic-writes"""
    check_sandbox(path)
    directory = os.path.dirname(path) or "."  # SAME DIRECTORY ALWAYS: `os.rename` cannot cross drives on any OS, so a scratch in the system temp dir turns every save into a cross-device failure
    handle, scratch = tempfile.mkstemp(
        dir=directory, prefix=os.path.basename(path) + ".", suffix=suffix)  # `suffix` is appended LAST, so a prefix carrying an extension does not decide the on-disk format a writer picks from the name
    os.close(handle)
    if not create:
        discard_scratch(scratch)  # the name only, for a writer that cannot be handed an existing file and cannot be probed headlessly to prove otherwise (`assetutils.saveThumbnailFromViewer` needs a live scene viewer); pre-creating reserves the inode, which is the bonus this gives up
    return scratch


def render_scratch(path: str, tag: str = "rendering") -> str:
    """A unique name for a renderer to write `path` to, its extension kept LAST ▸r/image-extension."""
    ext = os.path.splitext(path)[1] or ".png"
    return unique_scratch(path, suffix="." + tag + ext, create=False)


def promote_scratch(scratch: str, path: str) -> None:
    """fsync `scratch`, give it the permissions the destination should have, and swap it into place. Raises whatever `replace_file` raises. ▸r/atomic-writes"""
    check_sandbox(path)
    handle = os.open(scratch, os.O_RDWR)  # O_RDWR, not O_RDONLY: on Windows `os.fsync` commits through a handle that must be WRITABLE, and this is called for files another process wrote (Houdini's own `saveItemsToFile`), so the descriptor cannot be kept from the write
    try:
        os.fsync(handle)  # BEFORE the swap, or the rename lands while the bytes are still only in the page cache and a power loss leaves an intact directory entry pointing at a partial file
    finally:
        os.close(handle)
    mode = _DEFAULT_FILE_MODE
    try:
        existing = os.stat(path).st_mode & 0o7777
    except OSError:
        existing = -1
    if existing >= 0 and existing != _MKSTEMP_MODE:
        mode = existing  # match the file being replaced so an existing library's permissions survive a save - EXCEPT 0600 exactly, which is what mkstemp creates with and therefore this package's own narrowing bug on disk; copying it would preserve owner-only forever and lock a colleague out of a shared library silently. Widening a deliberate `chmod 600` back to the umask default is the accepted residual, because the directions are not symmetric
    _set_mode(scratch, mode | stat.S_IWUSR)    # a read-only scratch is one Windows will not delete
    replace_file(scratch, path)
    if not mode & stat.S_IWUSR:
        _set_mode(path, mode)


def _set_mode(path: str, mode: int) -> None:
    """`os.chmod`, best-effort: a filesystem with no permission bits must not fail a save."""
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def is_link_like(entry) -> bool:
    """Whether an `os.scandir` entry can lead somewhere its own name does not: a symlink, or on Windows any reparse point - a junction is not `is_symlink()`, and `os.walk` follows it whatever `followlinks` says. Read from the listing, so it opens nothing."""
    try:
        if entry.is_symlink():
            return True
        if is_windows():
            attributes = entry.stat(follow_symlinks=False).st_file_attributes
            return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except OSError:
        return True    # unreadable: resolve it rather than guess its real path
    return False


def check_deletable(path: str) -> None:
    """Raise the OSError deleting `path` would raise because another program holds it open; POSIX deletes an open file, so only Windows can refuse."""
    if not is_windows():
        return
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                     wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                     wintypes.HANDLE)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    delete, share_all, open_existing = 0x00010000, 0x7, 3
    handle = kernel32.CreateFileW(os.path.abspath(path), delete, share_all, None,
                                  open_existing, 0, None)
    if handle in (None, wintypes.HANDLE(-1).value):    # a holder that did not share delete: Python's own open() is one
        code = ctypes.get_last_error()
        raise OSError(errno.EACCES, ctypes.FormatError(code).strip(), path, code)
    kernel32.CloseHandle(handle)


def remove_file(path: str) -> None:
    """`os.unlink`, clearing a read-only flag first on Windows, which refuses to delete one where POSIX asks only the folder; the flag is put back when the delete fails anyway."""
    if not is_windows():
        os.unlink(path)
        return
    mode = os.stat(path).st_mode
    if not mode & stat.S_IWRITE:
        os.chmod(path, mode | stat.S_IWRITE)
    try:
        os.unlink(path)
    except OSError:
        _set_mode(path, mode)
        raise


def discard_scratch(scratch: str) -> None:
    """Remove a scratch file if it is still there. Never raises - but a scratch left behind is an unowned file a directory scan then has to learn to ignore, which is how live assets get reported as orphans."""
    if not scratch or not os.path.exists(scratch):
        return
    try:
        os.remove(scratch)
        return
    except OSError:
        _set_mode(scratch, stat.S_IREAD | stat.S_IWRITE)    # Windows will not delete a read-only file
    try:
        os.remove(scratch)
    except OSError as exc:
        _record("write", "a scratch file could not be removed",
                path=scratch, error=str(exc))


@contextlib.contextmanager
def scratch_beside(path: str, suffix: str = ".writing"):
    """Yield a unique scratch beside `path`, fsync it and rename it over `path` on the way out; on ANY exception remove it and re-raise, so a raising writer cannot litter the library."""
    scratch = unique_scratch(path, suffix)
    try:
        yield scratch
        promote_scratch(scratch, path)
    finally:
        discard_scratch(scratch)  # not on OSError, not on a serialisation failure, not on KeyboardInterrupt - a successful promote has already renamed it away, so this is a no-op then. A caller promoting SEVERAL files as one unit (an asset's .mat and .interface) uses the primitives directly instead


SANDBOX_VAR = "AMAZE_SANDBOX"  # the environment variable that arms the sandbox, below


class SandboxRefused(RuntimeError):
    """A write that would have left the sandbox - an exception rather than a refusal code, because a write that quietly does nothing is a probe reporting results it never produced. Nothing in the product sets the variable, so nothing in the product can raise this."""


def sandboxed() -> bool:
    return os.environ.get(SANDBOX_VAR, "") in ("1", "true", "yes")


SANDBOX_HOME_VAR = "AMAZE_SANDBOX_HOME"  # read only while armed; the suite points it into its temp dir


def sandbox_home() -> str:
    """The temp folder standing in for the user's own while armed, made on first ask; "" unarmed."""
    if not sandboxed():
        return ""
    home = os.environ.get(SANDBOX_HOME_VAR, "").strip()
    if not home:
        home = tempfile.mkdtemp(prefix="amaze_sandbox_home_")
        os.environ[SANDBOX_HOME_VAR] = home  # the environment, so a reload and a child find the same one
        atexit.register(shutil.rmtree, home, True)
    return home


def _sandboxed_root(kind: str) -> str:
    home = sandbox_home()
    return os.path.join(home, kind) if home else ""


def check_sandbox(path: str) -> None:
    """Raise `SandboxRefused` for a write that would land outside a temporary directory, when the sandbox is armed. Any script run by hand against a live machine arms it. ▸p/hand-run-script-is-unguarded"""
    if not sandboxed():
        return
    resolved = os.path.realpath(path)
    root = os.path.realpath(tempfile.gettempdir()) + os.sep
    if not resolved.startswith(root):
        raise SandboxRefused(
            "%s is armed, so this run may only write inside %s - refusing "
            "to write %s. If this is a real library or a real settings "
            "file, the script is pointed at live data."
            % (SANDBOX_VAR, root, resolved))


class _Recorded:
    """A text stream that keeps every piece written through it."""

    def __init__(self, stream) -> None:
        self._stream = stream
        self.pieces: list = []

    def write(self, text: str) -> int:
        self.pieces.append(text)
        return self._stream.write(text)


def write_json_atomic(path: str, data, indent: int = 4,
                      sort_keys: bool = False, serialised=None) -> tuple:
    """The JSON front door, never half-done; `serialised` is the caller's utf-8 dumps of `data`."""
    check_sandbox(path)
    with scratch_beside(path) as scratch:
        if serialised is not None:
            with open(scratch, "wb") as stream:
                stream.write(serialised)
            return file_fingerprint(serialised)
        with open(scratch, "w", encoding="utf-8", newline="\n") as stream:  # LF on Windows too, or no json.dumps compare ever matches
            recorded = _Recorded(stream)
            json.dump(data, recorded, indent=indent, sort_keys=sort_keys)
    return file_fingerprint("".join(recorded.pieces).encode("utf-8"))


FAILED_UNREACHABLE = "unreachable"  # what a failed write WAS, in one word - the cause kept separate from the sentence so a caller can branch (log, retry, offer Repair) without matching on prose
FAILED_READ_ONLY = "read-only"
FAILED_FULL = "full"
FAILED_HELD = "held"
FAILED_UNKNOWN = "unknown"

_FAILURE_CAUSES = {  # errno -> cause; an errno ABSENT here falls through to FAILED_UNKNOWN rather than being guessed from its name, and the wiki table is what says which of these were actually reproduced ▸r/failed-write
    errno.ENOENT: FAILED_UNREACHABLE,
    errno.ENOTDIR: FAILED_UNREACHABLE,
    errno.EACCES: FAILED_READ_ONLY,
    errno.EPERM: FAILED_READ_ONLY,
    errno.EROFS: FAILED_READ_ONLY,
    errno.ENOSPC: FAILED_FULL,
    errno.EBUSY: FAILED_HELD,  # never reached on the platform it was added for - Windows spells a held file EACCES, see _HELD_WINERRORS
    errno.ETXTBSY: FAILED_HELD,
}

_HELD_WINERRORS = frozenset((  # native Windows codes for a held destination, which `errno` cannot express ▸r/failed-write
    32,  # ERROR_SHARING_VIOLATION - in use by another process
    33,  # ERROR_LOCK_VIOLATION - another process locked part of it
))


def why_failed(exc: OSError, path: str = "") -> tuple:
    """(cause, a complete sentence) for a write that raised - THE one owner for turning an `OSError` into something a user can act on, naming the object they have to fix and claiming no cause at all for an errno nobody measured. ▸r/failed-write"""
    cause = _FAILURE_CAUSES.get(getattr(exc, "errno", None),
                                FAILED_UNKNOWN)
    if getattr(exc, "winerror", None) in _HELD_WINERRORS:
        cause = FAILED_HELD  # the native code OUTRANKS the errno, which is documented as an approximate POSIX translation of it and lands access-denied, sharing-violation and lock-violation all on EACCES - so without this a held file reads as a read-only folder
    where = os.path.dirname(path) or path
    if cause == FAILED_UNREACHABLE:
        sentence = ("the folder it lives in cannot be reached right now"
                    + (":\n" + where if where else "")
                    + "\n\nIf it is in a synced or network folder, it "
                      "will work again once that folder is back.")
    elif cause == FAILED_READ_ONLY:
        sentence = ("the folder it lives in is read-only"
                    + (":\n" + where if where else "")
                    + "\n\nThe file itself being read-only would not "
                      "stop this - it is the folder's permissions.")
    elif cause == FAILED_FULL:
        sentence = "the disk is full."
    elif cause == FAILED_HELD:
        sentence = ("another program is holding the file open"
                    + (":\n" + path if path else "") + ".")
    else:
        sentence = ("the disk reported: %s."
                    % (getattr(exc, "strerror", None) or exc))
    return cause, sentence


def disk_state(path: str):
    """`(mtime_ns, size)` for `path`, or None if it is not there - the per-asset content stat."""
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)  # a tuple, not an mtime alone: a write inside the same nanosecond tick still changes the size, and a write that keeps the size still moves the mtime. Cheap, not sound


def canonical_path_key(path: str) -> str:
    """A filesystem path as a stable dictionary/prefs key: normalized, forward slashes on EVERY OS, because stored keys travel through JSON as forward slashes while `os.path.join` output is backslashed on Windows."""
    return os.path.normpath(path).replace(os.sep, "/")


def comparable_path(path: str) -> str:
    """One spelling per file on THIS platform, for comparing paths: separators and case folded."""
    return os.path.normcase(os.path.normpath(path))


def _home_root() -> str:
    """Home in canonical spelling - its own function so a test can pin it, where patching `expanduser` would patch the world."""
    return canonical_path_key(os.path.expanduser("~"))


def storage_path_key(path: str) -> str:
    """A path as the LIBRARY stores it: `$AMAZE/...` under the install tree, `~/...` under home, the canonical absolute when neither covers it - one entry that resolves on every machine sharing the library."""
    if not path:
        return ""  # empty stays empty: `normpath("")` is `"."`, and a truthy `"."` key slips every `if not key` guard downstream
    trailing = "/" if str(path).endswith(("/", "\\")) else ""  # a location's identity CARRIES its trailing separator everywhere the store is compared, and normpath strips it - so it is remembered here and put back on whatever spelling wins
    path = canonical_path_key(path)
    amaze = os.environ.get("AMAZE", "")  # a Houdini package's `env` entries land in `os.environ`, so $AMAZE resolves here without `hou`
    for var, root in (("$AMAZE", canonical_path_key(amaze) if amaze else ""),  # $AMAZE FIRST: the install lives under home on every current machine, so home-first would mean the $AMAZE spelling can never fire
                      ("~", _home_root())):  # PYTHON's home, expanded by `expand_storage_path` and nothing else - and on Windows that is a DIFFERENT root from Houdini's `$HOME`, which defaults to Documents, so a path under Documents matches neither variable and stores as a machine-specific absolute ▸p/home-spelling-unproven
        if not root or root in ("/", "."):
            continue
        trimmed = root.rstrip("/")
        if path == trimmed:
            return var + trailing
        if path.startswith(trimmed + "/"):
            return var + path[len(trimmed):] + trailing
    if path != "/" and trailing and not path.endswith("/"):
        return path + trailing
    return path


def expand_storage_path(path: str) -> str:
    """The inverse: a stored spelling back to THIS machine's canonical absolute, preserving a trailing separator."""
    if not path:
        return ""
    trailing = "/" if path.endswith("/") else ""
    if path == "$AMAZE" or path.startswith("$AMAZE/"):
        root = os.environ.get("AMAZE", "")
        if not root:
            return path  # a `$AMAZE` spelling with no $AMAZE in the environment comes back UNTOUCHED - unresolvable is a fact the caller can see, not one to guess around
        expanded = canonical_path_key(
            root.rstrip("/\\") + path[len("$AMAZE"):])
    elif path == "~" or path.startswith("~/"):
        expanded = canonical_path_key(_home_root() + path[1:])
    else:
        expanded = canonical_path_key(path)
    if trailing and expanded != "/" and not expanded.endswith("/"):
        return expanded + trailing
    return expanded


def matched_extension(name: str, extensions) -> str:
    """The entry of `extensions` that `name` ends with, or "" - case-insensitively, because the filesystems this runs on are."""
    lowered = name.lower()
    best = ""
    for ext in extensions:
        ext = ext.lower()
        if lowered.endswith(ext) and len(ext) > len(best):
            best = ext  # LONGEST WINS, so `x.bgeo.sc` reports `.bgeo.sc` and not `.bgeo`; the caller uses the answer as a label and as a cache key and the short one is wrong for both, so the order of the caller's tuple must not matter
    return best


class PathEscape(ValueError):
    """A composed path landed outside the directory it had to stay in."""


@functools.lru_cache(maxsize=64)
def _real_base(base: str) -> str:
    """`base` with its links resolved, once: a base retargeted later only refuses joins."""
    return os.path.realpath(base)


def contained_join(base: str, *parts: str) -> str:
    """`os.path.join(base, *parts)`, raising `PathEscape` for anything that lands outside `base` - asset filenames are composed from an id that comes verbatim out of `library.json`, which the app does not author alone and cannot assume is honest."""
    composed = os.path.join(base, *parts)
    real_base = _real_base(base)
    real_composed = os.path.realpath(composed)
    if real_composed != real_base and not real_composed.startswith(
            real_base.rstrip(os.sep) + os.sep):
        raise PathEscape(
            "%r does not stay inside %r" % (composed, base))
    return composed


_WIN_RESERVED_NAMES = re.compile(
    r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$", re.IGNORECASE
)


def safe_filename(name: str, fallback: str = "unnamed") -> str:
    """A string made safe as a file or directory name on EVERY OS, falling back to `fallback` when nothing survives. Any content name (an online material title) passes through here before becoming a path."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name))  # the characters Windows forbids: angle brackets, colon, quote, slashes, pipe, question mark, asterisk, controls
    cleaned = cleaned.rstrip(". ")  # Windows silently DROPS a trailing dot or space, which changes the name behind the caller's back
    if not cleaned:
        return fallback
    if _WIN_RESERVED_NAMES.match(cleaned.split(".")[0]):
        cleaned = "_" + cleaned  # the reserved device names are invalid with any extension, so the split is on the stem
    return cleaned


def bundled_binary(hfs: str, name: str) -> str | None:
    """Absolute path of a binary in Houdini's own bin folder, or None."""
    path = os.path.join(hfs or "", "bin", name)
    if os.path.exists(path):
        return path
    exe = path + ".exe"  # Windows ships them with an .exe suffix
    if os.path.exists(exe):
        return exe
    return None
