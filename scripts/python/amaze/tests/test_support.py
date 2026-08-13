"""Shared test plumbing: keep every test away from the user's REAL
library, settings and log.

DatabaseConnector caches one instance per filename and load() returns
the cached data even when the path changed - so a test that constructs
a model BEFORE pointing preferences at the fixture reads (and can
WRITE) whatever library the first construction touched. One live run
proved the in-memory mutation reaches the user's real library data;
only luck kept it off disk. Every integration test must therefore
(1) reset the connector cache, (2) inject preferences that already
point at a private COPY of the fixture.

The LOG is redirected at import of this module - no opt-in, because
the leak it prevents is invisible: guarded() and the excepthook record
crashes even with Debug Mode off, so tests that raise ON PURPOSE
(test_drag_gesture's raising action, test_debug_flood's 3,000
tracebacks) wrote genuine-looking crash records into the user's real
log. 18,975 of them, until its exception count could no longer be read
as "the app crashed" - which is exactly the question the log exists to
answer. Every test module imports this one for that reason alone.
"""

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

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "assets", "library")

#: WHO a fixture library belongs to. A user-tagged store keys nothing
#: without one, so a fixture with no user is a library whose per-user
#: entries silently do not exist (ROADMAP line 21 step 2d).
#:
#: A CONSTANT, not a fresh `uuid4`: a stored key that changes every run
#: cannot be compared across two runs and is unreadable in a failure
#: message. Shaped like a real minted UID, because the tag is split on
#: the first separator precisely BECAUSE a uuid4 hex cannot contain one.
FIXTURE_USER = "0f1e2d3c4b5a69788796a5b4c3d2e1f0"


def isolate_debug_log() -> str:
    """Send this process's debug log to a throwaway file.

    Reuses $AMAZE_LOG_DIR when the runner already set one, so the whole
    suite shares a single log (one file to read when a run misbehaves)
    instead of one per module. Sets it when running a module directly,
    so anything importing amaze afterwards - including a reloaded debug
    module, which re-reads the variable - stays isolated too."""
    directory = os.environ.get("AMAZE_LOG_DIR", "").strip()
    if not directory:
        directory = tempfile.mkdtemp(prefix="amaze_test_log_")
        atexit.register(shutil.rmtree, directory, True)
        os.environ["AMAZE_LOG_DIR"] = directory
    path = os.path.join(directory, "test_debug.jsonl")
    debug.redirect(path)
    # Belt and braces: a silent failure here is the whole bug, so the
    # suite refuses to run rather than quietly logging to the real file.
    real = os.path.realpath(hostos.log_root())
    if os.path.realpath(os.path.dirname(path)).startswith(real):
        raise RuntimeError(
            "test log isolation failed - %s is inside the real log dir %s"
            % (path, real)
        )
    return path


#: Redirected at IMPORT, deliberately not left to each test to remember.
TEST_LOG = isolate_debug_log()


def isolate_cache_root() -> str:
    """Send this process's thumbnail cache to a throwaway directory.

    Same reasoning as the log, and learned the same way. ThumbnailCache
    is constructed from hostos.cache_root(), and its clear() sweeps
    EVERY texture_thumbnails_* and geo_thumbnails_* directory it finds
    there - so a single test exercising "Delete Local Cache" against the
    default root wiped the user's real thumbnail caches. Regenerable,
    but geometry thumbnails are Karma renders and cost real minutes.

    Set through the ENVIRONMENT, not just the module global: opening a
    panel reloads hostos and then calls set_cache_override(
    prefs.cache_dir), which is "" for fixture prefs - so a module global
    alone was wiped mid-run and the suite went back to the real cache.
    Same mechanism as $AMAZE_LOG_DIR, for the same reason."""
    directory = os.environ.get(hostos.CACHE_DIR_ENV, "").strip()
    if not directory:
        directory = tempfile.mkdtemp(prefix="amaze_test_cache_")
        atexit.register(shutil.rmtree, directory, True)
        os.environ[hostos.CACHE_DIR_ENV] = directory
    hostos.set_cache_override(directory)
    # Belt and braces, exactly like the log: a silent failure here is
    # the whole bug, so refuse to run rather than sweep the real cache.
    resolved = os.path.realpath(hostos.cache_root())
    if not resolved.startswith(os.path.realpath(directory)):
        raise RuntimeError(
            "test cache isolation failed - cache_root() is %s, not %s"
            % (resolved, directory)
        )
    return directory


