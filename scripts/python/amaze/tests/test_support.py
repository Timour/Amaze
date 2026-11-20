"""Test plumbing keeping tests off the real library, settings, caches and log. ▸p/harness-isolation"""

import atexit
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import types

from amaze.helpers import hostos

os.environ[hostos.SANDBOX_VAR] = "1"    # set at IMPORT, however the test was started ▸p/hand-run-script-is-unguarded


def call_as_amaze(fn):
    """Call `fn` from a frame whose `__name__` is an Amaze module, as during an import."""
    def inside():
        return _fn()    # noqa: F821 - bound by the globals handed to FunctionType below

    return types.FunctionType(inside.__code__, {"__name__": "amaze.render.nodes", "_fn": fn})()


def settle(done, timeout=3.0) -> None:
    """Pump the event loop from a test frame, which counts as idle, until `done()` or `timeout`."""
    from PySide6 import QtWidgets
    deadline = time.monotonic() + timeout
    while not done() and time.monotonic() < deadline:
        QtWidgets.QApplication.processEvents()
        time.sleep(0.01)


def pump_until(done, timeout=10.0) -> bool:
    """Run the event loop until `done()` is true or the time is up; return `done()`."""
    from PySide6 import QtWidgets
    deadline = time.monotonic() + timeout
    while not done() and time.monotonic() < deadline:
        QtWidgets.QApplication.processEvents()
        time.sleep(0.002)
    return bool(done())


def scratch_dir(prefix: str) -> str:
    """Make a directory in the system temp folder, where all test dirs go. ▸p/suite-scratch-folders"""
    return tempfile.mkdtemp(prefix=prefix)


def isolate_user_folders() -> str:
    """Point the sandbox's settings, cache and log folders into this run's temp dir."""
    directory = scratch_dir("amaze_test_home_")
    atexit.register(shutil.rmtree, directory, True)
    os.environ[hostos.SANDBOX_HOME_VAR] = directory
    if not os.path.realpath(hostos.config_root()).startswith(
            os.path.realpath(directory)):
        raise RuntimeError(
            "test settings isolation failed - config_root() is %s, not "
            "under %s" % (hostos.config_root(), directory))
    return directory


TEST_HOME = isolate_user_folders()    # before anything asks for a per-user folder

from amaze.core import debug                            # noqa: E402
from amaze.prefs import prefs                           # noqa: E402


FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "assets", "library")

FIXTURE_USER = "0f1e2d3c4b5a69788796a5b4c3d2e1f0"    # the fixture library's owner: a constant in the format of a generated UID


def isolate_debug_log() -> str:
    """Send the debug log to a throwaway file, never the real log dir. ▸p/harness-isolation"""
    directory = os.environ.get("AMAZE_LOG_DIR", "").strip()
    if not directory:
        directory = scratch_dir("amaze_test_log_")
        atexit.register(shutil.rmtree, directory, True)
        os.environ["AMAZE_LOG_DIR"] = directory
    path = os.path.join(directory, "test_debug.jsonl")
    debug.redirect(path)
    real = os.path.realpath(hostos.real_log_root())
    if os.path.realpath(os.path.dirname(path)).startswith(real):
        raise RuntimeError(
            "test log isolation failed - %s is inside the real log dir %s"
            % (path, real)
        )
    return path


TEST_LOG = isolate_debug_log()    # redirected at IMPORT, deliberately not left to each test to remember


def isolate_cache_root() -> str:
    """Send the thumbnail cache to a throwaway dir via the environment. ▸p/harness-isolation"""
    directory = os.environ.get(hostos.CACHE_DIR_ENV, "").strip()
    if not directory:
        directory = scratch_dir("amaze_test_cache_")
        atexit.register(shutil.rmtree, directory, True)
        os.environ[hostos.CACHE_DIR_ENV] = directory
    hostos.set_cache_override(directory)
    resolved = os.path.realpath(hostos.cache_root())
    if not resolved.startswith(os.path.realpath(directory)):
        raise RuntimeError(
            "test cache isolation failed - cache_root() is %s, not %s"
            % (resolved, directory)
        )
    return directory


TEST_CACHE = isolate_cache_root()    # redirected at IMPORT for the same reason as the log


