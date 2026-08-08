"""The OS-integration engine: every platform branch lives HERE.

One module owns everything that differs between macOS, Windows and
Linux - cache/log locations, opening paths in the system file browser, locating Houdini's bundled binaries. Nothing else in the
codebase may test sys.platform or hardcode an OS path convention; a new
platform quirk gets a function here, not a branch at a call site.

Locations follow each OS's own convention (the old code used macOS's
~/Library/... everywhere, which created a literal fake "Library" folder
under home on Windows and Linux):

    cache_root()         macOS    ~/Library/Caches/Amaze
                         Windows  %LOCALAPPDATA%/Amaze/Cache
                         Linux    $XDG_CACHE_HOME|~/.cache/Amaze
    log_root()           macOS    ~/Library/Logs/Amaze
                         Windows  %LOCALAPPDATA%/Amaze/Logs
                         Linux    $XDG_STATE_HOME|~/.local/state/Amaze

Both migrate ONCE from every legacy location (the Amaze-era macOS
dirs, the literal ~/Library/... dirs the old code created on
Windows/Linux, and the pre-rebrand egMatLib dir) by renaming the old
directory into place, so nothing regenerates just because the location
became correct.
"""

import contextlib
import glob
import gzip
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time

APP_DIR = "Amaze"


def is_macos() -> bool:
    return sys.platform == "darwin"


def is_windows() -> bool:
    return sys.platform == "win32"


def is_linux() -> bool:
    return sys.platform.startswith("linux")


def _home(*parts: str) -> str:
    return os.path.join(os.path.expanduser("~"), *parts)


def migrate_legacy_file(directory: str, old_name: str, new_name: str) -> bool:
    """Rename `old_name` to `new_name` inside `directory`, once.

    True only when a rename actually happened. Does nothing if the old
    file is absent or the new one already exists - the new name always
    wins, so a half-migrated folder is not re-migrated over.

    The rename is best-effort by design: every caller is carrying a
    pre-rename artifact forward (a debug log, a seed marker) and none
    of them may cost the user an action if it fails. This is the
    directory version's file-sized sibling; there were three separate
    copies of it - core/debug.py, core/code_library.py and
    core/gradient_library.py - each with its own silent `except
    OSError: pass`.

    Same-directory only, so `os.rename` is enough: the cross-volume
    `shutil.move` fallback `_migrated_dir` needs cannot apply here.
    """
    if not directory or not old_name or not new_name:
        return False
    old_path = os.path.join(directory, old_name)
    new_path = os.path.join(directory, new_name)
    if not os.path.exists(old_path) or os.path.exists(new_path):
        return False
    try:
        os.rename(old_path, new_path)
    except OSError:
        return False
    return True


#: Where each OS puts a user's home. THE ONLY place in the package
#: that may know this - prefs.py carried it as a regex, which
#: hostos.py's own docstring forbids ("Nothing else in the codebase may
#: test sys.platform or hardcode an OS path convention; a new platform
#: quirk gets a function here, not a branch at a call site").
_HOME_PREFIX_RE = re.compile(r"^(?:[A-Za-z]:)?/(?:Users|home)/[^/]+(?=/)")


def rehome(path: str) -> str:
    """A foreign absolute path re-pointed at THIS machine's home, or
    the path unchanged.

    For a library or folder carried over from the other machine, whose
    stored path is under someone's home directory that does not exist
    here. Only trusted when the result really exists, so a wrong guess
    changes nothing.

    KNOWN LIMITS, both real and both worth logging rather than hiding:

    * a home that is not under /Users or /home - a redirected Windows
      profile (D:/Profiles/<name>), a studio NFS layout
      (/export/home/<name>), a macOS network home - is not recognised,
      so the path stays dead and the sidebar shows it missing;
    * the pattern matches ANY two components under /home, so a shared
      mount at /home/projects/textures that is momentarily unreachable
      would be rewritten into this user's home if that happens to
      exist. The existence check is what stops it most of the time,
      not a guarantee.

    A substitution is RECORDED, because a silent one leaves the user
    looking at a different directory than the one they stored with no
    way to tell.
    """
    clean = (path or "").replace("\\", "/")
    match = _HOME_PREFIX_RE.match(clean)
    home = os.path.expanduser("~").replace("\\", "/").rstrip("/")
    if not match or not home:
        return path
    candidate = home + clean[match.end():]
    if not os.path.exists(candidate):
        return path
    return candidate


def _migrated_dir(new_dir: str, legacy_candidates: list) -> str:
    """Ensures new_dir exists, first adopting the newest legacy dir
    found by renaming it into place (a move, so existing caches/logs
    survive the location change instead of regenerating)."""
    if not os.path.exists(new_dir):
        for old in legacy_candidates:
            if os.path.isdir(old):
                try:
                    os.makedirs(os.path.dirname(new_dir), exist_ok=True)
                    os.rename(old, new_dir)
                except OSError:
                    # rename cannot cross drives (a redirected
                    # %LOCALAPPDATA% lands the new dir on another
                    # volume than the legacy one) - move instead.
                    try:
                        shutil.move(old, new_dir)
                    except OSError:
                        pass
                break
    try:
        os.makedirs(new_dir, exist_ok=True)
    except OSError:
        # Callers treat the dir as best-effort; a failed write there
        # surfaces at the write site, never at import time.
        pass
    return new_dir


# Optional user-chosen cache location (Preferences > Library > Local
# Cache). Set once at panel setup and again when Preferences closes;
# "" means each OS's own convention below.
#
# Survives reload: panel.py reloads this module on every panel open, and
# a plain `= ""` here cleared the user's cache location BEFORE the panel
# re-set it at setup - so every module that freezes a cache path at
# IMPORT (matx_library's preview and catalogue paths) captured the
# default root instead, and Online Materials kept writing to the old
# location for the session.
_cache_override = globals().get("_cache_override", "")