#: Redirected at IMPORT for the same reason as the log.
TEST_CACHE = isolate_cache_root()


def reset_database_singletons() -> None:
    """Drop every cached DatabaseConnector so the next construction
    loads from whatever path the test's preferences name.

    CLEAR the registry, never rebind it. `DatabaseConnector._instances`
    is the module-global `database._INSTANCES` held outside the class
    body on purpose - panel.py reloads the module on every panel open,
    and reload re-executes the `class` statement, so the class attribute
    is the only thing that can point back at the surviving registry.
    Assigning a fresh `{}` here DETACHED the class from that global:
    after this reset plus an importlib.reload, the reloaded class picked
    `_INSTANCES` back up and handed out the PRE-RESET connector, latches
    and all. Measured: a connector with `_write_blocked` set came back
    from a reset that was supposed to have dropped it, so every
    sabotage-verified refusal test in the suite was reporting on a
    resurrected object rather than the one the fix under test built.

    The identity check is not decoration. The rebind is a one-character
    edit away and its symptom is silent: tests keep passing, they just
    stop testing what they say they do.
    """
    database.DatabaseConnector._instances.clear()
    if database.DatabaseConnector._instances is not database._INSTANCES:
        raise RuntimeError(
            "the connector registry is no longer database._INSTANCES - "
            "every reload-survival mechanism reads that global, so this "
            "reset drops nothing a reloaded module can see"
        )


#: The committed File-section fixture: one tiny file per KIND, every
#: image format, and the filename shapes that have broken extension
#: matching. Built by make_file_fixtures.py, all synthetic.
FILES_FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "assets", "files")


def fresh_files_folder(testcase) -> str:
    """A throwaway COPY of the committed File-section fixture.

    This is what a fixture panel registers as its file location, and it
    is the whole reason the File section can be tested at all. Before
    2026-08-02 the panel-building tests ran against the machine's OWN
    registered locations - which on this machine are personal
    photograph and texture archives - so `activate()` on that tab
    scanned and converted several thousand of someone's photographs to
    assert a column width. A copy, not the original, so a test may
    delete and rewrite freely.
    """
    tmp = tempfile.mkdtemp(prefix="amaze_test_files_")
    testcase.addCleanup(shutil.rmtree, tmp, True)
    dest = os.path.join(tmp, "files")
    shutil.copytree(FILES_FIXTURE_DIR, dest)
    return dest + os.sep


def fresh_library(testcase) -> str:
    """A throwaway COPY of the committed fixture library, auto-removed
    after the test. Returns the directory with a trailing separator
    (the prefs.dir convention). Tests may mutate and save freely."""
    tmp = tempfile.mkdtemp(prefix="amaze_test_lib_")
    testcase.addCleanup(shutil.rmtree, tmp, True)
    dest = os.path.join(tmp, "library")
    shutil.copytree(FIXTURE_DIR, dest)
    return dest + os.sep


class _RecordedLog:
    """The records a `captured_log()` block wrote, read back per RECORD.

    Deliberately NO joined-text accessor. practice.md ▸ Testing: a test
    that asserts on joined output passes on text it did not mean - the
    Clean Library refusal test stayed green with its whole sentence
    deleted because the word it looked for was in a neighbouring line.
    So callers filter `messages()` and assert on one message.

    DRAINED when the block ends, into this object. The first version read
    the file lazily and the block removed its tempdir on the way out, so
    every assertion made after the `with` saw an empty list - which reads
    exactly like "the code said nothing" and would have been taken as a
    real defect had the messages not been known-good.
    """

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
    """Capture what `debug` RECORDS inside the block, not what it prints.

    Tests that assert on captured stdout for a `debug.note` are
    platform-dependent by construction: research.md ▸ *Debug log* - on
    Windows any print pops the Houdini Console, so note() returns BEFORE
    its print and stdout is empty. Three tests in test_generator did
    exactly that and went red under a forced `hostos.is_windows`, for
    messages that were recorded on both platforms.

    Turns Debug Mode ON for the duration, because note()'s log write is
    gated on it, and points the log at a throwaway file of its own so the
    block's records cannot be confused with the rest of the suite's.
    Swallows the print as well, so a passing run stays readable.

    Restores Debug Mode and the suite's shared log on the way out -
    including on an exception, or one failing test would leave verbose
    logging on for every test after it.

    Reads the FILE rather than spying on debug.note (which is what
    test_absent_database's local _NoteWatcher does, for a different
    question - it wants the note's structured data AND the print). Going
    through the file proves the record was actually written, which is
    the half note()'s Debug-Mode gate can silently skip.
    """
    directory = tempfile.mkdtemp(prefix="amaze_test_capture_")
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
        # DRAIN BEFORE THE FILE GOES, or every assertion after the block
        # reads an empty list and reports it as "the code said nothing".
        recorded._drain()
        shutil.rmtree(directory, True)


