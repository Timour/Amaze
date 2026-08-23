"""Shared test plumbing: every door here keeps a test away from the user's REAL library, settings, caches and log - the leak each door closed is recorded once, in the wiki. ▸p/harness-isolation"""

import atexit
import contextlib
import io
import json
import os
import shutil
import tempfile

from amaze.core import database, debug
from amaze.helpers import hostos
from amaze.prefs import prefs


def _adopt_suite_root() -> str:
    """Make `<test_dir>/suite/` THE tempdir for this whole process - settings' own Test Library folder is where suite debris belongs, and pointing `TMPDIR` there at IMPORT carries every consumer at once: the per-module `mkdtemp`s, the write sandbox and the fixture isolation asserts all define scratch as `tempfile.gettempdir()`. Answers "" on a machine that designates no folder, and tempfile's default stands. ▸p/suite-debris-home"""
    try:
        with open(os.path.join(hostos.config_root(), "settings.json"),
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
    """Every directory this module mints comes from HERE - the adopted tempdir, so test libraries land under the machine's designated Test Library folder wherever one exists. ▸p/suite-debris-home"""
    return tempfile.mkdtemp(prefix=prefix)


FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "assets", "library")

FIXTURE_USER = "0f1e2d3c4b5a69788796a5b4c3d2e1f0"    # WHO a fixture library belongs to - a CONSTANT shaped like a minted UID, comparable across runs and printable in a failure. ▸p/harness-isolation


def isolate_debug_log() -> str:
    """Send this process's debug log to a throwaway file - reuses a runner-set `$AMAZE_LOG_DIR`, sets it otherwise, and REFUSES to run when the redirect lands inside the real log dir. ▸p/harness-isolation"""
    directory = os.environ.get("AMAZE_LOG_DIR", "").strip()
    if not directory:
        directory = scratch_dir("amaze_test_log_")
        atexit.register(shutil.rmtree, directory, True)
        os.environ["AMAZE_LOG_DIR"] = directory
    path = os.path.join(directory, "test_debug.jsonl")
    debug.redirect(path)
    real = os.path.realpath(hostos.log_root())
    if os.path.realpath(os.path.dirname(path)).startswith(real):
        raise RuntimeError(
            "test log isolation failed - %s is inside the real log dir %s"
            % (path, real)
        )
    return path


TEST_LOG = isolate_debug_log()    # redirected at IMPORT, deliberately not left to each test to remember


def isolate_cache_root() -> str:
    """Send this process's thumbnail cache to a throwaway directory, through the ENVIRONMENT so a panel's hostos reload keeps it - and refuse to run when `cache_root()` still answers the real one. ▸p/harness-isolation"""
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
    """Drop every cached DatabaseConnector so the next construction loads from the test's own path - CLEARED in place, never rebound, and the identity check is load-bearing. ▸p/mutate-not-rebind, ▸p/harness-isolation"""
    database.DatabaseConnector._instances.clear()
    if database.DatabaseConnector._instances is not database._INSTANCES:
        raise RuntimeError(
            "the connector registry is no longer database._INSTANCES - "
            "every reload-survival mechanism reads that global, so this "
            "reset drops nothing a reloaded module can see"
        )


FILES_FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "assets", "files")    # the committed File-section fixture: one tiny file per KIND, built by make_file_fixtures.py, all synthetic


def posix_relpath(path: str, start: str) -> str:
    """A RELATIVE path in the one spelling the product and the docs use - forward slashes on every OS, where `os.path.relpath` answers in the host's dialect. ▸p/harness-isolation"""
    return os.path.relpath(path, start).replace(os.sep, "/")


def posix_path(path: str) -> str:
    """An ABSOLUTE path spelled the way the stores spell it, trailing separator intact - the product's OWN round trip through `storage_path_key`/`expand_storage_path`, never a re-derivation. ▸p/harness-isolation"""
    return hostos.expand_storage_path(hostos.storage_path_key(path))