#: Environment override, which BEATS a cleared user preference.
#: The test suite needs a cache root that survives a panel construction:
#: opening a panel reloads this module and then calls
#: set_cache_override(prefs.cache_dir), which is "" for fixture prefs -
#: so a module-global alone was reset mid-run and the suite went back to
#: sweeping the user's REAL thumbnail cache (ThumbnailCache.clear()
#: deletes every texture_thumbnails_* and geo_thumbnails_* it finds).
#: Same mechanism as $AMAZE_LOG_DIR, for the same reason. Also useful
#: for a render node that wants its cache on local scratch.
CACHE_DIR_ENV = "AMAZE_CACHE_DIR"


#: Bumped whenever the cache root moves. Callers that MEMOISE a path
#: derived from it (scene_captures's capture directory) store this number
#: with their memo and re-resolve when it changes - reading an int is
#: free, where re-deriving the path is the migration this exists to
#: stop running per paint. A counter rather than a callback registry:
#: hostos is the bottom of the import graph and must not know its
#: callers.
_cache_generation = globals().get("_cache_generation", 0)


def cache_generation() -> int:
    """How many times the cache root has been repointed this session."""
    return _cache_generation


def set_cache_override(path: str) -> None:
    global _cache_override, _cache_generation
    _cache_override = str(path or "").strip()
    _cache_generation += 1


def cache_root() -> str:
    """The per-user cache directory: the user's override when set, then
    $AMAZE_CACHE_DIR, else this OS's convention."""
    for candidate in (_cache_override,
                      os.environ.get(CACHE_DIR_ENV, "").strip()):
        if not candidate:
            continue
        try:
            os.makedirs(candidate, exist_ok=True)
            return candidate
        except OSError:
            continue  # unusable - fall through to the next
    if is_macos():
        new = _home("Library", "Caches", APP_DIR)
        legacy = [
            _home("Library", "Caches", "AssetLib"),
            _home("Library", "Caches", "egMatLib"),
        ]
    elif is_windows():
        local = os.environ.get("LOCALAPPDATA") or _home("AppData", "Local")
        new = os.path.join(local, APP_DIR, "Cache")
        # The old mac-style code created a literal ~/Library tree here.
        legacy = [_home("Library", "Caches", "AssetLib")]
    else:
        base = os.environ.get("XDG_CACHE_HOME") or _home(".cache")
        new = os.path.join(base, APP_DIR)
        legacy = [_home("Library", "Caches", "AssetLib")]
    return _migrated_dir(new, legacy)


def config_root() -> str:
    """The per-user PREFERENCES directory, per this OS's convention.

    Settings used to live in $AMAZE - inside the install - which put a
    user's library path and favorites in the plugin folder, and in a
    git working tree for anyone who installed by cloning. They belong
    where every other app on the machine keeps them:

      * macOS   ~/Library/Preferences/Amaze   (where Houdini keeps its
                own, so it is the familiar place to look)
      * Windows %APPDATA%/Amaze
      * Linux   $XDG_CONFIG_HOME/Amaze, else ~/.config/Amaze
    """
    if is_macos():
        new = _home("Library", "Preferences", APP_DIR)
        legacy = [_home("Library", "Preferences", "AssetLib")]
    elif is_windows():
        roaming = os.environ.get("APPDATA") or _home("AppData", "Roaming")
        new = os.path.join(roaming, APP_DIR)
        legacy = [os.path.join(roaming, "AssetLib")]
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or _home(".config")
        new = os.path.join(base, APP_DIR)
        legacy = [os.path.join(base, "AssetLib")]
    return _migrated_dir(new, legacy)


def log_root() -> str:
    """The per-user log directory, per this OS's convention."""
    if is_macos():
        new = _home("Library", "Logs", APP_DIR)
        legacy = [_home("Library", "Logs", "AssetLib")]
    elif is_windows():
        local = os.environ.get("LOCALAPPDATA") or _home("AppData", "Local")
        new = os.path.join(local, APP_DIR, "Logs")
        legacy = [_home("Library", "Logs", "AssetLib")]
    else:
        base = os.environ.get("XDG_STATE_HOME") or _home(".local", "state")
        new = os.path.join(base, APP_DIR)
        legacy = [_home("Library", "Logs", "AssetLib")]
    return _migrated_dir(new, legacy)


def os_tag() -> str:
    """Short, filename-safe name for this OS.

    For naming exported files, not for branching - a branch belongs in
    one of the is_* predicates above or in a hostver capability.
    """
    if is_macos():
        return "macos"
    if is_windows():
        return "windows"
    if is_linux():
        return "linux"
    return "unknown-os"


def machine_name() -> str:
    """This computer's name, reduced to filename-safe characters.

    Used to tell two machines' exported logs apart. Falls back to the
    OS tag rather than to something empty, because a filename that
    collides silently is worse than one that is merely vague.
    """
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
    return cleaned[:32] or os_tag()


def open_path(path: str) -> None:
    """Opens a file or folder with the system's default handler
    (Finder/Explorer window for a folder). Best-effort on every OS:
    subprocess.call never raises on failure, so the Windows branch
    must not either (os.startfile raises for extensions with no
    associated app - .jsonl, .mat)."""
    # Every platform reports "no application for this type" its own
    # way: macOS/Linux return a non-zero EXIT CODE (they do not raise),
    # Windows raises. In all three cases the honest fallback is to
    # reveal the file in the file browser - a .jsonl log has no opener
    # on a stock machine, which looked like the button doing nothing.
    if is_macos():
        if _call(["open", path]) != 0:
            reveal_path(path)
    elif is_windows():
        try:
            os.startfile(os.path.normpath(path))  # type: ignore[attr-defined]
        except OSError:
            reveal_path(path)
    else:
        if _call(["xdg-open", path]) != 0:
            reveal_path(path)