def reset_database_singletons() -> None:
    """Release every model and library database this session holds, after saving pending writes."""
    from amaze.core import library_db, model_registry
    library_db.flush()
    library_db.drop_scheduler()    # a panel left from the last test must not hold this one's saves
    model_registry.release()    # a kept model would carry the last test's rows into this one


def settle_stamps() -> None:
    """Save every pending change now, each asset's metadata included."""
    from amaze.core import library_db
    library_db.flush()


def flush_pending_saves() -> None:
    """Flush pending saves, so nothing writes into a test's library after the test ends."""
    from amaze.core import library_db
    library_db.flush()


FILES_FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "assets", "files")    # one tiny synthetic file per kind, built by make_file_fixtures.py


def posix_relpath(path: str, start: str) -> str:
    """A relative path with forward slashes on every OS. ▸p/harness-isolation"""
    return os.path.relpath(path, start).replace(os.sep, "/")


def posix_path(path: str) -> str:
    """An absolute path as the databases store it, via `storage_path_key`. ▸p/harness-isolation"""
    return hostos.expand_storage_path(hostos.storage_path_key(path))


def fresh_files_folder(testcase) -> str:
    """A throwaway copy of the File-section fixture, for a fixture panel. ▸p/harness-isolation"""
    tmp = scratch_dir("amaze_test_files_")
    testcase.addCleanup(shutil.rmtree, tmp, True)
    dest = os.path.join(tmp, "files")
    shutil.copytree(FILES_FIXTURE_DIR, dest)
    return posix_path(dest) + "/"


def pin_scene_folder(testcase) -> str:
    """Set `$HIP` to a new folder of two files for the test; its old value is restored after."""
    import hou
    scene = scratch_dir("amaze_test_scene_")
    testcase.addCleanup(shutil.rmtree, scene, True)
    for name in ("shot.hip", "notes.txt"):
        open(os.path.join(scene, name), "w").close()
    testcase.addCleanup(hou.putenv, "HIP", hou.getenv("HIP"))    # always set: `pin_env` would skip it
    hou.putenv("HIP", scene)
    from amaze.actions import files as files_actions
    real = getattr(files_actions.scene_saved, "real", files_actions.scene_saved)

    def saved() -> bool:    # the test scene counts as saved; `.real` is the original check
        return True
    saved.real = real
    files_actions.scene_saved = saved
    testcase.addCleanup(setattr, files_actions, "scene_saved", real)
    return posix_path(scene) + "/"


def fresh_library(testcase, source=None) -> str:
    """A throwaway copy of the fixture library, as a `prefs.dir` path. ▸p/harness-isolation"""
    tmp = scratch_dir("amaze_test_lib_")
    testcase.addCleanup(shutil.rmtree, tmp, True)
    testcase.addCleanup(flush_pending_saves)    # runs first: no check writes into a copy being removed
    dest = os.path.join(tmp, "library")
    shutil.copytree(source or FIXTURE_DIR, dest)
    return posix_path(dest) + "/"


_SEEDED = []    # the first seeded panel library, which later fixture panels copy
_PER_PANEL = ("files.json",)    # each panel writes its own locations


def _keep_seeded(library: str) -> None:
    """The first seeded panel library, minus its Files database: what later panels copy."""
    import json
    from amaze.core import gradient_library, library_db
    library_db.flush()
    try:
        with open(os.path.join(library, "DataBase.json"), encoding="utf-8") as handle:
            marks = json.load(handle).get("marks") or {}
    except (OSError, ValueError):
        marks = {}
    if _SEEDED or gradient_library.GradientLibrary._SEED_MARK not in marks:
        return
    keep = os.path.join(scratch_dir("amaze_seeded_fixture_"), "library")
    atexit.register(shutil.rmtree, os.path.dirname(keep), True)
    shutil.copytree(library, keep)
    for name in _PER_PANEL:    # emptied, not deleted: the manifest lists it, so a missing file reads as lost
        if os.path.exists(os.path.join(keep, name)):
            with open(os.path.join(keep, name), "w", encoding="utf-8") as handle:
                handle.write("{}\n")
    _SEEDED.append(keep)


def seeded_library(testcase) -> str:
    """`fresh_library`, already seeded, so switching to it skips adding the curated palettes."""
    return fresh_library(testcase, _SEEDED[0] if _SEEDED else None)


