"""OS integration and atomic writes: the only module that tests sys.platform. ▸r/platform-files"""

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


_HOME_PREFIX_RE = re.compile(r"^(?:[A-Za-z]:)?/(?:Users|home)/[^/]+(?=/)")  # where each OS puts a user's home


_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")    # `C:\` or `C:/`, the Windows absolute

_UNC_RE = re.compile(r"^[\\/]{2}[^\\/]")    # a Windows share, `\\server` or `//server` as the library stores it


def foreign_path(path: str) -> bool:
    """Whether `path` is spelled for another platform; `os.path` answers nonsense about one."""
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
    """A foreign absolute path moved under this machine's home, or unchanged if that is not here."""
    clean = (path or "").replace("\\", "/")
    match = _HOME_PREFIX_RE.match(clean)  # only homes under /Users or /home are recognised
    home = os.path.expanduser("~").replace("\\", "/").rstrip("/")
    if not match or not home:
        return path
    candidate = home + clean[match.end():]
    if not os.path.exists(candidate):
        return path  # usually, not always, keeps an unreachable shared mount under /home as is
    return candidate


def _ensure_dir(new_dir: str) -> str:
    """`new_dir`, made if missing; a failed write surfaces at the write site, not here."""
    check_sandbox(new_dir)
    try:
        os.makedirs(new_dir, exist_ok=True)
    except OSError:
        pass
    return new_dir


_cache_override = globals().get("_cache_override", "")  # user-chosen cache root, "" for the OS default; survives a reload

CACHE_DIR_ENV = "AMAZE_CACHE_DIR"  # environment override; beats a cleared user preference


_cache_generation = globals().get("_cache_generation", 0)  # bumped when the cache root moves; re-resolve a memo on change


def cache_generation() -> int:
    """How many times the cache root has been repointed this session."""
    return _cache_generation


def set_cache_override(path: str) -> None:
    global _cache_override, _cache_generation
    _cache_override = str(path or "").strip()
    _cache_generation += 1


def cache_root() -> str:
    """The per-user cache directory: the user's override, then $AMAZE_CACHE_DIR, else the OS's."""
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
    """Short filename-safe name for this OS, for naming exported files; never branch on it."""
    if is_macos():
        return "macos"
    if is_windows():
        return "windows"
    if is_linux():
        return "linux"
    return "unknown-os"


def machine_name() -> str:
    """This computer's name, filename-safe and capped at 32 characters, for naming exported logs."""
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
    return cleaned[:32] or os_tag()  # the OS tag when nothing survives


def open_path(path: str) -> None:
    """Open a file or folder with its default app, else reveal it in the file browser. Never raises."""
    if is_macos():
        if _call(["open", path]) != 0:  # no handler is a non-zero exit code here, not a raise
            reveal_path(path)
    elif is_windows():
        try:
            os.startfile(os.path.normpath(path))  # type: ignore[attr-defined]
        except OSError:
            reveal_path(path)  # `os.startfile` raises for an extension with no associated app
    else:
        if _call(["xdg-open", path]) != 0:
            reveal_path(path)


def _call(argv: list) -> int:
    """`subprocess.call` that cannot raise: the exit code, or 1 when the program is missing."""
    try:
        return subprocess.call(argv)
    except OSError as exc:
        try:
            from amaze.core import debug  # imported HERE, not at module level: debug imports hostos, so the other direction would be circular

            debug.note("could not run %s" % argv[0], error=str(exc))
        except Exception:                           # noqa: BLE001
            print("Amaze: could not run %s (%s)" % (argv[0], exc))
        return 1


def reveal_path(path: str) -> None:
    """Show a file selected in the system file browser, or a directory itself."""
    path = os.path.normpath(path)
    if is_macos():
        _call(["open", "-R", path])
    elif is_windows():
        _call(["explorer", "/select," + path])  # one argument, no space, or Explorer ignores /select
    else:
        target = path if os.path.isdir(path) else os.path.dirname(path)
        _call(["xdg-open", target])