def fresh_files_folder(testcase) -> str:
    """A throwaway COPY of the committed File-section fixture - what a fixture panel registers as its file location, so no test ever scans a real machine's own folders. ▸p/harness-isolation"""
    tmp = scratch_dir("amaze_test_files_")
    testcase.addCleanup(shutil.rmtree, tmp, True)
    dest = os.path.join(tmp, "files")
    shutil.copytree(FILES_FIXTURE_DIR, dest)
    return posix_path(dest) + "/"


def fresh_library(testcase) -> str:
    """A throwaway COPY of the committed fixture library, auto-removed after the test, in the `prefs.dir` convention WHOLE - forward slashes AND trailing separator. Tests may mutate and save freely. ▸p/harness-isolation"""
    tmp = scratch_dir("amaze_test_lib_")
    testcase.addCleanup(shutil.rmtree, tmp, True)
    dest = os.path.join(tmp, "library")
    shutil.copytree(FIXTURE_DIR, dest)
    return posix_path(dest) + "/"


class _RecordedLog:
    """The records a `captured_log()` block wrote, read back per RECORD - deliberately no joined-text accessor, and drained before the block's tempdir goes. ▸p/harness-isolation"""

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


@contextlib.contextmanager
def captured_log():
    """Capture what `debug` RECORDS inside the block, not what it prints - Debug Mode on for the duration, its own throwaway file, mode and the shared log restored even on exception. ▸p/harness-isolation"""
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


def live_library_to_rehearse_on(testcase):
    """The machine's configured REAL library (`real_dir`, never the Test Mode overlay) or a skip - recovery rehearsals recover the owner's own snapshots or they prove nothing. ▸p/harness-isolation"""
    live = prefs.Prefs()
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
    """Preferences pointing at a fresh fixture copy, BOTH paths redirected (.dir and .path), the fixture user POINTED rather than minted so the library stays byte-identical - inject into model constructors. ▸p/harness-isolation"""
    p = prefs.Prefs()
    p.dir = fresh_library(testcase)
    p.path = scratch_dir("amaze_fixture_prefs_")
    testcase.addCleanup(shutil.rmtree, p.path, True)
    p.library_user = FIXTURE_USER
    return p


def class_scope(testcase_class):
    """A stand-in for `self` when a fixture is built once per CLASS - routes the helpers' `addCleanup` registrations to `addClassCleanup`."""
    class _Scope:
        @staticmethod
        def addCleanup(function, *args, **kwargs):
            testcase_class.addClassCleanup(function, *args, **kwargs)
    return _Scope


ALL_SECTION_KEYS = ("material", "gradient", "cop", "code", "file")    # every section key, so a fixture panel can drive any tab regardless of the machine's own settings


def fixture_panel(testcase):
    """A REAL MatLibPanel over a private fixture library: `hostos.config_root` redirected (AFTER importing panel.py, which reloads hostos), saves disabled, network blocked, workers stopped on cleanup, and the isolation ASSERTED rather than assumed. ▸p/harness-isolation"""
    from amaze.panel import panel as panel_mod       # reloads hostos
    from amaze.helpers import hostos as hostos_mod
    from amaze.core import matx_library, matx_sources

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
    library = fresh_library(testcase)
    files = fresh_files_folder(testcase)
    with open(os.path.join(config, "settings.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"directory": library,
                   "enabled_sections": list(ALL_SECTION_KEYS),
                   "library_user": FIXTURE_USER,    # IN THE SETTINGS FILE - the panel builds its OWN Prefs and load()s, so a user on some other Prefs object never reaches it
                   "file_folders": [files],
                   "file_location_records": {
                       files: {"registered": True}},
                   "last_file_folder": files}, handle)

    real_config_root = hostos_mod.config_root
    hostos_mod.config_root = lambda: config
    testcase.addCleanup(setattr, hostos_mod, "config_root", real_config_root)

    reset_database_singletons()
    panel = panel_mod.MatLibPanel()
    testcase.addCleanup(dispose_panel, panel)
    testcase.addCleanup(stop_panel_workers, panel)    # AFTER deleteLater so it runs BEFORE it (cleanups are LIFO) - hython never emits aboutToQuit, so unstopped engines abort the process at Py_Finalize

    checked = [("settings", panel.prefs.path),
               ("library", panel.prefs.dir),
               ("catalogue cache", matx_library.catalogue_cache()),
               ("preview cache", matx_library.preview_cache())]
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
    return panel