class _RecordedLog:
    """The records a `captured_log()` block wrote, read per record. ▸p/harness-isolation"""

    def __init__(self, path: str) -> None:
        self.path = path
        self._drained = None

    def _drain(self) -> None:
        out = []
        try:
            with open(self.path, encoding="utf-8") as handle:
                lines = handle.readlines()
        except OSError:
            lines = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        self._drained = out

    def records(self, category: str = "note") -> list:
        if self._drained is None:
            self._drain()
        return [r for r in self._drained
                if category is None or r.get("cat") == category]

    def messages(self, category: str = "note") -> list:
        return [str(r.get("msg", "")) for r in self.records(category)]

    def matching(self, needle: str, category: str = "note") -> list:
        """The messages that themselves contain `needle`, lowercased."""
        return [m for m in self.messages(category)
                if needle.lower() in m.lower()]


def asset_ids(model) -> set:
    """Every asset id `model` holds now - taken before an action that adds rows."""
    return {str(asset.mat_id) for asset in model.assets}


def arrived(model, before) -> list:
    """The assets added since `before`, in row order, as sorted. ▸p/grid-engine"""
    return [asset for asset in model.assets if str(asset.mat_id) not in before]


def refused_at_open(path, error=None):
    """Patch `open` to fail for `path` only, by default as for a file another account owns."""
    import errno
    from unittest import mock
    error = error or PermissionError(errno.EACCES, "Permission denied", path)
    real_open = open
    wanted = os.path.realpath(path)

    def failing_open(name, *args, **kwargs):
        if isinstance(name, (str, os.PathLike)) and os.path.realpath(name) == wanted:
            raise error
        return real_open(name, *args, **kwargs)

    return mock.patch("builtins.open", failing_open)


@contextlib.contextmanager
def full_disk_for(path):
    """Make every write of `path`, or of its scratch file beside it, fail with a full-disk error."""
    import errno
    from unittest import mock
    from amaze.core import guard
    real_write, real_disk_write = hostos.write_json_atomic, guard.Disk.write
    wanted = os.path.realpath(path)

    def _is_target(name) -> bool:
        name = os.path.realpath(name)
        return name == wanted or (os.path.dirname(name) == os.path.dirname(wanted)
                                  and os.path.basename(name).startswith(
                                      os.path.basename(wanted) + ".")
                                  and name.endswith(guard.SCRATCH))

    def failing_write(name, *args, **kwargs):
        if _is_target(name):
            raise OSError(errno.ENOSPC, "No space left on device", name)
        return real_write(name, *args, **kwargs)

    def failing_disk_write(disk, name, data):
        if _is_target(name):
            raise OSError(errno.ENOSPC, "No space left on device", name)
        return real_disk_write(disk, name, data)

    with mock.patch.object(hostos, "write_json_atomic", failing_write), \
            mock.patch.object(guard.Disk, "write", failing_disk_write):
        yield


@contextlib.contextmanager
def captured_log():
    """Capture what `debug` records in the block; state restored on exit. ▸p/harness-isolation"""
    directory = scratch_dir("amaze_test_capture_")
    path = os.path.join(directory, "captured.jsonl")
    recorded = _RecordedLog(path)
    was_on = debug.is_on()
    debug.redirect(path)
    debug.configure(True)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            yield recorded
    finally:
        debug.configure(was_on)
        debug.redirect(TEST_LOG)
        recorded._drain()    # BEFORE the file is deleted, or every later assertion finds no records
        shutil.rmtree(directory, True)


@contextlib.contextmanager
def row_moves_inside_a_layout_change(*models):
    """Every row insert, removal or reset emitted while that model's layout change was open."""
    caught = []
    wired = []

    def recorder(model, name, depth):
        def record(*_args):
            if depth[0]:
                caught.append("%s.%s" % (type(model).__name__, name))
        return record

    for model in models:
        depth = [0]    # open layout changes; the H21 segfault comes from a row move at depth > 0

        def opened(*_args, depth=depth):
            depth[0] += 1

        def closed(*_args, depth=depth):
            depth[0] = max(0, depth[0] - 1)

        slots = [(model.layoutAboutToBeChanged, opened),
                 (model.layoutChanged, closed)]
        for name in ("rowsInserted", "rowsRemoved", "modelReset"):
            slots.append((getattr(model, name),
                          recorder(model, name, depth)))
        for signal, slot in slots:
            signal.connect(slot)
            wired.append((signal, slot))
    try:
        yield caught
    finally:
        for signal, slot in wired:
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass             # the model was already deleted