_session_snapshots = globals().get("_session_snapshots", {})  # {path: monotonic time of last snapshot}
if isinstance(_session_snapshots, set):
    _session_snapshots = {path: 0.0 for path in _session_snapshots}  # a reload can hand the OLD build's set to this build's dict logic

SNAPSHOT_INTERVAL = 30 * 60  # seconds between snapshots of one file


def preserve_unreadable(path: str, why: str = "") -> str:
    """Copy an unparseable file to `<path>.unreadable`, write-once; the copy's path or ""."""
    if not path or not os.path.isfile(path):
        return ""
    try:
        if os.path.getsize(path) == 0:  # a 0-byte file is a sync placeholder, never preserved
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
    if existing > 0:  # write-once, except that a 0-byte `.unreadable` is replaced
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
        from amaze.core import debug  # imported here: debug imports hostos
        debug.event(kind, message, **data)
    except Exception:                                    # noqa: BLE001
        pass


def parses_as_json(raw: bytes) -> bool:
    """Whether `raw` is a document this package could load - the health test the backup tiers gate on."""
    try:
        json.loads(raw.decode("utf-8-sig"))  # utf-8-sig, as every reader of a library JSON file
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
    """`file_fingerprint` of the file at `path`, or None when unreadable; no parse. ▸r/peer-read"""
    try:
        with open(path, "rb") as handle:
            return file_fingerprint(handle.read())
    except OSError:
        return None


def peer_read(path: str, fingerprint=None) -> PeerFile:
    """Whether `path` changed since `fingerprint`, with the document; one read per call. ▸r/peer-read"""
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


LOCK_TRIES = 20             # ~1s at 50ms
LOCK_WAIT = 0.05


def lock_path(path: str) -> str:
    """Where the lock for `path` lives: this machine's cache, never beside the file."""
    digest = hashlib.sha256(
        canonical_path_key(path).encode("utf-8")).hexdigest()[:16]
    folder = os.path.join(cache_root(), "locks")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, digest + ".lock")


def _take_lock(handle) -> None:
    """One non-blocking exclusive attempt; OSError when held, or when the filesystem cannot lock."""
    try:
        import fcntl
    except ImportError:
        import msvcrt
        handle.seek(0)    # msvcrt locks at the current position; _drop_lock must use the same byte
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
    """Lock `path` on this machine for the body, yielding whether it was taken. ▸p/merge-needs-a-base"""
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
    """Name of one trace proving `path` existed before, or "" when nothing says it did."""
    found = existed_before_all(path, markers)
    return found[0] if found else ""


def existed_before_all(path: str, markers: tuple = (), names=None) -> list:
    """Every trace a file was here: bak tiers, unreadable, markers; `names` answers from a listing."""
    if not path:
        return []
    if names is not None:
        base = os.path.basename(path)
        traces = sorted(name for name in names if name.startswith(base + ".bak-"))
        if base + ".unreadable" in names:
            traces.append(base + ".unreadable")
        return traces or [marker for marker in markers if marker and marker in names]
    traces = sorted(glob.glob(glob.escape(path) + ".bak-*"))  # a library path may hold [ ] ? ▸r/glob-brackets
    unreadable = path + ".unreadable"
    if os.path.exists(unreadable):
        traces.append(unreadable)
    if traces:
        return [os.path.basename(trace) for trace in traces]
    directory = os.path.dirname(path)
    return [marker for marker in markers
            if marker and os.path.exists(os.path.join(directory, marker))]  # markers cover a file saved once


HISTORY_DAYS = 90  # daily history entries kept per file


LIBRARY_ID_KEY = "library_id"    # in the policy.json beside a file; `library_policy.library_id` mints it

_LIBRARY_IDS = globals().get("_LIBRARY_IDS", {})    # folder -> its library id, "" for none: one read each
_FOLLOWED = globals().get("_FOLLOWED", set())    # history folders already moved to their id this session