def _call(argv: list) -> int:
    """subprocess.call that really cannot raise.

    The docstring above has always claimed "subprocess.call never raises
    on failure". It does when the PROGRAM ITSELF is missing:
    FileNotFoundError, verified on an emptied PATH. `open` and
    `explorer` always exist, but xdg-open does not - a Linux workstation
    or render node without xdg-utils is ordinary - and panel.py's "Open
    Library Folder" calls this unguarded, so it was an uncaught
    exception inside a Qt slot, which PySide swallows: a button that
    does nothing, with no trace anywhere."""
    try:
        return subprocess.call(argv)
    except OSError as exc:
        # Imported HERE, not at module level: debug imports hostos, so
        # the other direction would be circular.
        try:
            from amaze.core import debug

            debug.note("could not run %s" % argv[0], error=str(exc))
        except Exception:                           # noqa: BLE001
            print("Amaze: could not run %s (%s)" % (argv[0], exc))
        return 1


def reveal_path(path: str) -> None:
    """Shows a file selected in the system file browser (folder view
    with the file highlighted), or the folder itself for a directory.
    The right verb for files no app is associated with (a .jsonl log
    on Windows has no opener, but its folder always shows)."""
    path = os.path.normpath(path)
    if is_macos():
        _call(["open", "-R", path])
    elif is_windows():
        # ONE argument: "/select,<path>", no space. Passing "/select,"
        # and the path separately produces `explorer /select, C:\...`,
        # and Explorer's documented syntax has no separator there - it
        # ignores the parameter and opens a default window instead.
        # This is the path "Open Log" takes on Windows (.jsonl has no
        # association on a stock install), so the button reliably opened
        # the wrong window - the exact symptom open_path was written to
        # fix.
        _call(["explorer", "/select," + path])
    else:
        target = path if os.path.isdir(path) else os.path.dirname(path)
        _call(["xdg-open", target])


#: {path: monotonic seconds of the last snapshot}. TIME, not a
#: once-per-session set: the old gate meant the rolling .bak-N ring
#: captured at most ONE state per launch, so a day of work in one
#: session had a single restore point - the ring existed and mostly
#: held air. Throttled rather than every-save because a save storm
#: (an import loop, Render All) must not chew all three slots inside a
#: minute; the content check inside snapshot_before_write already
#: refuses to spend a slot on an identical state.
#:
#: Survives the module reload - panel.py reloads hostos on every panel
#: open, and a plain literal here made every reopen look like a fresh
#: session, so three reopens rotated every good .bak-N out.
_session_snapshots = globals().get("_session_snapshots", {})
if isinstance(_session_snapshots, set):
    # A reload can hand the OLD build's set to this build's dict logic.
    _session_snapshots = {path: 0.0 for path in _session_snapshots}

#: Seconds between snapshots of one file. Half an hour: fine-grained
#: enough that an afternoon leaves several restore points, coarse
#: enough that the ring is not spent by one busy minute.
SNAPSHOT_INTERVAL = 30 * 60



def preserve_unreadable(path: str, why: str = "") -> str:
    """Copy a file we could not parse to `<path>.unreadable`, ONCE.

    The policy this serves is written down: an unreadable file is NOT an
    empty one, and the difference is everything - the model loads empty,
    believes it is complete, and the first save makes it true (measured:
    200 gradients -> 1 after one truncated launch plus one save).

    Never overwritten once written, like `.bak-first`: the SECOND
    failure is usually a write we caused, so keeping the first copy is
    what keeps the original. Returns the copy's path, or "" if there was
    nothing to preserve or the copy failed.

    prefs.py grew its own version of this before it was shared; this is
    the one new callers should use.

    TWO DEGENERATE CASES, both of which made the one rescue slot useless:

    * A 0-BYTE SOURCE IS NOT WORTH PRESERVING. A sync placeholder is a
      real, ordinary state for a file in a synced library, and copying it
      spent the never-overwritten slot on nothing - so the genuinely
      truncated file that arrived a minute later got no copy at all. ""
      is returned, and nothing is created.
    * A 0-BYTE `.unreadable` IS REPLACED. Write-once is right for a copy
      that holds bytes; a copy that holds none is not evidence of
      anything, and keeping it forever locked the slot shut.

    The return value is what the CALLER may claim to the user: a path
    means a copy is genuinely there (this call's or an earlier one's),
    "" means there is nothing beside the file and no message may say
    there is. The log line distinguishes the two, since "we kept a copy
    just now" and "a copy from an earlier incident is still there" are
    different facts during a diagnosis and read identically otherwise.

    NOTHING HERE SPEAKS TO THE USER, and the return value is why. Every
    caller on this path already prints a full paragraph about the file it
    could not read, and both of them now name the copy - or do not - from
    what this returned, so a printed line from in here was a second
    paragraph about the same event, in vocabulary (rescue slot, sync
    placeholder, write-once) the reader cannot act on separately. The
    helper records; the caller speaks. It used to print, and the three
    lines below were the loudest thing in a suite run.
    """
    import shutil

    if not path or not os.path.isfile(path):
        return ""
    try:
        if os.path.getsize(path) == 0:
            _record("rescue", "nothing preserved - the file is 0 bytes, "
                    "which is a sync placeholder rather than damaged "
                    "content, so the one rescue copy is left free for the "
                    "real thing", path=path, why=why)
            return ""
    except OSError:
        return ""
    keep = path + ".unreadable"
    try:
        existing = os.path.getsize(keep) if os.path.exists(keep) else -1
    except OSError:
        existing = -1
    if existing > 0:
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
    """debug.event that cannot take the caller down with it. Imported
    inside the function rather than at module level: debug imports hostos,
    so the other direction would be circular."""
    try:
        from amaze.core import debug
        debug.event(kind, message, **data)
    except Exception:                                    # noqa: BLE001
        pass


