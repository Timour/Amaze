"""Test plumbing keeping tests off the real library, settings, caches and log. ▸p/harness-isolation"""

import atexit
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import time
import types

from amaze.helpers import hostos

os.environ[hostos.SANDBOX_VAR] = "1"    # armed at IMPORT, however the test was started ▸p/hand-run-script-is-unguarded


def call_as_amaze(fn):
    """Call `fn` from a frame whose module name is Amaze's own, the way an import's frames read."""
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
    """Run the event loop until done answers true or the time is up, and answer done."""
    from PySide6 import QtWidgets
    deadline = time.monotonic() + timeout
    while not done() and time.monotonic() < deadline:
        QtWidgets.QApplication.processEvents()
        time.sleep(0.002)
    return bool(done())


def _adopt_suite_root() -> str:
    """Point `TMPDIR` at `<test_dir>/suite/` at import, when a folder is set. ▸p/suite-debris-home"""
    try:
        with open(os.path.join(hostos.real_config_root(), "settings.json"),
                  encoding="utf-8") as handle:
            configured = str(json.load(handle).get("test_dir", "") or "")
    except (OSError, ValueError):
        return ""
    if not configured:
        return ""
    root = os.path.join(os.path.expanduser(configured), "suite")
    try:
        os.makedirs(root, exist_ok=True)
    except OSError:
        return ""
    os.environ["TMPDIR"] = root
    tempfile.tempdir = None    # gettempdir() re-reads the environment on its next ask
    return root


SUITE_ROOT = _adopt_suite_root()


def scratch_dir(prefix: str) -> str:
    """Every directory this module mints, under the adopted tempdir. ▸p/suite-debris-home"""
    return tempfile.mkdtemp(prefix=prefix)


def isolate_user_folders() -> str:
    """Point the sandbox's stand-in settings, cache and log folders into this run's temp dir."""
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

from amaze.core import database, debug                  # noqa: E402
from amaze.prefs import prefs                           # noqa: E402


FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "assets", "library")

FIXTURE_USER = "0f1e2d3c4b5a69788796a5b4c3d2e1f0"    # the fixture library's owner: a constant shaped like a minted UID


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
    """Drop every cached DatabaseConnector, cleared in place, never rebound. ▸p/mutate-not-rebind"""
    from amaze.core import model_registry
    stop_stamp_checks()    # a stamp check of the last test's library would write into the next
    database.DatabaseConnector._instances.clear()
    model_registry.release()    # models alias the connector's document, so a kept model would leak old rows
    if database.DatabaseConnector._instances is not database._INSTANCES:
        raise RuntimeError(
            "the connector registry is no longer database._INSTANCES - "
            "every reload-survival mechanism reads that global, so this "
            "reset drops nothing a reloaded module can see"
        )


def settle_stamps() -> None:
    """Wait for every stamp check to end, then hand what each found to this thread."""
    from PySide6 import QtCore
    from amaze.core import library
    for worker in list(library.stamps._threads):
        worker.wait(10000)
    QtCore.QCoreApplication.sendPostedEvents()


def stop_stamp_checks() -> None:
    """Stop every stamp check, as quitting does: one left running outlives the test that started it."""
    from amaze.core import library
    library.stamps.shutdown()


FILES_FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "assets", "files")    # one tiny synthetic file per kind, built by make_file_fixtures.py


def posix_relpath(path: str, start: str) -> str:
    """A relative path with forward slashes on every OS. ▸p/harness-isolation"""
    return os.path.relpath(path, start).replace(os.sep, "/")


def posix_path(path: str) -> str:
    """An absolute path as the stores spell it, via the product's own round trip. ▸p/harness-isolation"""
    return hostos.expand_storage_path(hostos.storage_path_key(path))


def fresh_files_folder(testcase) -> str:
    """A throwaway copy of the File-section fixture, for a fixture panel. ▸p/harness-isolation"""
    tmp = scratch_dir("amaze_test_files_")
    testcase.addCleanup(shutil.rmtree, tmp, True)
    dest = os.path.join(tmp, "files")
    shutil.copytree(FILES_FIXTURE_DIR, dest)
    return posix_path(dest) + "/"


def pin_scene_folder(testcase) -> str:
    """`$HIP` is a fresh folder of two files for the test, then its old value."""
    import hou
    scene = scratch_dir("amaze_test_scene_")
    testcase.addCleanup(shutil.rmtree, scene, True)
    for name in ("shot.hip", "notes.txt"):
        open(os.path.join(scene, name), "w").close()
    testcase.addCleanup(hou.putenv, "HIP", hou.getenv("HIP"))    # always set: `pin_env` would skip it
    hou.putenv("HIP", scene)
    return posix_path(scene) + "/"