def reopened_panel(testcase):
    """A SECOND panel over the SAME already-redirected fixture scope - valid only after `fixture_panel` in this scope, asserted rather than trusted, and with NO demands on what loaded (broken-open panels are the point). ▸p/harness-isolation"""
    from amaze.helpers import hostos as hostos_mod
    from amaze.panel import panel as panel_mod

    probe = hostos_mod.config_root()
    if not os.path.realpath(probe).startswith(
            os.path.realpath(tempfile.gettempdir())):
        raise RuntimeError(
            "reopened_panel without fixture_panel's redirection - "
            "config_root is %s, outside the temp directory" % probe)
    panel = panel_mod.MatLibPanel()
    testcase.addCleanup(dispose_panel, panel)
    testcase.addCleanup(stop_panel_workers, panel)
    return panel


def fixture_unconfigured_panel(testcase):
    """A REAL MatLibPanel with NO library configured - the first-run state - with `fixture_panel`'s guards plus the LEGACY path blanked, so `load()` cannot migrate the real settings into the "unconfigured" panel. ▸p/harness-isolation"""
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
    panel = panel_mod.MatLibPanel()
    testcase.addCleanup(dispose_panel, panel)
    testcase.addCleanup(stop_panel_workers, panel)
    if panel.prefs.dir:
        raise RuntimeError(
            "the unconfigured fixture found a library (%s) - the "
            "isolation failed and this panel is not first-run"
            % panel.prefs.dir)
    return panel


def dispose_panel(panel) -> None:
    """The fixture's own deleteLater, tolerating a panel the test has already destroyed - teardown tests delete their own panel."""
    try:
        panel.deleteLater()
    except RuntimeError:
        pass                     # already gone, which is the point


def stop_panel_workers(panel) -> None:
    """Stop every QThread a constructed panel may have started - both shutdowns idempotent, the same calls the app makes on quit, made here because hython never gets there. ▸p/harness-isolation"""
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
        thumbnails.engine.shutdown()
    except Exception:                                    # noqa: BLE001
        pass


def toolbar_row(panel) -> list:
    """The toolbar row as it reads LEFT TO RIGHT - widgets by `objectName` (the one identity they all carry, stable across renames; an unnamed widget RAISES), a fixed gap as `"gap"`, the expanding item as `"stretch"`. ▸p/harness-isolation"""
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


BADGE_FAMILY = ("badge_open", "badge_star", "badge_versions",
                "badge_comment")    # the tile badges, by art name - the family, in corner order


def art_colours(name: str) -> set:
    """Every colour an SVG in ui/ actually declares - badge tests assert the SHAPE of the family from these, never literal hexes, because the art is redrawn whenever the design moves. ▸p/harness-isolation"""
    import os
    import re

    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "ui", name if name.endswith(".svg") else name + ".svg")
    with open(path, encoding="utf-8") as handle:
        body = handle.read().lower()
    found = set(re.findall(r'(?:fill|stroke)="(#[0-9a-f]{3,8})"', body))
    found |= set(re.findall(r'(?<![-\w])(?:fill|stroke)\s*:\s*(#[0-9a-f]{3,8})', body))    # style-declared paints too - a style attribute outranks the presentation attribute beside it (r/svg-style-wins), so an Inkscape export declares its real colours here
    return {c for c in found if c != "none"}