def parses_as_json(raw: bytes) -> bool:
    """Whether `raw` is a document this package could load.

    utf-8-sig, matching every reader of a library-owned JSON file: a
    byte-order mark is an ordinary artifact of a file that has been
    through a Windows editor or a sync client's conflict helper, and
    the loaders read one fine - so a BOM must not make a healthy file
    look like garbage here.

    The docstring used to claim "every reader in the package" and that
    was false for three of them (settings.json, gradients.json,
    policy.json read plain utf-8 until 2026-08-08), so this helper
    called a file healthy, the backup tier copied it into the
    write-once tier, and only the loader refused it. The claim is
    narrowed to what it can enforce; the divergent readers were
    brought across in the same change.
    """
    try:
        json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        return False
    return True


def existed_before(path: str, markers: tuple = ()) -> str:
    """Name of a surviving trace that proves `path` was here before, or
    "" when nothing says it ever was.

    ABSENT IS ONLY "NEW" WHEN NOTHING SAYS THE FILE WAS EVER HERE. A
    database can be missing for one instant for reasons that have
    nothing to do with the user deleting it - a sync placeholder still
    arriving, a conflict rename, a partial restore - and the loaders
    that treated that instant as "new library" seeded an empty file over
    it. Measured 2026-07-29: cops.json 5,537 bytes / 8 records -> 96
    bytes / 0 records in one panel open, and gradients.json 290,454
    bytes / 388 gradients -> 39 bytes / 0.

    Two kinds of trace, and BOTH are needed - neither covers the real
    library on its own:

    * the copies THIS module writes beside a file it is about to
      overwrite (`.bak-N`, `.bak-first`, `.unreadable`). Both return
      early for a path that does not exist, so a copy can only be there
      because the original was. Measured on the real library: cops.json
      has four, gradients.json and code.json have NONE.
    * `markers` - sibling files in the same directory whose only writer
      runs after that database has been successfully saved (the seed
      markers). Measured on the real library: `.amaze_gradient_seed_v1`
      and `.amaze_code_starter_v1` are both there.

    So a `.bak`-only test fails OPEN on exactly the two files with no
    `.bak` - it looks like a guard and is not one. The caller passes the
    markers that apply to ITS database; the answer is a name, so the
    refusal can tell the user which trace it is going on.
    """
    found = existed_before_all(path, markers)
    return found[0] if found else ""


def existed_before_all(path: str, markers: tuple = ()) -> list:
    """EVERY surviving trace, not just the first - the list a refusal
    must name.

    `existed_before` answers the yes/no question and returns one name,
    and three refusals interpolated that one name as the complete
    instruction ("remove %s as well and the next launch starts a fresh
    one"). Measured on the real library: cops.json and library.json
    each carry four traces, so following the sentence verbatim removed
    one and the next launch named the next - four runs, four different
    sentences, each spending a recovery copy. Same order as before:
    the .bak tiers sorted, then .unreadable, then the markers.
    """
    if not path:
        return []
    # glob, not a fixed .bak-1..3 list: `keep` is a parameter of
    # snapshot_before_write, so the highest N is not this function's to
    # assume. escape() because a library directory is a user-chosen path
    # and may legitimately contain [ ] ? characters.
    traces = sorted(glob.glob(glob.escape(path) + ".bak-*"))
    unreadable = path + ".unreadable"
    if os.path.exists(unreadable):
        traces.append(unreadable)
    if traces:
        return [os.path.basename(trace) for trace in traces]
    directory = os.path.dirname(path)
    return [marker for marker in markers
            if marker and os.path.exists(os.path.join(directory, marker))]


#: How many daily history entries to keep per file. A database is
#: ~40 KB gzipped, so 90 days of four databases is well under 15 MB -
#: cheap enough that the limit is about tidiness, not space.
HISTORY_DAYS = 90


def history_root(for_path: str) -> str:
    """The machine-local history directory for a file's library.

    NOT beside the file, and that is the whole point. The `.bak-*` tiers
    live inside the library, and the library lives in a synced folder -
    measured: the sync client tracks 15 in-library `.bak` paths, so the
    restore points are inside the tree they exist to protect against,
    exactly as this module's own docstring warns ("sync services
    propagate corruption and deletion").

    Keyed by a digest of the library's canonical path so two libraries
    cannot collide, with a readable prefix so the folder can be
    identified by eye when someone goes looking.
    """
    library = os.path.dirname(os.path.abspath(for_path))
    key = canonical_path_key(library)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:10]
    label = safe_filename(os.path.basename(library) or "library")[:24]
    return os.path.join(config_root(), "history", "%s-%s" % (label, digest))