def plugins_loaded(*renderers):
    """Each material conversion API reports loaded only for `renderers`, MaterialX always."""
    from unittest import mock
    from amaze.render.material_conversion import engine
    stack = contextlib.ExitStack()
    for each in engine.apis().values():
        if each.name != engine.INTERMEDIATE:
            stack.enter_context(mock.patch.object(
                each, "available", lambda name=each.name: name in renderers))
    return stack


def renderer_loaded(key: str) -> bool:
    """Whether `key`'s plugin is loaded, via `engine.api`: the check `plugins_loaded` patches."""
    from amaze.render.material_conversion import engine
    return engine.api(key).available()


def pin_env(scope, name: str, value: str) -> None:
    """Set `$name` to `value` for `scope` if Amaze reads it as unset; its old state is restored."""
    import hou
    previous = hou.getenv(name)
    if previous:    # Amaze's check is `not hou.getenv(name)`, so an empty `OCIO =` is unset
        return
    if previous is None:
        scope.addCleanup(hou.unsetenv, name)
    else:
        scope.addCleanup(hou.putenv, name, previous)
    hou.putenv(name, value)


def clear_obj() -> None:
    """Delete every node at object level, whatever a test built there."""
    import hou
    for child in hou.node("/obj").children():
        try:
            child.destroy()
        except hou.OperationFailed:
            pass


def drop_node(node) -> None:
    """Destroy `node` off the undo stack; one the test already destroyed is fine."""
    import hou
    with hou.undos.disabler():
        try:
            node.destroy()
        except hou.ObjectWasDeleted:
            pass


def write_text(path: str, text: str) -> None:
    """`text` into `path` as UTF-8, its folder made first."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def source_of(relative: str) -> str:
    """The text of a package file, named relative to the package: `core/notes.py`."""
    package = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(package, relative), encoding="utf-8") as handle:
        return handle.read()


def refuse_listing(testcase, folder: str) -> None:
    """Make `folder` refuse to be listed until the test ends; skips as root, who lists it anyway."""
    if hostos.is_windows():    # its mode bits stop no listing there; a deny rule for Everyone does
        everyone = "*S-1-1-0"
        subprocess.run(["icacls", folder, "/deny", everyone + ":(RD)"],
                       check=True, capture_output=True)
        testcase.addCleanup(subprocess.run, ["icacls", folder, "/remove:d", everyone],
                            capture_output=True)
        return
    if hasattr(os, "getuid") and os.getuid() == 0:
        testcase.skipTest("root lists every folder")
    os.chmod(folder, 0)
    testcase.addCleanup(os.chmod, folder, 0o755)


def bash() -> str:
    """The `bash` first on PATH; Windows by itself starts System32's, which is WSL's."""
    return shutil.which("bash") or "bash"


def plain_python() -> str:
    """The plain Python under this hython, which starts in under a second; hython takes 20 s."""
    for name in (os.path.join("bin", "python3"), "python.exe"):
        path = os.path.join(sys.base_prefix, name)
        if os.path.isfile(path):
            return path
    return sys.executable


def live_library_to_rehearse_on(testcase):
    """The configured library, or a skip. ▸p/harness-isolation"""
    live = prefs.Prefs()
    live.path = hostos.real_config_root()    # the user's own settings, read only - the sandbox blocks writes
    live.load()
    directory = live.dir
    if not directory or not os.path.isdir(directory):
        testcase.skipTest("no library configured on this machine")
    from amaze.core import guard, library_conversion
    if library_conversion.needs_conversion(directory):
        return live    # an older library: the rehearsal converts a copy of it
    reading = guard.Guard(directory).read("materials.json")
    if reading.verdict != guard.FINE or not (reading.document or {}).get("assets"):
        testcase.skipTest("the configured library is empty or could not be read")
    return live


def fixture_prefs(testcase):
    """Preferences with .dir and .path on a fresh fixture copy, user set. ▸p/harness-isolation"""
    p = prefs.Prefs()
    p.dir = fresh_library(testcase)
    p.path = scratch_dir("amaze_fixture_prefs_")
    testcase.addCleanup(shutil.rmtree, p.path, True)
    p.library_user = FIXTURE_USER
    return p


def class_scope(testcase_class):
    """A per-class stand-in for `self`, routing `addCleanup` to `addClassCleanup`."""
    class _Scope:
        @staticmethod
        def addCleanup(function, *args, **kwargs):
            testcase_class.addClassCleanup(function, *args, **kwargs)
    return _Scope


ALL_SECTION_KEYS = ("material", "gradient", "cop", "code", "file")    # every section key, so a fixture panel can drive any tab regardless of the machine's own settings


FIXTURE_USER_NAME = "Fixture"    # the fixture user's name, in a library a panel opens


def with_fixture_user(library) -> str:
    """Add the fixture user to `library`, which a panel opens only with one of its users."""
    import types
    from amaze.core import library_db, users
    holder = types.SimpleNamespace(dir=library, library_user=FIXTURE_USER)
    held = library_db.document(holder, "DataBase.json")
    held.put(users.SECTION, FIXTURE_USER, {"name": FIXTURE_USER_NAME})
    library_db.flush(holder)
    library_db.release(holder)
    return library


def repair_from_preferences(testcase, panel):
    """Preferences on `panel`, its Databases button pressed twice: Check, then Repair."""
    from amaze.dialogs import prefs_dialog
    dialog = prefs_dialog.PrefsDialog(panel.prefs, panel=panel)
    testcase.addCleanup(dialog.deleteLater)
    dialog.check_or_repair()
    dialog.check_or_repair()
    return dialog


def backup_now(library, name: str) -> str:
    """Copy database `name` to a backup Check Library lists; returns the backup's path."""
    import datetime
    from amaze.core import guard
    folder = os.path.join(str(library), guard.BACKUP_DIR)
    os.makedirs(folder, exist_ok=True)
    stamp = (datetime.datetime.now() - datetime.timedelta(hours=1)).strftime(guard.STAMP)
    target = os.path.join(folder, "%s.%s%s" % (name, stamp, guard.BACKUP_TAIL))
    shutil.copyfile(os.path.join(str(library), name), target)
    return target