def fresh_library(testcase, source=None) -> str:
    """A throwaway fixture library copy, spelled as `prefs.dir`, free to mutate. ▸p/harness-isolation"""
    tmp = scratch_dir("amaze_test_lib_")
    testcase.addCleanup(shutil.rmtree, tmp, True)
    testcase.addCleanup(stop_stamp_checks)    # runs first: no check writes into a copy being removed
    dest = os.path.join(tmp, "library")
    shutil.copytree(source or FIXTURE_DIR, dest)
    return posix_path(dest) + "/"


_SEEDED = []    # the first seeded panel library, which later fixture panels copy
_PER_PANEL = ("locations.json", "location_paths.json")    # each panel writes its own


def _keep_seeded(library: str) -> None:
    """The first seeded panel library, minus its location files: what later panels copy."""
    from amaze.core import gradient_library
    marker = os.path.join(library, gradient_library.GradientLibrary._SEED_MARKER)
    if _SEEDED or not os.path.exists(marker):
        return
    keep = os.path.join(scratch_dir("amaze_seeded_fixture_"), "library")
    atexit.register(shutil.rmtree, os.path.dirname(keep), True)
    shutil.copytree(library, keep, ignore=lambda _folder, names: [
        name for name in names if name.startswith(_PER_PANEL)])
    _SEEDED.append(keep)


def seeded_library(testcase) -> str:
    """`fresh_library`, already seeded, so a switch onto it skips the curated palettes."""
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
    """The assets added since `before`, in row order: a new row sorts in. ▸p/grid-engine"""
    return [asset for asset in model.assets if str(asset.mat_id) not in before]


def refused_at_open(path, error=None):
    """`open` refusing `path` alone, by default as a file another account owns refuses this one."""
    import errno
    from unittest import mock
    error = error or PermissionError(errno.EACCES, "Permission denied", path)
    real_open = open
    wanted = os.path.realpath(path)

    def refused(name, *args, **kwargs):
        if isinstance(name, (str, os.PathLike)) and os.path.realpath(name) == wanted:
            raise error
        return real_open(name, *args, **kwargs)

    return mock.patch("builtins.open", refused)


def full_disk_for(path):
    """`hostos.write_json_atomic` refusing `path` alone, as a full disk refuses a write."""
    import errno
    from unittest import mock
    real_write = hostos.write_json_atomic
    wanted = os.path.realpath(path)

    def refused(name, *args, **kwargs):
        if os.path.realpath(name) == wanted:
            raise OSError(errno.ENOSPC, "No space left on device", name)
        return real_write(name, *args, **kwargs)

    return mock.patch.object(hostos, "write_json_atomic", refused)


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
        recorded._drain()    # BEFORE the file goes, or every later assertion reads "the code said nothing"
        shutil.rmtree(directory, True)


@contextlib.contextmanager
def row_moves_inside_a_layout_change(*models):
    """Every row insert, removal or reset sent while that model's layout change was open."""
    caught = []
    wired = []

    def follower(model, name, depth):
        def heard(*_args):
            if depth[0]:
                caught.append("%s.%s" % (type(model).__name__, name))
        return heard

    for model in models:
        depth = [0]    # the open pairs; the H21 segfault shape is a row move at depth > 0

        def opened(*_args, depth=depth):
            depth[0] += 1

        def closed(*_args, depth=depth):
            depth[0] = max(0, depth[0] - 1)

        slots = [(model.layoutAboutToBeChanged, opened),
                 (model.layoutChanged, closed)]
        for name in ("rowsInserted", "rowsRemoved", "modelReset"):
            slots.append((getattr(model, name),
                          follower(model, name, depth)))
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
                pass             # the model went first


def plugins_loaded(*renderers):
    """Each material conversion API answers loaded for `renderers` alone, MaterialX always."""
    from unittest import mock
    from amaze.render.material_conversion import engine
    stack = contextlib.ExitStack()
    for each in engine.apis().values():
        if each.name != engine.HUB:
            stack.enter_context(mock.patch.object(
                each, "available", lambda name=each.name: name in renderers))
    return stack


def renderer_loaded(key: str) -> bool:
    """Whether `key`'s plugin is loaded, asked the product's way - the answer `plugins_loaded` fakes."""
    from amaze.render.material_conversion import engine
    return engine.api(key).available()