_LIBRARY_ID_SHAPE = re.compile(r"^[0-9a-f]{32}$")


def is_library_id(value) -> bool:
    return isinstance(value, str) and bool(_LIBRARY_ID_SHAPE.match(value))


def library_id_beside(for_path: str) -> str:
    """The library id the policy.json beside `for_path` holds, or ""; read once per folder."""
    folder = os.path.dirname(os.path.abspath(for_path))
    if folder not in _LIBRARY_IDS:
        found = ""
        try:
            with open(os.path.join(folder, "policy.json"), encoding="utf-8-sig") as handle:
                document = json.load(handle)
            value = document.get(LIBRARY_ID_KEY) if isinstance(document, dict) else None
            if is_library_id(value):
                found = value
        except (OSError, ValueError):
            found = ""
        _LIBRARY_IDS[folder] = found
    return _LIBRARY_IDS[folder]


def forget_library_id(folder: str) -> None:
    """Read the policy.json in `folder` again at the next ask; call after writing it."""
    _LIBRARY_IDS.pop(os.path.abspath(folder), None)


def history_root(for_path: str) -> str:
    """The machine-local history folder of a file's library, by its id when it has one, else by path."""
    library = os.path.dirname(os.path.abspath(for_path))
    key = canonical_path_key(library)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:10]
    label = safe_filename(os.path.basename(library) or "library")[:24]
    by_path = os.path.join(config_root(), "history", "%s-%s" % (label, digest))
    library_id = library_id_beside(for_path)
    if not library_id:
        return by_path
    by_id = os.path.join(config_root(), "history", "library-" + library_id)
    if by_path not in _FOLLOWED:
        _FOLLOWED.add(by_path)
        if os.path.isdir(by_path) and not os.path.exists(by_id):
            try:
                check_sandbox(by_id)
                os.rename(by_path, by_id)
                _record("history", "history folder now follows the library id",
                        source=by_path, target=by_id)
            except OSError as exc:
                _record("history", "history folder not moved to the library id",
                        source=by_path, target=by_id, error=str(exc))
    return by_id


def record_history(path: str, days: int = HISTORY_DAYS) -> str:
    """Keep one gzipped copy of `path` per day, machine-local; the entry's path or "" if none."""
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
        if not parses_as_json(current):  # a copy that does not parse is never recorded
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
    """Keep the newest `days` entries for one file, ordered by the date in the name, not mtime."""
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
    """Mint the write-once `.bak-first` from a just-created file; whether a floor was written."""
    first = path + ".bak-first"
    if not path or os.path.exists(first):
        return False  # an existing floor is never replaced
    try:
        with open(path, "rb") as handle:
            current = handle.read()
    except OSError as exc:
        _record("backup", "no restore floor seeded - the new file could "
                "not be read back", path=path, error=str(exc))
        return False
    if not parses_as_json(current):  # a floor is never made from content that does not parse
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
    """Snapshot `path` to a rolling `.bak-N` and a permanent `.bak-first`; never blocks the write."""
    check_sandbox(path)
    record_history(path)  # before the throttle: history is keyed by date, not by session
    last = _session_snapshots.get(path)
    if last is not None and time.monotonic() - last < SNAPSHOT_INTERVAL:
        return
    if not os.path.exists(path):
        return  # no marker for a file not yet created, so its first save gets a snapshot
    _session_snapshots[path] = time.monotonic()
    try:
        with open(path, "rb") as handle:
            current = handle.read()
    except OSError as exc:
        _session_snapshots.pop(path, None)  # drop the marker: a read failure is transient
        _record("backup", "no snapshot taken - the file could not be read",
                path=path, error=str(exc))
        return
    if not parses_as_json(current):  # never rotate in content that does not parse
        _session_snapshots.pop(path, None)  # drop the marker so a later healthy save is snapshotted
        _record("backup", "no snapshot taken - the file on disk does not "
                "parse", path=path, bytes=len(current))
        return
    try:
        first = path + ".bak-first"  # a first-seen copy, never rotated
        if not os.path.exists(first):
            shutil.copy2(path, first)
        else:
            try:
                with open(first, "rb") as handle:
                    floor_bytes = handle.read()
            except OSError:
                floor_bytes = None
            if floor_bytes is not None and not parses_as_json(floor_bytes):
                shutil.copy2(path, first)  # only an unreadable floor is replaced
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
                "rotated", path=path, error=str(exc))