def serves(name: str, library) -> bool:
    """Whether a shared model for database `name` reads `library`."""
    from amaze.core import model_registry
    wanted = os.path.realpath(str(library).rstrip("/\\"))
    return any(os.path.realpath(str(model.preferences.dir).rstrip("/\\")) == wanted
               for models in model_registry._models.values() for model in models.values()
               if getattr(model, "DB_FILENAME", None) == name)


def set_library_version(library, version: int) -> None:
    """The library's recorded version set to `version`, as a newer or older Amaze would leave it."""
    from amaze.core import guard
    held = guard.Guard(str(library))
    reading = held.read("DataBase.json")
    document = dict(reading.document or {})
    policy = dict(document.get("policy") or {})
    policy["library"] = {"version": int(version)}
    change = held.change("")
    change.replace("DataBase.json", dict(document, policy=policy))
    change.commit()


def with_fixture_location(library, folder) -> None:
    """`folder` registered as the fixture user's one File location in `library`."""
    import types
    from amaze.core import library_db, locations
    holder = types.SimpleNamespace(dir=library, library_user=FIXTURE_USER,
                                   last_known_folders=[folder],
                                   keep_last_known=lambda *_args: None)
    locations.forget()
    if not locations.set_record(holder, folder, {"registered": True}):
        raise RuntimeError("the fixture location could not be registered in %s" % library)
    library_db.flush(holder)
    library_db.release(holder)
    locations.forget()