def pin_env(scope, name: str, value: str) -> None:
    """`$name` is `value` for `scope` wherever the product reads it as unset; its own state comes back."""
    import hou
    previous = hou.getenv(name)
    if previous:    # the product's gate is `not hou.getenv(name)`, so an empty `OCIO =` is unset
        return
    if previous is None:
        scope.addCleanup(hou.unsetenv, name)
    else:
        scope.addCleanup(hou.putenv, name, previous)
    hou.putenv(name, value)


def clear_obj() -> None:
    """Object level back to empty, whatever a test built there."""
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


def plain_python() -> str:
    """The Python under this one, started in under a second; hython itself costs 20 s."""
    for name in (os.path.join("bin", "python3"), "python.exe"):
        path = os.path.join(sys.base_prefix, name)
        if os.path.isfile(path):
            return path
    return sys.executable


def live_library_to_rehearse_on(testcase):
    """The configured real library (`real_dir`, never the overlay), or a skip. ▸p/harness-isolation"""
    live = prefs.Prefs()
    live.path = hostos.real_config_root()    # the user's own settings, read only - the sandbox refuses a write
    live.load()
    live.test_mode = False    # this instance's own overlay switch, so every `live.dir` downstream is the real library
    directory = getattr(live, "real_dir", "") or live.dir
    index = os.path.join(directory, "library.json") if directory else ""
    if not index or not os.path.exists(index):
        testcase.skipTest("no library configured on this machine")
    try:
        with open(index, encoding="utf-8-sig") as handle:
            if not (json.load(handle).get("assets") or []):
                testcase.skipTest(
                    "the configured library is empty - nothing to "
                    "rehearse a recovery on")
    except (OSError, ValueError, AttributeError):
        testcase.skipTest("the configured library could not be read")
    return live


def fixture_prefs(testcase):
    """Preferences with .dir and .path on a fresh fixture copy, user pointed. ▸p/harness-isolation"""
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
    """`library`, holding the fixture user: a panel opens a library only with its user."""
    import types
    from amaze.core import keyed_store, users
    holder = types.SimpleNamespace(dir=library, library_user=FIXTURE_USER)
    keyed_store.open_store(users.SPEC, holder).set(FIXTURE_USER, {"name": FIXTURE_USER_NAME})
    keyed_store.release()
    return library


def fixture_panel(testcase, render_geometry=False):
    """A real AmazePanel over a private fixture library, isolation asserted. ▸p/harness-isolation"""
    from amaze.panel import panel as panel_mod       # reloads hostos
    from amaze.helpers import hostos as hostos_mod
    from amaze.core import matx_library, matx_sources
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
    scene = pin_scene_folder(testcase)    # before the panel: its cleanup then runs after the panel's
    with open(os.path.join(config, "settings.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"directory": library,
                   "enabled_sections": list(ALL_SECTION_KEYS),
                   "library_user": FIXTURE_USER,    # in the settings file: the panel builds and loads its own Prefs
                   "file_folders": [files],
                   "file_location_records": {
                       files: {"registered": True}},
                   "last_file_folder": files}, handle)

    real_config_root = hostos_mod.config_root
    hostos_mod.config_root = lambda: config
    testcase.addCleanup(setattr, hostos_mod, "config_root", real_config_root)

    reset_database_singletons()
    panel = panel_mod.AmazePanel()
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
    """A second panel over the same scope, only after `fixture_panel`. ▸p/harness-isolation"""
    from amaze.helpers import hostos as hostos_mod
    from amaze.panel import panel as panel_mod

    probe = hostos_mod.config_root()
    if not os.path.realpath(probe).startswith(
            os.path.realpath(tempfile.gettempdir())):
        raise RuntimeError(
            "reopened_panel without fixture_panel's redirection - "
            "config_root is %s, outside the temp directory" % probe)
    panel = panel_mod.AmazePanel()
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
        panel.unwatch_scene()    # deleteLater never pumps `destroyed` here
    except Exception:                                    # noqa: BLE001
        pass
    try:
        thumbnails.engine.shutdown()
    except Exception:                                    # noqa: BLE001
        pass
    try:
        stop_stamp_checks()
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
                "badge_comment")    # the tile badges, by art name - the family, in corner order


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
    found |= set(re.findall(r'(?<![-\w])(?:fill|stroke)\s*:\s*(#[0-9a-f]{3,8})', body))    # style-declared paints too: style outranks the presentation attribute ▸r/svg-style-wins
    return {c for c in found if c != "none"}