def record_history(path: str, days: int = HISTORY_DAYS) -> str:
    """Keep ONE gzipped copy of `path` per calendar day, machine-local.

    The in-library `.bak-*` ring answers "undo the last few writes". It
    cannot answer "this file was already wrong yesterday, and the sync
    has since carried that everywhere" - every copy it holds is in the
    same synced tree, and a rolling ring of three is easily spent by the
    corruption itself.

    Returns the entry's path, or "" when nothing was written (today is
    already recorded, the file is absent or unreadable, or the content
    does not parse). Best-effort throughout: history is a safety net and
    must never block or fail a write.
    """
    try:
        if not os.path.exists(path):
            return ""
        stamp = time.strftime("%Y-%m-%d")
        folder = history_root(path)
        entry = os.path.join(folder,
                             "%s.%s.gz" % (os.path.basename(path), stamp))
        if os.path.exists(entry):
            return ""                      # today is already recorded
        with open(path, "rb") as handle:
            current = handle.read()
        # The same rule the .bak tier follows: a snapshot of bytes that
        # do not parse is worthless on its own terms - restore refuses
        # to put one back - and recording it would spend the day's slot
        # on garbage while the good state ages out behind it.
        if not parses_as_json(current):
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
    """Keep the newest `days` entries for one file, by NAME not mtime.

    The name carries the date this copy is OF; mtime records when it was
    written, and a restore or a file copy rewrites that. Sorting by the
    stamp keeps the oldest real state rather than the oldest touch.
    """
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
    """Mint the write-once `.bak-first` from a file that has just been
    CREATED. Returns whether a floor was written.

    snapshot_before_write copies what is ALREADY on disk, and correctly
    declines when there is nothing there (a fresh install's first save
    must not burn the session's one snapshot on a file that does not
    exist yet). The consequence is a hole with no other cure: a store
    written exactly once has no `.bak` tier, no `.unreadable` copy and
    no marker - so if it then vanishes for an instant, `existed_before`
    has nothing to find and the absent-but-known guard cannot fire.

    Measured on the real library 2026-08-03: `notes.json` has all four
    tiers, and `icons.json` is absent with none at all - so the first
    tile icon ever picked would have been the one write with no floor
    and no evidence behind it.

    This writes no NEW kind of file. `<file>.json.bak-first` is already
    the documented "immutable first-seen copy" in the library's
    contents (overview.md); it simply arrives at the first write rather
    than the second. Write-once is preserved: an existing floor is
    never replaced here, and a floor is never minted from bytes that do
    not parse - the same two rules snapshot_before_write enforces, for
    the same reason (a permanent floor made of garbage is worse than no
    floor).
    """
    first = path + ".bak-first"
    if not path or os.path.exists(first):
        return False
    try:
        with open(path, "rb") as handle:
            current = handle.read()
    except OSError as exc:
        _record("backup", "no restore floor seeded - the new file could "
                "not be read back", path=path, error=str(exc))
        return False
    if not parses_as_json(current):
        _record("backup", "no restore floor seeded - what was just "
                "written does not parse", path=path, bytes=len(current))
        return False
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
    """Once per session per file: before the FIRST write to a critical
    database, copy the CURRENT on-disk version to a rolling .bak-N
    beside it (bak-1 newest). Sync services propagate corruption and
    deletion, so a local snapshot is the only cheap restore point - a
    corrupted settings.json once cost a full recovery session.
    Best-effort: a failed snapshot never blocks the write."""
    # BEFORE the once-per-session marker. The daily entry is keyed by
    # date, not by session, so it must get its chance on whichever save
    # is the first one today - not only on the first save of a session
    # that may have started yesterday.
    record_history(path)
    last = _session_snapshots.get(path)
    if last is not None and time.monotonic() - last < SNAPSHOT_INTERVAL:
        return
    if not os.path.exists(path):
        # Do NOT burn the once-per-session marker on a file that does
        # not exist yet: the first save of a fresh install CREATES
        # settings.json, and marking it here meant every later save that
        # session found the marker set and took no snapshot at all - so
        # the file spent its whole first session with no restore point.
        # Measured while reproducing the prefs-overwrite bug: a save,
        # then a corruption, then a save = no .bak-first anywhere.
        return
    _session_snapshots[path] = time.monotonic()
    try:
        # Closed explicitly: an unclosed handle here is not just a
        # warning. On Windows a held handle is precisely what makes the
        # following os.replace raise PermissionError - the case
        # replace_file already has to retry around.
        with open(path, "rb") as handle:
            current = handle.read()
    except OSError as exc:
        # DISCARD THE MARKER HERE TOO. This branch is the transient one -
        # the Windows sync-client hold that replace_file already has to
        # retry around, a share that dropped for a second, a permission
        # blip - and burning the session's one chance on a read that
        # failed for a reason that has already passed left the file with
        # no restore point for the whole session. The parse branch below
        # discards for exactly this reason; leaving this one set was the
        # same defect three lines earlier in the same function.
        _session_snapshots.pop(path, None)
        _record("backup", "no snapshot taken - the file could not be read",
                path=path, error=str(exc))
        return
    # PARSE BEFORE ROTATING. This copied whatever was on disk with no
    # check at all, and .bak-first is written once and never rotated - so
    # a single half-synced launch minted the one permanent restore point
    # from garbage, and the rolling .bak-N ring then aged the good states
    # out behind it. gradients.json and code.json currently have NO
    # .bak-* tier of any kind on the real library (measured 2026-07-29),
    # which means the very next snapshot for either of them is its
    # permanent floor: exactly one chance to get it right.
    #
    # A snapshot of unreadable bytes is also worthless on its own terms -
    # restore.py refuses to put a non-parsing snapshot back, correctly -
    # so this cannot cost a recovery that would otherwise have worked.
    # preserve_unreadable is the mechanism that keeps THAT file, and the
    # callers on this path already run it.
    if not parses_as_json(current):
        # DISCARD THE MARKER. Leaving it set would spend the whole
        # session's one chance on the read that failed, so a later
        # healthy save would find the file "already snapshotted" and take
        # no copy - the same once-per-session trap that left a fresh
        # install's settings.json with no restore point at all.
        _session_snapshots.pop(path, None)
        # event, not note: every caller on this path already tells the
        # user loudly that the file could not be read, and a second
        # printed line about backup internals is a wall of text about
        # something they cannot act on separately.
        _record("backup", "no snapshot taken - the file on disk does not "
                "parse", path=path, bytes=len(current))
        return
    try:
        # An immutable first-seen copy: the rolling set can age a good
        # state out (three panel opens is enough), so one copy is kept
        # forever and never rotated.
        first = path + ".bak-first"
        # Write-once - EXCEPT when what is there does not parse. The
        # permanent floor being garbage is worse than no floor: a single
        # half-synced launch used to mint it from a truncated file, and
        # the rolling ring then aged every good state out behind it,
        # leaving the one copy that never rotates as the one that never
        # worked. A healthy current file may replace a broken floor; a
        # PARSEABLE floor with different content is never touched - that
        # difference is the floor doing its job.
        if not os.path.exists(first):
            shutil.copy2(path, first)
        else:
            try:
                with open(first, "rb") as handle:
                    floor_bytes = handle.read()
            except OSError:
                floor_bytes = None
            if floor_bytes is not None and not parses_as_json(floor_bytes):
                shutil.copy2(path, first)
                _record("backup", "an unreadable .bak-first was replaced "
                        "by the current healthy file", path=first)
        # Rotate only when the content actually differs from the newest
        # backup - identical rewrites must not consume a slot.
        newest = path + ".bak-1"
        if os.path.exists(newest):
            try:
                # `with`, for the reason spelled out eight lines above:
                # a handle still open on Windows is what makes the
                # os.replace below raise PermissionError. The bare
                # open() here leaked one on every rotation - CPython
                # closed it whenever it felt like it, which is not a
                # guarantee and is not the same on every interpreter.
                with open(newest, "rb") as previous:
                    if previous.read() == current:
                        return
            except OSError:
                pass
        for i in range(keep, 1, -1):
            older = "%s.bak-%d" % (path, i - 1)
            if os.path.exists(older):
                os.replace(older, "%s.bak-%d" % (path, i))
        shutil.copy2(path, newest)
    except OSError:
        pass