def replace_file(src: str, dst: str) -> None:
    """`os.replace` with a brief retry, then a final attempt that raises to the caller."""
    check_sandbox(dst)
    for wait in (0.05, 0.15, 0.35):
        try:
            os.replace(src, dst)
            return
        except PermissionError:  # Windows raises for a destination held open for a moment
            time.sleep(wait)
    os.replace(src, dst)


class NoExclusiveRename(OSError):
    """This drive has no rename that refuses a taken name. ▸r/no-replace-rename"""


_RENAME_EXCL = 0x4    # macOS sys/stdio.h, for renamex_np
_RENAME_NOREPLACE = 0x1    # Linux linux/fs.h, for renameat2
_AT_FDCWD = -100    # Linux fcntl.h: a relative path resolves from the working folder, as in os.rename
_NO_SUCH_FLAG = frozenset((errno.ENOTSUP, errno.EOPNOTSUPP, errno.EINVAL, errno.ENOSYS))


@functools.lru_cache(maxsize=None)
def _libc():
    import ctypes
    return ctypes.CDLL(None, use_errno=True)


def _flagged_rename(source: bytes, dest: bytes) -> int:
    """0 when the rename that refuses a taken name renamed, else its errno. ▸r/no-replace-rename"""
    import ctypes
    try:
        if is_macos():
            code = _libc().renamex_np(source, dest, ctypes.c_uint(_RENAME_EXCL))
        elif is_linux():
            code = _libc().renameat2(_AT_FDCWD, source, _AT_FDCWD, dest,
                                     ctypes.c_uint(_RENAME_NOREPLACE))
        else:
            return errno.ENOTSUP
    except AttributeError:    # no such call in this C library: glibc before 2.28
        return errno.ENOTSUP
    return 0 if code == 0 else ctypes.get_errno()


def rename_exclusive(source: str, dest: str) -> bool:
    """Rename in one call that refuses a taken name, False when taken. ▸r/no-replace-rename"""
    if is_windows():
        try:
            os.rename(source, dest)    # Windows refuses a taken name itself
        except FileExistsError:
            return False
        return True
    code = _flagged_rename(os.fsencode(source), os.fsencode(dest))
    if code in (0, errno.EEXIST):
        return code == 0
    if code in _NO_SUCH_FLAG:    # the drive or the kernel has no such rename: exFAT, FAT32
        raise NoExclusiveRename(code, os.strerror(code), dest)
    raise OSError(code, os.strerror(code), source, None, dest)


_MKSTEMP_MODE = 0o600  # what `tempfile.mkstemp` creates with; promote_scratch recognises it


def _default_file_mode() -> int:
    """The mode a new file gets from the process umask, as `open(path, "w")` does. ▸r/atomic-writes"""
    mask = os.umask(0)  # briefly sets mask 0 for every thread, so call it once
    os.umask(mask)
    return 0o666 & ~mask


_DEFAULT_FILE_MODE = _default_file_mode()  # read once at import


def unique_scratch(path: str, suffix: str = ".writing",
                   create: bool = True) -> str:
    """A unique scratch path beside `path`, created empty unless `create=False`. ▸r/atomic-writes"""
    check_sandbox(path)
    directory = os.path.dirname(path) or "."  # same directory always: a rename cannot cross drives
    handle, scratch = tempfile.mkstemp(
        dir=directory, prefix=os.path.basename(path) + ".", suffix=suffix)  # `suffix` goes last, so it sets the extension
    os.close(handle)
    if not create:
        discard_scratch(scratch)  # the name only, for a writer that cannot be handed an existing file
    return scratch