def fixture_panel(testcase, render_geometry=False):
    """A real AmazePanel over a private fixture library, isolation asserted. ▸p/harness-isolation"""
    from amaze.panel import panel as panel_mod       # reloads hostos
    from amaze.helpers import hostos as hostos_mod
    from amaze.core import library_db as library_db_mod, matx_library, matx_sources
    from amaze.actions import files as files_actions

    if not render_geometry:    # the fixture's three geometry files cost ~1.2 s a render, every panel, every folder shown
        real_render = files_actions.render_geo_misses
        files_actions.render_geo_misses = lambda model, misses: None
        testcase.addCleanup(setattr, files_actions, "render_geo_misses", real_render)

    def _no_network(url, *args, **kwargs):
        raise OSError(
            "the test suite blocks the network - a fixture panel reached "
            "out to %s" % url
        )

    real_request = matx_sources._request
    matx_sources._request = _no_network
    testcase.addCleanup(setattr, matx_sources, "_request", real_request)

    real_save = prefs.Prefs.save
    prefs.Prefs.save = lambda self, *a, **k: None
    testcase.addCleanup(setattr, prefs.Prefs, "save", real_save)

    config = scratch_dir("amaze_fixture_panel_")
    testcase.addCleanup(shutil.rmtree, config, True)
    library = with_fixture_user(fresh_library(testcase, _SEEDED[0] if _SEEDED else None))
    files = fresh_files_folder(testcase)
    with_fixture_location(library, files)
    scene = pin_scene_folder(testcase)    # before the panel: its cleanup then runs after the panel's
    with open(os.path.join(config, "settings.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"directory": library,
                   "library_user": FIXTURE_USER,    # in the settings file: the panel builds and loads its own Prefs
                   "users": {FIXTURE_USER: {
                       "enabled_sections": list(ALL_SECTION_KEYS),
                       "file_folders": [files],
                       "file_location_records": {files: {"registered": True}},
                       "last_file_folder": files}}}, handle)

    real_config_root = hostos_mod.config_root
    hostos_mod.config_root = lambda: config
    testcase.addCleanup(setattr, hostos_mod, "config_root", real_config_root)

    reset_database_singletons()
    panel = panel_mod.AmazePanel()
    library_db_mod.drop_scheduler()    # a test reads what it changed at once, never after a timer
    testcase.addCleanup(dispose_panel, panel)
    testcase.addCleanup(stop_panel_workers, panel)    # after deleteLater, so it runs first: hython never emits aboutToQuit

    checked = [("settings", panel.prefs.path),
               ("library", panel.prefs.dir),
               ("catalogue cache", matx_library.catalogue_cache()),
               ("preview cache", matx_library.preview_cache()),
               ("scene folder", scene)]
    for folder in panel.prefs.file_folders or ():    # NAMED field, not a defaulting getattr - a default would narrow this check silently
        checked.append(("file_folders", str(folder)))
    for label, path in checked:
        if not os.path.realpath(path).startswith(
                os.path.realpath(tempfile.gettempdir())):
            raise RuntimeError(
                "fixture panel isolation failed - %s is %s, outside the "
                "temp directory" % (label, path)
            )
    if panel.material_model is None:
        raise RuntimeError(
            "the fixture panel did not load its library, so setup() never "
            "ran - this fixture is not building the panel tests need"
        )
    _keep_seeded(panel.prefs.dir)
    return panel


def reopened_panel(testcase):
    """A second panel on the same settings, only after `fixture_panel`. ▸p/harness-isolation"""
    from amaze.helpers import hostos as hostos_mod
    from amaze.panel import panel as panel_mod

    probe = hostos_mod.config_root()
    if not os.path.realpath(probe).startswith(
            os.path.realpath(tempfile.gettempdir())):
        raise RuntimeError(
            "reopened_panel without fixture_panel's redirection - "
            "config_root is %s, outside the temp directory" % probe)
    panel = panel_mod.AmazePanel()
    from amaze.core import library_db
    library_db.drop_scheduler()    # a test reads what it changed at once
    testcase.addCleanup(dispose_panel, panel)
    testcase.addCleanup(stop_panel_workers, panel)
    return panel


def apply_library(testcase, panel, folder, user: str = "", dialog=None) -> bool:
    """Switch `panel` to `folder` as Preferences does: pick it and a user, then Apply, saves real."""
    from unittest import mock
    from amaze.dialogs import prefs_dialog
    from amaze.prefs import persistence
    if dialog is None:
        dialog = prefs_dialog.PrefsDialog(panel.prefs, panel=panel)
        testcase.addCleanup(dialog.deleteLater)
    dialog.pick_library(folder)
    combo = dialog.cbb_library_user
    if user and combo.findText(user) >= 0:
        combo.setCurrentIndex(combo.findText(user))
    elif user or combo.currentIndex() < 0:
        dialog.create_library_user(user or "Tester")
    with mock.patch.object(prefs.Prefs, "save", persistence._Persistence.save):    # a switch re-reads it
        return dialog.apply_library()