def replace_file(src: str, dst: str) -> None:
    """os.replace with a brief retry: on Windows the destination being
    momentarily open (cloud-sync scanners on the library dir, a viewer
    holding a thumbnail) raises PermissionError where POSIX just
    swaps. Retries cover the transient hold; a persistent one still
    raises so the caller's error path runs."""
    for wait in (0.05, 0.15, 0.35):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            time.sleep(wait)
    os.replace(src, dst)


#: The permissions tempfile.mkstemp creates with - right for a scratch
#: file in a world-writable /tmp, wrong for the file it is about to
#: become. Named because promote_scratch has to recognise it on a
#: DESTINATION as well, see there.
_MKSTEMP_MODE = 0o600

#: Default permissions for a file this module CREATES, derived from the
#: process umask exactly as a plain open(path, "w") would be.
#:
#: Read once, at import, because os.umask is a get-and-set with no
#: read-only form: every call leaves a window in which another thread
#: creating a file sees mask 0, so the cheapest thing is to open that
#: window once instead of on every save. It is NOT true that no thread
#: exists yet - this module is imported through the panel's module graph
#: when the panel opens, long after Houdini has started its own thread
#: pool - so the window is real, microseconds wide, and its worst outcome
#: is one file created more permissively than the umask asked for. That is
#: the same direction as the bug below rather than the opposite one, which
#: is why it is acceptable and why it is written down instead of claimed
#: away. (An earlier version of this comment asserted the reverse.)
#:
#: This matters because every atomic write here goes through
#: tempfile.mkstemp. A library in a shared folder whose library.json and
#: .mat files silently turned owner-only would stop being readable by the
#: other person using it, and nothing in the app would say why.
def _default_file_mode() -> int:
    mask = os.umask(0)
    os.umask(mask)
    return 0o666 & ~mask


_DEFAULT_FILE_MODE = _default_file_mode()


def unique_scratch(path: str, suffix: str = ".writing",
                   create: bool = True) -> str:
    """A uniquely-named scratch path beside `path`, created empty.

    THE NAME MUST BE UNIQUE, and that is the whole reason this exists.
    Every fixed-name scratch in this package was one shared buffer: two
    writers of the same destination interleaved into it. Measured
    2026-07-29 for the JSON case, two processes x 600 saves: 790 reads
    unparseable and - far worse - 794 reads that PARSED while holding
    records from BOTH writers, leaving the destination larger than either
    document. Silent, parseable corruption with no hardware fault
    involved. A truncated file announces itself; that one does not.

    SAME DIRECTORY, ALWAYS. `dir=` is the destination's own folder
    because os.rename cannot cross drives on any OS (research.md, Windows
    audit) - a scratch in the system temp dir would turn every save into
    a cross-device failure.

    `create=False` returns the name with nothing at it, for the one kind
    of writer that cannot be handed an existing file: HOUDINI'S OWN. A
    pre-created file is strictly safer - the name is reserved, so not even
    a pathological collision can hand it out twice - and it is verified
    safe for the writers whose behaviour can be measured from a headless
    test (json.dump, and hou.Node.saveItemsToFile, probed 22.0.395:
    26,025 bytes onto a fresh path, a 0-byte file and a 100-byte file
    alike). assetutils.saveThumbnailFromViewer needs a live scene viewer
    and therefore cannot be probed that way, so it gets the name only -
    the unique name is the fix, and reserving the inode is the bonus this
    gives up where it cannot be proven safe.
    """
    directory = os.path.dirname(path) or "."
    handle, scratch = tempfile.mkstemp(
        dir=directory, prefix=os.path.basename(path) + ".", suffix=suffix)
    os.close(handle)
    if not create:
        discard_scratch(scratch)
    return scratch