def render_scratch(path: str, tag: str = "rendering") -> str:
    """A unique name for a renderer to write `path` to, its extension kept LAST ▸r/image-extension."""
    ext = os.path.splitext(path)[1] or ".png"
    return unique_scratch(path, suffix="." + tag + ext, create=False)


def promote_scratch(scratch: str, path: str) -> None:
    """fsync `scratch`, set the destination's mode and swap it into place; may raise. ▸r/atomic-writes"""
    check_sandbox(path)
    handle = os.open(scratch, os.O_RDWR)  # on Windows `os.fsync` needs a writable handle
    try:
        os.fsync(handle)  # before the swap, so the rename never points at a partial file
    finally:
        os.close(handle)
    mode = _DEFAULT_FILE_MODE
    try:
        existing = os.stat(path).st_mode & 0o7777
    except OSError:
        existing = -1
    if existing >= 0 and existing != _MKSTEMP_MODE:
        mode = existing  # keep the replaced file's mode; a 0600 one widens to the umask default
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
    """Whether an `os.scandir` entry is a symlink or, on Windows, any reparse point; opens nothing."""
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
    """Raise the OSError a delete would hit while another program holds `path`; Windows only."""
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
    """`os.unlink`, first clearing a read-only flag on Windows and restoring it if the delete fails."""
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
    """Remove a scratch file if it is still there. Never raises."""
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
    """Yield a unique scratch beside `path`; promote it on exit, remove it on any exception."""
    scratch = unique_scratch(path, suffix)
    try:
        yield scratch
        promote_scratch(scratch, path)
    finally:
        discard_scratch(scratch)  # several files promoted as one unit use the primitives instead


SANDBOX_VAR = "AMAZE_SANDBOX"  # the environment variable that arms the sandbox, below


class SandboxRefused(RuntimeError):
    """A write that would have left the sandbox; raised only while the sandbox is armed."""


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
    """Raise `SandboxRefused` for a write outside temp while armed. ▸p/hand-run-script-is-unguarded"""
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


FAILED_UNREACHABLE = "unreachable"  # the cause of a failed write in one word, to branch on
FAILED_READ_ONLY = "read-only"
FAILED_FULL = "full"
FAILED_HELD = "held"
FAILED_UNKNOWN = "unknown"

_FAILURE_CAUSES = {  # errno -> cause; an unlisted errno is FAILED_UNKNOWN ▸r/failed-write
    errno.ENOENT: FAILED_UNREACHABLE,
    errno.ENOTDIR: FAILED_UNREACHABLE,
    errno.EACCES: FAILED_READ_ONLY,
    errno.EPERM: FAILED_READ_ONLY,
    errno.EROFS: FAILED_READ_ONLY,
    errno.ENOSPC: FAILED_FULL,
    errno.EBUSY: FAILED_HELD,  # Windows reports a held file as EACCES, see _HELD_WINERRORS
    errno.ETXTBSY: FAILED_HELD,
}

_HELD_WINERRORS = frozenset((  # native Windows codes for a held destination, which `errno` cannot express ▸r/failed-write
    32,  # ERROR_SHARING_VIOLATION - in use by another process
    33,  # ERROR_LOCK_VIOLATION - another process locked part of it
))


def why_failed(exc: OSError, path: str = "") -> tuple:
    """(cause, sentence) for a write that raised, naming what the user must fix. ▸r/failed-write"""
    cause = _FAILURE_CAUSES.get(getattr(exc, "errno", None),
                                FAILED_UNKNOWN)
    if getattr(exc, "winerror", None) in _HELD_WINERRORS:
        cause = FAILED_HELD  # the native code outranks the errno, which reads a held file as EACCES
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
    return (stat.st_mtime_ns, stat.st_size)  # mtime and size together: cheap, not sound