def live_library_to_rehearse_on(testcase):
    """The machine's configured library, or a skip.

    THE REAL LIBRARY, NOT THE SESSION'S. Both rehearsals recover the
    owner's own snapshots, which is the whole reason they exist - so
    they read `real_dir`, the configured path, and Test Mode's overlay
    cannot point them at a throwaway. Measured 2026-08-08: pointed at
    a young test library they failed twice for reasons that were true
    of that library and meaningless about recovery - `bak-1` empty
    because it predated the first save, then `bak-3` empty for the
    same reason once `bak-1` had grown.

    Still skips when there is nothing to rehearse ON, so a fresh
    machine and a brand-new library say so rather than fail.
    """
    live = prefs.Prefs()
    live.load()
    # The overlay is switched off on THIS instance - the helper's own,
    # never a shared one - so every `live.dir` downstream is the real
    # library without each call site having to remember.
    live.test_mode = False
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
    """Preferences pointing at a fresh fixture copy - inject into model
    constructors (Categories(preferences=...)) so nothing ever touches
    the machine's real settings/library.

    BOTH paths are redirected: .dir (the library) and .path (where
    settings.json lives). Prefs() resolves .path from $AMAZE, which
    under hython IS the live install - a single save() on a fixture
    Prefs would overwrite the user's real settings, which is exactly
    how a live settings file was lost once."""
    p = prefs.Prefs()
    p.dir = fresh_library(testcase)
    p.path = tempfile.mkdtemp(prefix="amaze_fixture_prefs_")
    testcase.addCleanup(shutil.rmtree, p.path, True)
    # A LIBRARY HAS USERS NOW, so a fixture without one is not a
    # realistic library: a user-tagged store would key nothing and the
    # section under test would silently show an empty list.
    #
    # POINTED, NOT MINTED, and the difference is the blast radius
    # (practice.md ▸ A STORE MANY THINGS READ IS NOT TURNED ON
    # INCREMENTALLY). `users.current(p)` mints, and a mint writes
    # `users.json` INTO the library - so every fixture library would
    # gain a file it did not have, and every test asserting on a
    # library's CONTENTS would answer about the fixture rather than
    # about the product. `Store.user_tag` reads `library_user` and
    # nothing else, so a UID in the preference is the whole
    # requirement and the fixture stays byte-identical.
    p.library_user = FIXTURE_USER
    return p


def class_scope(testcase_class):
    """A stand-in for `self` when a fixture is built once per CLASS.

    The helpers here register teardown through `addCleanup`, which is
    per-TEST. A panel is expensive enough to build once for a whole
    class, and this routes those registrations to `addClassCleanup` so
    they still run exactly once, after the last test in it."""
    class _Scope:
        @staticmethod
        def addCleanup(function, *args, **kwargs):
            testcase_class.addClassCleanup(function, *args, **kwargs)
    return _Scope


#: Every section key, so a fixture panel can drive any tab regardless of
#: what the machine's own settings happen to have switched on.
ALL_SECTION_KEYS = ("material", "gradient", "cop", "code", "file")