def promote_scratch(scratch: str, path: str) -> None:
    """fsync `scratch`, give it the permissions the destination should
    have, and swap it into place.

    FSYNC BEFORE THE SWAP. Without it the rename can land while the bytes
    are still only in the page cache, so a power loss leaves an intact
    directory entry pointing at a partial file. There was no fsync
    anywhere in the package before this. Measured at +0.15ms on a 355KB
    save - against a ~2s panel open, it is free.

    Opened O_RDWR rather than O_RDONLY: on Windows fsync commits through a
    handle that must be writable, and this is called for files another
    process wrote (Houdini's own saveItemsToFile), so the descriptor
    cannot simply be kept from the write.
    """
    handle = os.open(scratch, os.O_RDWR)
    try:
        os.fsync(handle)
    finally:
        os.close(handle)
    # Match the file being replaced when there is one, so an existing
    # library's permissions survive a save; otherwise the umask default,
    # which is what a plain open() would have produced.
    #
    # EXCEPT 0600, WHICH IS THE BUG'S OWN FINGERPRINT. Copying the
    # destination's mode preserves a narrowing as faithfully as it
    # preserves a widening, and one narrowing is already on disk:
    # write_json_atomic went through mkstemp for a while with no chmod at
    # all, so every file it wrote in that window became owner-only and
    # would then stay owner-only for every future save, forever. Measured
    # on the real library, 2026-07-30: library.json 0600 (written by that
    # code), code.json 0600, against cops.json 0644 and gradients.json
    # 0666 written before it. On a shared library the second person can
    # open neither, and nothing in the app says why. "Preserve what is
    # there" would have made the repair impossible.
    #
    # 0600 exactly, and only 0600, because that is what mkstemp creates
    # with - so this recognises the state our own bug leaves and nothing
    # else. The residual is accepted knowingly: a user who deliberately
    # chmod 600'd a library file gets it widened back to their umask
    # default on the next save, and there is nothing in the mode alone to
    # tell the two apart. The direction decides it. Wrongly widening makes
    # a file in a folder the user CHOSE as a shared asset library readable
    # by their own group; wrongly narrowing locks a colleague out of the
    # library permanently and silently. On a machine whose umask is 077
    # the default IS 0600 and this whole branch is a no-op.
    mode = _DEFAULT_FILE_MODE
    try:
        existing = os.stat(path).st_mode & 0o7777
    except OSError:
        existing = -1
    if existing >= 0 and existing != _MKSTEMP_MODE:
        mode = existing
    try:
        os.chmod(scratch, mode)
    except OSError:
        # Best-effort: a filesystem with no permission bits (some network
        # mounts) must not fail the save over cosmetics.
        pass
    replace_file(scratch, path)


def discard_scratch(scratch: str) -> None:
    """Remove a scratch file if it is still there. Never raises.

    A scratch left behind is not merely untidy: an unowned file in the
    library directory is exactly the kind of thing a directory scan has
    to learn to ignore, and "the directory cannot tell you who owns a
    file" is how 8 live assets were once reported as orphans.
    """
    try:
        if scratch and os.path.exists(scratch):
            os.remove(scratch)
    except OSError:
        pass


@contextlib.contextmanager
def scratch_beside(path: str, suffix: str = ".writing"):
    """Write to a unique scratch beside `path`, then swap it in.

    The single-destination shape of unique_scratch/promote_scratch:

        with hostos.scratch_beside(path) as scratch:
            ... write scratch ...

    On the way out the scratch is fsynced and renamed over `path`; on any
    exception it is removed and the exception propagates, so a raising
    writer cannot litter the library. Callers that must promote SEVERAL
    files as one unit (an asset's .mat and .interface are one thing in two
    files) use the primitives directly instead - there is no portable way
    to make two renames atomic, but two renames of fully-written files
    microseconds apart is a different risk from a truncation followed by
    work that can fail.
    """
    scratch = unique_scratch(path, suffix)
    try:
        yield scratch
        promote_scratch(scratch, path)
    finally:
        # Never leave the scratch behind - not on OSError, not on a
        # serialisation failure, not on KeyboardInterrupt. A successful
        # promote has already renamed it away, so this is a no-op then.
        discard_scratch(scratch)


#: The environment variable that arms the sandbox, below.
SANDBOX_VAR = "AMAZE_SANDBOX"


class SandboxRefused(RuntimeError):
    """A write that would have left the sandbox.

    Loud on purpose, and an exception rather than a refusal code: this
    guards development scripts, where a write that quietly does nothing
    is a probe reporting results it never produced. Nothing in the
    product ever sets the variable, so nothing in the product can raise
    this.
    """


def sandboxed() -> bool:
    return os.environ.get(SANDBOX_VAR, "") in ("1", "true", "yes")


def check_sandbox(path: str) -> None:
    """Refuse a write that would land outside a temporary directory,
    when the sandbox is armed.

    **Why it exists (2026-08-05).** A probe script pointed a `Prefs` at
    a scratch library - after calling `load()`, which is where the
    location migration runs. So the migration had already written two
    files into the real, synced library before the redirect took. No
    guard saw it: the destructive-command hook reads SHELL commands for
    delete verbs, and this was a Python write.

    The rule that follows is not "be careful". It is that any script run
    by hand against a live machine arms this variable, and then the one
    function every JSON write in the package goes through - prefs, all
    four databases, the keyed stores, the manifests - can refuse on its
    own behalf. One place, because a per-caller check is a list someone
    can write short.
    """
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


def write_json_atomic(path: str, data, indent: int = 4,
                      sort_keys: bool = False) -> None:
    """Serialise `data` to `path` so no reader can ever see it half-written.

    The JSON front door onto scratch_beside, which carries the unique
    name, the same-directory rule, the fsync and the cleanup - all of it
    in one place so the package's writers cannot drift apart again. Four
    of them had grown their own fixed-name version of this.
    """
    check_sandbox(path)
    with scratch_beside(path) as scratch:
        # newline="\n", or Windows text mode turns every \n into \r\n on
        # the way out. Nothing READS these files line by line, so the
        # cost was invisible - but database.save() skips a write that
        # changes nothing by comparing `json.dumps(...)` (LF) against the
        # file read in BINARY, and CRLF on disk can never match it. So on
        # Windows the no-op guard never fired: every save wrote, and each
        # write costs a snapshot rotation and a sync upload, which is the
        # exact cost the guard exists to avoid. Worse across the two
        # machines - the Mac writes LF, Windows wrote CRLF, so each one's
        # guard also mismatched after the other had saved, in the library
        # they share. Measured 2026-08-06 by test_db_hardening's
        # identical-skip, which returned "stored" on Windows.
        with open(scratch, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, indent=indent, sort_keys=sort_keys)