def canonical_path_key(path: str) -> str:
    """A path as a stable dict or prefs key: normalized, with forward slashes on every OS."""
    return os.path.normpath(path).replace(os.sep, "/")


def comparable_path(path: str) -> str:
    """One spelling per file on THIS platform, for comparing paths: separators and case folded."""
    return os.path.normcase(os.path.normpath(path))


def _home_root() -> str:
    """Home in canonical spelling, its own function so a test can pin it."""
    return canonical_path_key(os.path.expanduser("~"))


def storage_path_key(path: str) -> str:
    """A path as the library stores it: `$AMAZE/...`, `~/...`, else the canonical absolute."""
    if not path:
        return ""  # empty stays empty, never "."
    trailing = "/" if str(path).endswith(("/", "\\")) else ""  # a trailing separator is kept
    path = canonical_path_key(path)
    amaze = os.environ.get("AMAZE", "")  # a Houdini package's `env` entries land in `os.environ`, so $AMAZE resolves here without `hou`
    for var, root in (("$AMAZE", canonical_path_key(amaze) if amaze else ""),  # $AMAZE first: the install may live under home
                      ("~", _home_root())):  # Python's home, not Houdini's $HOME ▸p/home-spelling-unproven
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
    """The inverse: a stored spelling to this machine's canonical absolute, trailing separator kept."""
    if not path:
        return ""
    trailing = "/" if path.endswith("/") else ""
    if path == "$AMAZE" or path.startswith("$AMAZE/"):
        root = os.environ.get("AMAZE", "")
        if not root:
            return path  # returned untouched when $AMAZE is not set
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
    """The entry of `extensions` that `name` ends with, or "", case-insensitively."""
    lowered = name.lower()
    best = ""
    for ext in extensions:
        ext = ext.lower()
        if lowered.endswith(ext) and len(ext) > len(best):
            best = ext  # the longest match wins, so `x.bgeo.sc` gives `.bgeo.sc`
    return best


class PathEscape(ValueError):
    """A composed path landed outside the directory it had to stay in."""


@functools.lru_cache(maxsize=64)
def _real_base(base: str) -> str:
    """`base` with its links resolved, once: a base retargeted later only refuses joins."""
    return os.path.realpath(base)


def _under_real_base(real_base: str, parts):
    """realpath(join(base, *parts)) built on the resolved base, a lstat a name; None: ask realpath."""
    names = []
    for part in parts:
        if os.path.isabs(part) or os.path.splitdrive(part)[0]:
            return None
        names += part.replace(os.altsep or os.sep, os.sep).split(os.sep)
    if not names or any(name in ("", ".", "..") for name in names):
        return None
    current = real_base
    for index, name in enumerate(names):
        current = os.path.join(current, name)
        try:
            st = os.lstat(current)
        except OSError:
            return os.path.join(current, *names[index + 1:])    # realpath appends what it cannot stat
        if (stat.S_ISLNK(st.st_mode)
                or getattr(st, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            return None    # a link or a junction: only realpath knows where it lands
    return current


def contained_join(base: str, *parts: str) -> str:
    """`os.path.join(base, *parts)`, raising `PathEscape` for a result outside `base`."""
    composed = os.path.join(base, *parts)
    real_base = _real_base(base)
    real_composed = _under_real_base(real_base, parts) or os.path.realpath(composed)
    if real_composed != real_base and not real_composed.startswith(
            real_base.rstrip(os.sep) + os.sep):
        raise PathEscape(
            "%r does not stay inside %r" % (composed, base))
    return composed


_WIN_RESERVED_NAMES = re.compile(
    r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$", re.IGNORECASE
)


def safe_filename(name: str, fallback: str = "unnamed") -> str:
    """A string made safe as a file or directory name on every OS, else `fallback`."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name))  # the characters Windows forbids
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