def fixture_panel(testcase):
    """A REAL MatLibPanel, built against a private fixture library.

    The panel takes no preferences - it constructs its own `Prefs()` and
    calls `load()` - so the only way in is the directory `Prefs.__init__`
    reads its settings from. Redirecting `hostos.config_root` puts both
    the settings file and (through the settings we write there) the
    library inside a tempdir, so this reaches nothing of the user's.

    TWO ORDERING TRAPS, both measured:

    * **Import the panel module BEFORE patching.** `panel.py` reloads
      `hostos` at import time, which re-executes the module and restored
      the real `config_root` - a patch applied first was silently undone
      and the panel opened the user's real library (measured: prefs.dir
      came back as the live path).
    * **Reset the connector cache before constructing**, per this
      module's own docstring: the models are built during construction.

    THREE MORE THINGS A CONSTRUCTED PANEL REACHES, all closed here:

    * **`Prefs.save` is disabled**, as practice.md requires of every
      panel-constructing script: the view-mode toggle persists itself
      while the panel builds. Redirecting config_root already sends that
      write into the tempdir, but the tempdir is removed at cleanup while
      the panel object is still alive (deleteLater never runs without an
      event loop), so a deferred save timer would fire at a deleted path.
    * **The network is blocked**, at `matx_sources._request` - the one
      urlopen in the package. Entering the online browser starts a
      catalogue worker that fetches EVERY source, so one placeholder
      assertion made four live third-party requests, each able to stall
      for TIMEOUT (30s) while shutdown terminates the thread after 3.
      The worker turns the refusal into an ordinary "could not reach"
      errors entry, which is what an offline machine looks like anyway.
    * **The catalogue cache is asserted**, not assumed. It used to be an
      import-time constant off the real cache root (see matx_library),
      and a fixture panel read the user's real 684KB catalogue and was
      one `if errors:` away from writing it.

    The panel is deleted and every patch restored on cleanup.
    """
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

    config = tempfile.mkdtemp(prefix="amaze_fixture_panel_")
    testcase.addCleanup(shutil.rmtree, config, True)
    library = fresh_library(testcase)
    files = fresh_files_folder(testcase)
    with open(os.path.join(config, "settings.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"directory": library,
                   "enabled_sections": list(ALL_SECTION_KEYS),
                   # IN THE SETTINGS FILE, because the panel builds its
                   # OWN Prefs and calls load() - so a user assigned to
                   # some other Prefs object never reaches it, and every
                   # user-tagged store in the panel keys nothing.
                   "library_user": FIXTURE_USER,
                   # The File section gets its OWN location. Registering
                   # none left the tab empty, which is safe but untested;
                   # registering the machine's own is what reached the
                   # user's photograph archive. A private copy is both.
                   "file_folders": [files],
                   "last_file_folder": files}, handle)

    real_config_root = hostos_mod.config_root
    hostos_mod.config_root = lambda: config
    testcase.addCleanup(setattr, hostos_mod, "config_root", real_config_root)

    reset_database_singletons()
    panel = panel_mod.MatLibPanel()
    testcase.addCleanup(dispose_panel, panel)
    # Registered AFTER deleteLater so it runs BEFORE it (cleanups are
    # LIFO). Measured: without this the suite itself passed and the
    # PROCESS aborted at interpreter shutdown - "QThread: Destroyed
    # while thread is still running", exit 134, i.e. a red gate under a
    # green run. Both engines hang their shutdown on
    # QCoreApplication.aboutToQuit, which hython never emits: nothing
    # quits the app, it is destroyed by Py_Finalize. Entering the online
    # browser starts a catalogue worker, and activating a section queues
    # thumbnail loaders, so a fixture panel leaves both kinds running.
    testcase.addCleanup(stop_panel_workers, panel)

    # ASSERT THE ISOLATION, do not assume it. The patch above is one
    # reload away from being undone, and its failure mode is a test
    # quietly running against the user's real library.
    checked = [("settings", panel.prefs.path),
               ("library", panel.prefs.dir),
               ("catalogue cache", matx_library.catalogue_cache()),
               # Its import-time twin, caught 2026-08-02 by the
               # same reasoning that caught the catalogue.
               ("preview cache", matx_library.preview_cache())]
    # THE REGISTERED FOLDERS, added 2026-08-02. These are the File
    # section's locations, and on a real machine they are the user's
    # own photograph and texture archives. `activate()` on that section
    # SCANS every one of them and converts every image it finds - so a
    # panel test that reaches them is not merely reading the wrong
    # data, it is grinding through somebody's personal files for a UI
    # assertion. The fixture settings above register none, and this is
    # what proves it stayed that way.
    # NAMED, not `getattr(..., ())` - the texture/geometry/hip lists
    # were swept 2026-08-12 and a defaulting lookup would narrow this
    # to one kind without saying so.
    for folder in panel.prefs.file_folders or ():
        checked.append(("file_folders", str(folder)))
    for label, path in checked:
        if not os.path.realpath(path).startswith(
                os.path.realpath(tempfile.gettempdir())):
            raise RuntimeError(
                "fixture panel isolation failed - %s is %s, outside the "
                "temp directory" % (label, path)
            )
    # A panel that failed to load its library never runs setup(), so it
    # has no models and no active section - every test built on this
    # would be exercising the unconfigured shell instead.
    if panel.material_model is None:
        raise RuntimeError(
            "the fixture panel did not load its library, so setup() never "
            "ran - this fixture is not building the panel tests need"
        )
    return panel