def disk_state(path: str):
    """`(mtime_ns, size)` for `path`, or None if it is not there.

    The fingerprint a store keeps so it can tell whether ANOTHER
    session wrote the file since this one read it - the question every
    adopt-from-disk path asks before it overwrites. Two stores had
    grown their own identical five lines of it
    (`keyed_store.Store`, `texture_library.ThumbnailCache`), which is
    the same drift `write_json_atomic` above was written to end.

    Deliberately a tuple, not an mtime alone: a write that lands
    inside the same nanosecond tick still changes the size, and a
    write that keeps the size still moves the mtime.
    """
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def canonical_path_key(path: str) -> str:
    """A filesystem path as a stable dictionary/prefs key: normalized,
    forward slashes on every OS. os.path.join output is os.sep-flavored
    (backslashes on Windows) while stored keys travel through JSON as
    forward slashes - comparing the two raw broke subfolder favorites
    there. Existing keys written on macOS/Linux are already in this
    form."""
    return os.path.normpath(path).replace(os.sep, "/")


def _home_root() -> str:
    """Home in canonical spelling. Its own function so a test can pin
    it - patching expanduser would patch the world."""
    return canonical_path_key(os.path.expanduser("~"))


def storage_path_key(path: str) -> str:
    """A path as the LIBRARY stores spell it: `$AMAZE/...` under the
    install tree, `~/...` under home, the canonical absolute when
    neither covers it - one entry that resolves on every machine
    sharing the library (the 2026-08-06 unification: relative
    spellings, home by default; research.md > Windows for the
    three-spellings-of-one-file measurement that earned it).

    $AMAZE is tried FIRST: the install lives under home on every
    current machine, so home-first would mean the $AMAZE spelling can
    never fire. Empty stays empty - `normpath("")` is `"."`
    (research.md), and a truthy `"."` key slips every `if not key`
    guard downstream.

    `~` here is PYTHON's home, expanded by `expand_storage_path` and
    nothing else. It is NOT Houdini's `$HOME`, which on a stock
    Windows machine defaults to Documents (INSTALL.md) - the display
    spelling `houdini_path()` writes serves that world; this one never
    passes through Houdini. Measured 2026-08-06: a package's `env`
    entries land in `os.environ`, so $AMAZE resolves here without hou.
    """
    if not path:
        return ""
    # A location's identity CARRIES its trailing separator (`/tex/a/`
    # is the registered spelling everywhere the store is compared), and
    # normpath strips it - so it is remembered here and put back on
    # whatever spelling wins.
    trailing = "/" if str(path).endswith(("/", "\\")) else ""
    path = canonical_path_key(path)
    amaze = os.environ.get("AMAZE", "")
    for var, root in (("$AMAZE", canonical_path_key(amaze) if amaze else ""),
                      ("~", _home_root())):
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
    """The inverse: a stored spelling back to THIS machine's canonical
    absolute. A `$AMAZE` spelling with no $AMAZE in the environment
    comes back untouched - unresolvable is a fact the caller can see,
    not one to guess around."""
    if not path:
        return ""
    trailing = "/" if path.endswith("/") else ""
    if path == "$AMAZE" or path.startswith("$AMAZE/"):
        root = os.environ.get("AMAZE", "")
        if not root:
            return path
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
    """The entry of `extensions` that `name` ends with, or "".

    LONGEST WINS, so "x.bgeo.sc" reports ".bgeo.sc" rather than
    ".bgeo" - the caller uses the answer as a label and as a cache
    key, and the short one is wrong for both. Callers used to get this
    by ordering their tuple longest-first, which is a property of the
    data that nothing checked; sorting here makes the tuple's order
    stop mattering.

    Matching is case-insensitive because the filesystems this runs on
    are (".PNG" is the same file as ".png" on macOS and Windows), which
    is why this lives with the other path semantics rather than beside
    any one section's extension list. There were three of these: two
    identical copies in geo_library and scene_captures, and a third shape
    in file_library that used `str.endswith(tuple)` and therefore could
    not say WHICH extension matched - the reason its FormatRole needed
    a separate branch for images.
    """
    lowered = name.lower()
    best = ""
    for ext in extensions:
        ext = ext.lower()
        if lowered.endswith(ext) and len(ext) > len(best):
            best = ext
    return best


class PathEscape(ValueError):
    """A composed path landed outside the directory it had to stay in."""


def contained_join(base: str, *parts: str) -> str:
    """`os.path.join(base, *parts)`, refusing anything that escapes base.

    Asset filenames are composed from an id that comes verbatim out of
    `library.json` - a file the app does not author alone and cannot
    assume is honest. With the id `../../.ssh/authorized_keys`, the
    ordinary composition resolves outside the library entirely, which
    lets a tampered index choose which file the loader opens.

    Containment is checked on the REAL paths (symlinks resolved), so a
    link planted inside the asset directory cannot be used as the hop
    out. Base itself is not required to exist - the check is about where
    the result points, and a library directory can legitimately be
    missing when this is asked.
    """
    composed = os.path.join(base, *parts)
    real_base = os.path.realpath(base)
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
    """A string made safe as a file/directory name on every OS: strips
    the characters Windows forbids (angle brackets, colon, quote,
    slashes, pipe, question mark, asterisk, controls), trailing
    dots/spaces (silently dropped by Windows, changing the name), and
    sidesteps the reserved device names (CON, NUL, COM1...). Content
    names (online material titles) must pass through here before
    becoming paths."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name))
    cleaned = cleaned.rstrip(". ")
    if not cleaned:
        return fallback
    if _WIN_RESERVED_NAMES.match(cleaned.split(".")[0]):
        cleaned = "_" + cleaned
    return cleaned


def bundled_binary(hfs: str, name: str) -> str | None:
    """Absolute path of a binary in Houdini's own bin folder, or None.
    Windows ships them with an .exe suffix."""
    path = os.path.join(hfs or "", "bin", name)
    if os.path.exists(path):
        return path
    exe = path + ".exe"
    if os.path.exists(exe):
        return exe
    return None