def fixture_unconfigured_panel(testcase):
    """A real AmazePanel with no library, the legacy path blanked too. ▸p/harness-isolation"""
    from amaze.panel import panel as panel_mod       # reloads hostos
    from amaze.helpers import hostos as hostos_mod
    from amaze.core import matx_sources

    def _no_network(url, *args, **kwargs):
        raise OSError(
            "the test suite blocks the network - an unconfigured "
            "fixture panel reached out to %s" % url
        )

    real_request = matx_sources._request
    matx_sources._request = _no_network
    testcase.addCleanup(setattr, matx_sources, "_request", real_request)

    real_save = prefs.Prefs.save
    prefs.Prefs.save = lambda self, *a, **k: None
    testcase.addCleanup(setattr, prefs.Prefs, "save", real_save)

    config = scratch_dir("amaze_fixture_noconf_")
    testcase.addCleanup(shutil.rmtree, config, True)
    real_config_root = hostos_mod.config_root
    hostos_mod.config_root = lambda: config
    testcase.addCleanup(setattr, hostos_mod, "config_root",
                        real_config_root)

    reset_database_singletons()
    panel = panel_mod.AmazePanel()
    testcase.addCleanup(dispose_panel, panel)
    testcase.addCleanup(stop_panel_workers, panel)
    if panel.prefs.dir:
        raise RuntimeError(
            "the unconfigured fixture found a library (%s) - the "
            "isolation failed and this panel is not first-run"
            % panel.prefs.dir)
    return panel


def dispose_panel(panel) -> None:
    """The fixture's deleteLater, tolerating a panel the test already destroyed."""
    try:
        panel.deleteLater()
    except RuntimeError:
        pass                     # already gone, which is the point


def stop_panel_workers(panel) -> None:
    """Every QThread a panel may have started, stopped as quitting would. ▸p/harness-isolation"""
    from amaze.core import thumbnails

    try:
        model = getattr(panel, "matx_online_model", None)
    except RuntimeError:
        model = None             # the panel is already deleted
    if model is not None:
        try:
            model.shutdown()
        except Exception:                                # noqa: BLE001
            pass
    try:
        panel.unwatch_scene()    # `destroyed` is never emitted here after deleteLater
    except Exception:                                    # noqa: BLE001
        pass
    try:
        thumbnails.engine.shutdown()
    except Exception:                                    # noqa: BLE001
        pass
    try:
        flush_pending_saves()
    except Exception:                                    # noqa: BLE001
        pass


def toolbar_row(panel) -> list:
    """The toolbar row left to right, by `objectName`; unnamed widgets raise. ▸p/harness-isolation"""
    layout = panel.toolbar_layout
    row = []
    for index in range(layout.count()):
        item = layout.itemAt(index)
        widget = item.widget()
        if widget is not None:
            name = widget.objectName()
            if not name:
                raise RuntimeError(
                    "toolbar item %d is a %s with no objectName, so this "
                    "row cannot tell it from its siblings - give it one "
                    "where it is constructed"
                    % (index, type(widget).__name__)
                )
            row.append(name)
        elif item.expandingDirections():
            row.append("stretch")
        else:
            row.append("gap")
    return row


BADGE_FAMILY = ("badge_open", "badge_favourite", "badge_versions",
                "badge_comment")    # the tile badges, by SVG name, in corner order


def tile_delegate(roles, subtitle_role=None, **kwargs):
    """A tile delegate showing the badges in `roles`, each reading the number given (None: no role)."""
    from amaze.panel import delegates
    model = type("TileModel", (), {})
    for name, role in roles.items():
        if delegates.BADGE[name].role:
            setattr(model, delegates.BADGE[name].role, role)
    return delegates.AssetItemDelegate(
        subtitle_role, tile_badges=tuple(roles), tile_model=model, **kwargs)


def art_colours(name: str) -> set:
    """Every colour an SVG in ui/ declares, so tests avoid literal hexes. ▸p/harness-isolation"""
    import os
    import re

    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "ui", name if name.endswith(".svg") else name + ".svg")
    with open(path, encoding="utf-8") as handle:
        body = handle.read().lower()
    found = set(re.findall(r'(?:fill|stroke)="(#[0-9a-f]{3,8})"', body))
    found |= set(re.findall(r'(?<![-\w])(?:fill|stroke)\s*:\s*(#[0-9a-f]{3,8})', body))    # style-declared paints too: style outranks the presentation attribute ▸r/svg-style-overrides
    return {c for c in found if c != "none"}