def reopened_panel(testcase):
    """A SECOND panel over the SAME already-redirected fixture scope -
    the reopen-after-something-happened shape (a repaired index, a
    relaunch scenario). Valid only after fixture_panel has run in this
    testcase's scope: it performs no redirection of its own, so
    without the fixture's config_root patch it would build against
    the machine's real settings. It asserts that precondition instead
    of trusting it. Unlike fixture_panel it makes NO demands on what
    loaded - the whole point is testing panels that open broken."""
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
    """A REAL MatLibPanel with NO library configured - the first-run
    state, which is a real machine state the panel must survive
    (Preferences is the only way OUT of it).

    The same guards as fixture_panel - config_root redirected to a
    tempdir, Prefs.save disabled, the network blocked - plus one this
    fixture alone needs: the LEGACY path blanked, because under hython
    $AMAZE is the live install and load() would migrate the user's
    real settings straight into the "unconfigured" panel. No library,
    no settings file: prefs.load() answers False and the panel takes
    its no-library branch.
    """
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

    config = tempfile.mkdtemp(prefix="amaze_fixture_noconf_")
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
    """The fixture's own deleteLater, tolerating a panel the test has
    already destroyed - a test about panel TEARDOWN has to be able to
    delete it and still tear down cleanly."""
    try:
        panel.deleteLater()
    except RuntimeError:
        pass                     # already gone, which is the point


def stop_panel_workers(panel) -> None:
    """Stop every QThread a constructed panel may have started.

    Both shutdowns are idempotent and safe when nothing is running, and
    both are what the app itself calls on quit - this is the same call,
    made explicitly, because hython never gets there."""
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
    """The toolbar row as it reads LEFT TO RIGHT, one entry per item.

    A widget becomes its `objectName()`, a fixed gap `"gap"` and the
    expanding one `"stretch"`. That is the actual on-screen order, after
    every builder and after `_mirror_toolbar` - the thing source offsets
    in panel.py cannot report.

    KEYED ON objectName, and both halves of that matter:

    * It is the only identity every one of these widgets has. The first
      version looked up whichever panel ATTRIBUTE held the widget, which
      answered `"IconMenuButton"` for all three menu/action buttons
      because no attribute holds them - so Renderer, View and
      Preferences were interchangeable and swapping two of them on
      screen passed the whole suite. The same collapse practice.md
      records for ui_snapshot's unnamed siblings.
    * It does not move when code is renamed. The attribute version went
      RED on a pure rename with no layout change at all, and reported it
      as "the toolbar row is not in the designed order" - a test that
      lies about the cause is worth little more than one that misses it.

    An unnamed widget raises rather than falling back to its class name:
    a fallback is what let three siblings share one key, and the fix is
    one `setObjectName` at the widget's construction.
    """
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


#: The tile badges, by art name - the family, in corner order.
BADGE_FAMILY = ("badge_open", "badge_star", "badge_versions",
                "badge_comment")


def art_colours(name: str) -> set:
    """Every colour an SVG in ui/ actually declares.

    Badge tests assert the SHAPE of the family - all four share a
    backdrop colour, each carries a glyph on top of it - never
    literal hexes: the art is redrawn whenever the design moves
    (twice on 2026-08-01 alone), and a test that names colours turns
    red on every redraw while proving nothing about the family.
    """
    import os
    import re

    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "ui", name if name.endswith(".svg") else name + ".svg")
    with open(path, encoding="utf-8") as handle:
        body = handle.read().lower()
    found = set(re.findall(r'(?:fill|stroke)="(#[0-9a-f]{3,8})"', body))
    return {c for c in found if c != "none"}
