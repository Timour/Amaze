"""How `debug` reports: `alert` once per condition, `refuse` once per action. ▸p/refuse-vs-alert"""

import ast
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")    # BEFORE the app ▸p/first-app-picks-the-platform
import hou                                                # noqa: E402
from PySide6 import QtCore, QtWidgets                     # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])    # the fixture panel is a widget

from amaze.core import debug                             # noqa: E402
from amaze.helpers import hostos                         # noqa: E402
from amaze.tests import test_support                      # noqa: E402


class AlertIsOncePerConditionTest(unittest.TestCase):
    """A condition inside a loop must interrupt ONCE."""

    def setUp(self):
        self._shown = []
        real = debug.alert    # captured through the headless print fallback rather than by mocking hou
        self.addCleanup(setattr, debug, "alert", real)
        self.addCleanup(debug._alerted.clear)
        debug._alerted.clear()

    def _count(self, *calls):
        shown = 0
        for message, key in calls:
            if debug.alert(message, key=key):
                shown += 1
        return shown

    def test_each_key_shows_once(self):
        """A per-file message aggregates on its KEY; with no key the message is the key."""
        for why, calls, expected in (
                ("a per-file message", [("could not save icon %s.png" % n,
                                         "icons-not-saved") for n in "abc"], 1),
                ("a second, unrelated condition",
                 [("icons", "icons-not-saved"), ("icons", "icons-not-saved"),
                  ("gradients", "gradients-unreadable")], 2),
                ("no key at all", [("one exact sentence", "")] * 2, 1)):
            with self.subTest(why):
                debug._alerted.clear()
                self.assertEqual(expected, self._count(*calls),
                                 "%s showed the wrong number of dialogs" % why)

    def test_it_is_recorded_even_when_it_does_not_show(self):
        """Every occurrence reaches the log, which is how "rare" is verified later."""
        debug.configure(True, debug.log_path())
        self.addCleanup(debug.configure, False, debug.log_path())
        before = os.path.getsize(debug.log_path())
        for _ in range(5):
            debug.alert("repeats", key="repeat-me")
        self.assertGreater(
            os.path.getsize(debug.log_path()), before,
            "suppressed alerts were not recorded, so the log cannot say "
            "how often the condition fired")


class ReportUnlistedShowsOneStatusLineTest(unittest.TestCase):
    """`library.report_unlisted`: one status line at the end of six callers; none when all saved"""

    def setUp(self):
        from amaze.utils import rc_calls
        self.lines = []
        self.shown = []
        self.addCleanup(debug.set_ui, debug._ui)
        debug.set_ui(rc_calls.HoudiniUI)

    def _ui(self):
        return types.SimpleNamespace(
            setStatusMessage=lambda text, *a, **k: self.lines.append(text),
            displayMessage=lambda text, *a, **k: self.shown.append(text),
        )

    def _report_unlisted(self, names, **kwargs):
        from amaze.core import library as library_mod
        with mock.patch.object(hou, "ui", self._ui(), create=True):
            library_mod.report_unlisted(names, **kwargs)
        self.assertEqual([], self.shown, "the status line opened a dialog")
        return self.lines

    def test_no_status_line_when_every_record_is_saved(self):
        """The empty check: without it a batch with no failure ends on `0 materials were added`."""
        self.assertEqual([], self._report_unlisted([]))

    def test_one_added_row_is_named(self):
        lines = self._report_unlisted(["Rust"])
        self.assertEqual(1, len(lines), lines)
        self.assertIn('"Rust" was added, but the library could not be saved.', lines[0])

    def test_several_added_rows_are_counted_not_named(self):
        lines = self._report_unlisted(["Rust", "Chrome", "Oak"])
        self.assertEqual(1, len(lines), "a batch wrote more than one line: %r" % lines)
        self.assertIn("3 materials were added, but the library could not be saved.", lines[0])

    def test_one_updated_row_is_reported_as_updated(self):
        lines = self._report_unlisted(["Rust"], updated=True)
        self.assertIn('"Rust" was updated, but the library could not be saved.', lines[0])

    def test_several_updated_rows_are_reported_as_updated(self):
        lines = self._report_unlisted(["Rust", "Chrome"], updated=True)
        self.assertIn("2 materials were updated, but the library could not be saved.", lines[0])


class AnOnlineImportReportsUnlistedRecordsLast(unittest.TestCase):
    """A batch collects the records the library could not save and shows one line, after all else"""

    class _Panel:
        _online_download_active = False

        def __init__(self):
            self.material_model = types.SimpleNamespace(assets=())
            self.landed = []

        def render_new_thumbnails(self, held):
            self.landed.append(held)

    def _batch(self, answers):
        """`import_records` on len(answers) records; `import_material` returns each (ok, reason)."""
        from amaze.panel import online_import as online_import_mod

        class StubImport(online_import_mod.OnlineImport):
            def import_material(self, record, on_progress=None, **kwargs):
                return answers[record]

        panel = self._Panel()
        with mock.patch.object(hou, "ui", types.SimpleNamespace(
                setStatusMessage=lambda text, *a, **k: self.lines.append(text),
                displayMessage=lambda text, *a, **k: self.shown.append(
                    "\n\n".join(filter(None, (text, k.get("details")))))),    # the list is passed in `details`
                create=True):
            StubImport(panel).import_records(list(answers))
        return panel

    def setUp(self):
        from amaze.utils import rc_calls
        self.lines = []
        self.shown = []
        self.addCleanup(debug.set_ui, debug._ui)
        debug.set_ui(rc_calls.HoudiniUI)

    def test_an_imported_but_unlisted_record_is_named_and_is_no_failure(self):
        from amaze.core import library as library_mod
        self._batch({"Rust": (True, library_mod.ListNotSaved("Rust"))})
        self.assertEqual([], self.shown, "an unlisted record opened the failure dialog")
        self.assertEqual(1, len(self.lines), self.lines)
        self.assertIn('"Rust" was added, but the library could not be saved.', self.lines[0])

    def test_a_batch_counts_only_the_records_its_list_did_not_save(self):
        from amaze.core import library as library_mod
        self._batch({"Rust": (True, library_mod.ListNotSaved("Rust")),
                     "Chrome": (True, ""),
                     "Oak": (True, library_mod.ListNotSaved("Oak"))})
        self.assertEqual(1, len(self.lines), self.lines)
        self.assertIn("2 materials were added", self.lines[0])

    def test_a_batch_that_all_saved_writes_no_status_line(self):
        self._batch({"Rust": (True, ""), "Chrome": (True, "")})
        self.assertEqual([], self.lines, "a clean batch wrote the status line anyway")

    def test_a_real_failure_still_opens_its_dialog_and_is_not_a_status_line(self):
        self._batch({"Rust": (False, "the fetch died")})
        self.assertEqual([], self.lines, "a failure was reported as merely unlisted")
        self.assertEqual(1, len(self.shown), self.shown)
        self.assertIn("the fetch died", self.shown[0])


class DebugRefuseReportsGestureFailuresTest(unittest.TestCase):
    """`debug.refuse`: a wrong target on the status line, damage in a dialog. ▸p/refuse-vs-alert"""

    def setUp(self):
        from amaze.utils import rc_calls
        self.lines = []
        self.shown = []
        self.printed = []
        self.addCleanup(debug.set_ui, debug._ui)
        debug.set_ui(rc_calls.HoudiniUI)    # what the pane and every shelf tool pass to `set_ui`

    def _ui(self):
        """Both calls, so a wrong branch fills the wrong list instead of raising an AttributeError."""
        return types.SimpleNamespace(
            setStatusMessage=lambda text, *a, **k: self.lines.append(text),
            displayMessage=lambda text, *a, **k: self.shown.append(text),
        )

    def _not_windows(self):
        """The fallback prints on macOS and Linux only; Windows has its own test below."""
        return mock.patch.object(hostos, "is_windows", lambda: False)

    def _fire_deferred(self, singleShot):
        """Run what the dialog branch deferred."""
        for call in singleShot.call_args_list:
            call.args[1]()

    def test_a_wrong_target_goes_to_the_status_line_every_time(self):
        """Starts with `Amaze: `, and is never de-duplicated the way an alert is."""
        with mock.patch.object(hou, "ui", self._ui(), create=True):
            for _ in range(3):
                debug.refuse("that node has no file parameter")
        self.assertEqual([], self.shown,
                         "a wrong-target refusal opened a dialog")
        self.assertEqual(3, len(self.lines),
                         "the refusal was de-duplicated like an alert, so "
                         "a repeated action looked like it succeeded")
        for text in self.lines:
            self.assertTrue(text.startswith("Amaze: "),
                            "the status line does not start with `Amaze: `: "
                            "%r" % text)
            self.assertIn("that node has no file parameter", text)

    def test_a_wrong_target_is_information_not_a_warning(self):
        """Houdini prints `Warning:` before a Warning line; a missed drop is only information."""
        severities = []
        ui = types.SimpleNamespace(
            setStatusMessage=lambda text, *a, **k: severities.append(k.get("severity")),
            displayMessage=lambda text, *a, **k: None)
        with mock.patch.object(hou, "ui", ui, create=True):
            debug.refuse("The action was canceled.")
        self.assertEqual([hou.severityType.Message], severities)

    def test_damage_opens_a_dialog_DEFERRED_past_the_release_click(self):
        """Never the status line, which the next write erases."""
        with mock.patch.object(hou, "ui", self._ui(), create=True), \
                mock.patch.object(QtCore.QTimer, "singleShot") as later:
            debug.refuse(debug.Damage('"Rust": asset file is missing.'))
            self.assertEqual(
                [], self.shown,
                "the dialog opened INSIDE the release handler, where it "
                "receives the drag's own release click")
            self.assertEqual(1, later.call_count)
            self._fire_deferred(later)
        self.assertEqual([], self.lines,
                         "library damage went to the status line, which "
                         "the next write erases")
        self.assertEqual(['"Rust": asset file is missing.'], self.shown)

    def test_the_deferred_dialog_waits_while_amaze_is_still_at_work(self):
        """The queued dialog must not open inside Houdini's event loop. ▸p/deferred-ui-at-top-level"""
        with mock.patch.object(hou, "ui", self._ui(), create=True):
            debug.refuse(debug.Damage('"Rust": asset file is missing.'))

            def pump():
                QtWidgets.QApplication.processEvents()    # Houdini's Esc check inside createNode
                self.assertEqual([], self.shown, "the dialog opened inside Amaze's own work")

            test_support.call_as_amaze(pump)
            test_support.settle(lambda: self.shown)
        self.assertEqual(['"Rust": asset file is missing.'], self.shown,
                         "the dialog did not open once the event loop was idle")

    def test_without_set_ui_the_log_only_prints(self):
        """The log shows messages in Houdini only through the object given to `set_ui`."""
        debug.set_ui(None)
        with mock.patch.object(hou, "ui", self._ui(), create=True), self._not_windows(), \
                mock.patch("builtins.print", self.printed.append):
            debug.refuse("no ramp here")
            debug.refuse(debug.Damage("gone"))
        self.assertEqual(([], []), (self.lines, self.shown),
                         "the log called Houdini's UI with nothing handed over")
        self.assertEqual(2, len(self.printed))

    def test_headless_prints_it_and_does_not_raise(self):
        self.assertFalse(hasattr(hou, "ui"),
                         "this host HAS a ui, so the fallback is untested")
        with self._not_windows(), mock.patch("builtins.print", self.printed.append):
            shown = debug.refuse("no ramp here")
            damaged = debug.refuse(debug.Damage("gone"))
        self.assertTrue(shown and damaged,
                        "a headless refusal returned that it showed nothing")
        self.assertEqual(2, len(self.printed))


    def test_on_windows_the_fallback_prints_nothing(self):
        """A print opens the Windows Console; alert, refuse and note skip it. ▸r/platform-files"""
        debug.set_ui(None)
        self.addCleanup(debug._alerted.clear)
        with mock.patch.object(hostos, "is_windows", lambda: True), \
                mock.patch("builtins.print", self.printed.append):
            debug.note("noted")
            debug.alert("windows alert", key="windows-alert-fallback")
            debug.refuse("no ramp here")
            debug.refuse(debug.Damage("gone"))
        self.assertEqual([], self.printed, "a fallback printed on Windows")

class TheImportFunctionsMarkTheirFailureReasonsTest(unittest.TestCase):
    """Every literal refusal the import functions in nodes.py return, classified. ▸p/refuse-vs-alert"""

    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    FUNCTIONS = ("_payload_or_refusal", "_import_asset_to_scene_inner",
                 "_import_cop_asset_inner", "_load_saved")

    DAMAGE = {    # opening words -> library damaged? A forwarded reason keeps the marking of its source
        '"%s": asset file is missing on disk.': True,
        '"%s": %s.': True,    # the Node import's empty or unreadable file, its reason inserted
        '"%s" cannot be imported: its id is not a usable file': True,
        '"%s" cannot be imported: its files resolve to': True,
        '"%s" cannot be imported: its material file is': True,
        '"%s" cannot be imported: its material file could': True,
        '"%s" has an unrecognised renderer': True,
        '"%s": failed to load into': True,
        '"%s": failed to load the saved network': True,
        '"%s" needs the "%s" node type, which is not': False,
        '"%s" could not be imported - a node type in it is': False,
        '"%s" holds %s nodes and a %s network cannot hold': False,
        '"%s" was loaded but could not be placed': False,
        '"%s": could not create a %s node in the current': False,
        "cannot import here: %s": False,
    }

    @staticmethod
    def _sentence(expr):
        """The literal a refusal is built from, or "" when it forwards one."""
        while isinstance(expr, ast.BinOp):
            expr = expr.left
        if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
            return expr.value
        return ""

    def _failure_reasons_in_nodes(self):
        """{sentence: marked} for every literal refusal the FUNCTIONS return."""
        with open(os.path.join(self.ROOT, "render", "nodes.py"),
                  encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        found = {}
        for func in ast.walk(tree):
            if not (isinstance(func, ast.FunctionDef)
                    and func.name in self.FUNCTIONS):
                continue
            for node in ast.walk(func):
                if not (isinstance(node, ast.Return)
                        and isinstance(node.value, ast.Tuple)
                        and len(node.value.elts) >= 2):
                    continue
                payload = node.value.elts[1]
                marked = (isinstance(payload, ast.Call)
                          and isinstance(payload.func, ast.Attribute)
                          and payload.func.attr == "Damage")
                inner = payload.args[0] if marked else payload
                sentence = self._sentence(inner)
                if sentence:
                    found[sentence] = marked
        return found

    def test_each_sentence_is_marked_with_its_severity(self):
        """Fails, and never passes on nothing found, when a sentence is reworded or moved."""
        found = self._failure_reasons_in_nodes()
        missing = [opening for opening in self.DAMAGE
                   if not any(s.startswith(opening) for s in found)]
        self.assertEqual(
            [], missing,
            "refusal(s) this test classifies are no longer returned by %s "
            "- update their keys in the commit that moved them, never drop "
            "the entry:\n  %s" % (", ".join(self.FUNCTIONS),
                                  "\n  ".join(missing)))
        wrong = []
        for sentence, marked in sorted(found.items()):
            for opening, damage in self.DAMAGE.items():
                if sentence.startswith(opening):
                    if marked != damage:
                        wrong.append(
                            "%s: marked=%s, should be %s"
                            % (sentence[:60], marked, damage))
                    break
            else:
                wrong.append("%s: NEW refusal, classify it here"
                             % sentence[:60])
        self.assertEqual(
            [], wrong,
            "the Damage marking in nodes.py no longer matches DAMAGE - a damage "
            "sentence left unmarked is shown on the status line, which "
            "the next write erases, and a wrong-target sentence marked opens "
            "a dialog during the drag:\n  " + "\n  ".join(wrong))


class NoReleaseHandlerOpensAModalInline(unittest.TestCase):
    """A release handler calls `debug.refuse`: a modal in a release gets its click. ▸p/refuse-vs-alert"""

    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    MODALS = {"displayMessage", "displayConfirmation", "displayCustomConfirmation", "readInput",
              "readMultiInput", "selectFromList", "selectFile", "selectColor", "selectNode"}
    BOX_MODALS = {"information", "warning", "critical", "question"}    # on QMessageBox
    PANEL_RELEASES = ("assign_category_active", "move_files_active")    # the panel's own drop calls
    REACHED = ("material_lop_viewport_drop", "assign_material_to_obj", "_import_material_builder",
               "import_geo_in_context")    # the functions that once opened one
    HELPERS = {"drop_placement": ("panel/drop_placement.py", "DropPlacement"),    # the objects the panel holds
               "tile_capture": ("panel/tile_capture.py", "TileCapture"),
               "online_import": ("panel/online_import.py", "OnlineImport"),
               "package_import": ("panel/package_import.py", "PackageImport")}

    def _methods(self, relative, only=None) -> dict:
        """{name: [def]} for the methods of one source file, of class `only` when given."""
        with open(os.path.join(self.ROOT, *relative.split("/")), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        found = {}
        for cls in ast.walk(tree):
            if isinstance(cls, ast.ClassDef) and only in (None, cls.name):
                for item in cls.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        found.setdefault(item.name, []).append(item)
        return found

    @staticmethod
    def _release_handlers() -> set:
        """Every handler a section declares for a release, read off the live DropRules."""
        from amaze.panel import sections
        handlers = set()
        for cls in sections.SECTION_CLASSES + (sections.OnlineContext,):
            for rule in [cls.DROP] + list(cls.DROP_BY_KIND.values()):
                if rule is not None:
                    handlers.update(v for v in (rule.on_node, rule.on_space, rule.resolve)
                                    if v)
        return handlers

    def test_no_release_handler_reaches_a_modal(self):
        own = {"section": self._methods("panel/sections.py"),
               "panel": self._methods("panel/panel.py", "AmazePanel")}
        own.update((held, self._methods(*where)) for held, where in self.HELPERS.items())
        stack = [("section", handler, handler) for handler in sorted(self._release_handlers())]
        stack += [("panel", handler, handler) for handler in self.PANEL_RELEASES]
        seen, offenders = set(), []
        while stack:
            side, name, path = stack.pop()
            if (side, name) in seen:
                continue
            seen.add((side, name))
            for function in own[side].get(name, ()):
                for node in ast.walk(function):
                    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                        continue
                    owner, called = ast.unparse(node.func.value), node.func.attr
                    head, _dot, held = owner.rpartition(".")
                    if called in self.MODALS or (
                            called in self.BOX_MODALS and owner.endswith("QMessageBox")):
                        offenders.append("%s: %s, line %d" % (path, called, node.lineno))
                    elif owner == "self":
                        stack.append((side, called, path + " > " + called))
                    elif owner in ("panel", "self.panel"):
                        stack.append(("panel", called, path + " > " + called))
                    elif held in self.HELPERS and head in ("self", "panel", "self.panel"):
                        stack.append((held, called, path + " > " + called))
                    elif owner in ("context", "section"):
                        stack.append(("section", called, path + " > " + called))
        reached = {name for _side, name in seen}
        self.assertEqual([], [name for name in self.REACHED if name not in reached],
                         "premise: the walk no longer reaches these functions - update REACHED")
        self.assertEqual(
            [], offenders,
            "a release handler opens a modal inline, where it takes the drag's own "
            "release click - return the reason to debug.refuse:\n  "
            + "\n  ".join(offenders))


class AFailedReleaseIsReportedThroughDebugRefuse(unittest.TestCase):
    """Two import paths run for real: nothing opens inside the release; the reason goes to `refuse`."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def setUp(self):
        from amaze.utils import rc_calls
        self.shown, self.lines = [], []
        self.addCleanup(debug.set_ui, debug._ui)
        debug.set_ui(rc_calls.HoudiniUI)
        ui = types.SimpleNamespace(
            displayMessage=lambda text, *a, **k: self.shown.append(text),
            setStatusMessage=lambda text, *a, **k: self.lines.append(text))
        for patcher in (mock.patch.object(hou, "ui", ui, create=True),
                        mock.patch.object(QtCore.QTimer, "singleShot")):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.later = QtCore.QTimer.singleShot

    def test_a_scene_that_will_not_open_is_reported_after_the_release(self):
        """`open_hip_scene` on a scene file, with `hou.hipFile.load` failing."""
        from amaze.core import locations
        panel = self.panel
        panel.section_tabs.setChecked("file")
        QtWidgets.QApplication.processEvents()
        proxy = panel.thumblist.model()
        kind, path_role = panel.file_files_model.KindRole, panel.file_files_model.PathRole
        row = next((r for r in range(proxy.rowCount())
                    if proxy.index(r, 0).data(kind) == locations.KIND_HIP), None)
        self.assertIsNotNone(row, "premise: the fixture folder lists no scene")
        failed = mock.Mock(side_effect=hou.OperationFailed("the file is damaged"))
        self.later.reset_mock()    # the section switch defers work of its own
        with mock.patch.object(hou.hipFile, "load", failed):
            panel.sections["file"].open_hip_scene(proxy.index(row, 0))
        self.assertEqual(1, failed.call_count, "premise: the load was never called")
        self.assertEqual([], self.shown, "the failed open showed a modal inside the release")
        self.assertEqual(1, self.later.call_count, "the failed open was not deferred to a dialog")
        self.later.call_args.args[1]()    # the call `debug.refuse` deferred until Qt is idle
        self.assertEqual(1, len(self.shown))
        self.assertIn(proxy.index(row, 0).data(path_role), self.shown[0])

    def test_a_network_that_takes_no_geometry_is_shown_on_the_status_line(self):
        """`import_geo_in_context` where node creation fails: a wrong target, never a dialog."""
        def refuse(*_args, **_kwargs):
            raise hou.OperationFailed("Cannot create a node inside a locked asset")
        network = types.SimpleNamespace(
            childTypeCategory=lambda: types.SimpleNamespace(name=lambda: "Object"),
            createNode=refuse)
        made = self.panel.drop_placement.import_geo_in_context("/nowhere/rock.bgeo.sc", network)
        self.assertIsNone(made)
        self.assertEqual(([], 0), (self.shown, self.later.call_count),
                         "a network refusing the import opened a dialog")
        self.assertEqual(1, len(self.lines), "the refusal was not shown on the status line")
        self.assertIn("rock.bgeo.sc", self.lines[0])


class TheTenSitesAreConvertedTest(unittest.TestCase):
    """Source scan: every user alert is raised through alert() or the registry. ▸o/debug-engine"""

    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    EXPECTED = {    # file -> conditions; empty: moved to the registry ▸p/source-derived-tests
        os.path.join("core", "gradient_library.py"): (
            "colors-not-saved",),    # the trailing comma is required: a bare string is iterated one character at a time
        os.path.join("core", "library_db.py"): ("database-%s-%s-%s", "database-write-failed-%s",
                                                "shrunk-%s-%s"),
        os.path.join("core", "tile_icons.py"): ("icons-not-saved",),
        os.path.join("core", "notes.py"): (),
        os.path.join("core", "matx_sources.py"): (
            "online-unsafe-archive-paths",),
    }

    def test_a_read_only_database_message_names_the_check(self):
        """Only library_db.py decides a database is read-only; its messages point at the check."""
        from amaze import messages
        for text in (messages.DATABASE_CORRUPT_READ_ONLY, messages.DATABASE_MISSING_READ_ONLY,
                     messages.DATABASE_SHRUNK):
            self.assertIn("Check in Preferences ▸ Library", text,
                          "a database the user cannot write says nothing of how to get it back")
        source = open(os.path.join(self.ROOT, "core", "library_db.py"), encoding="utf-8").read()
        for name in ("DATABASE_CORRUPT_READ_ONLY", "DATABASE_MISSING_READ_ONLY",
                     "LIBRARY_FORMAT_AHEAD_READ_ONLY", "DATABASE_SHRUNK", "LIBRARY_WRITE_FAILED"):
            self.assertIn("messages." + name, source,
                          "%s is no longer used by library_db.py, which checks each database" % name)

    def test_every_condition_is_raised_through_alert(self):
        missing = []
        for rel, keys in self.EXPECTED.items():
            with open(os.path.join(self.ROOT, rel), encoding="utf-8") as fh:
                src = fh.read()
            for key in keys:
                if 'key="%s"' % key not in src:
                    missing.append("%s: %s" % (rel, key))
        self.assertEqual([], missing,
                         "condition(s) no longer raised: %s" % missing)


class EveryEntryPointCallsSetUi(unittest.TestCase):
    """Houdini shows the log's messages only after `set_ui`; every entry point calls it first."""

    REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))))

    def test_every_shelf_tool_that_imports_amaze_calls_set_ui(self):
        """In its script, or by the rc_calls function the script calls, run here with no screen."""
        import re
        import xml.etree.ElementTree as ET
        from amaze.utils import rc_calls
        self.assertFalse(hasattr(hou, "ui"), "premise: a screen would run the tools for real")
        self.addCleanup(debug.set_ui, debug._ui)
        root = ET.parse(os.path.join(self.REPO, "toolbar", "Amaze.shelf")).getroot()
        missing = []
        for tool in root.findall("tool"):
            script = tool.find("script").text
            if "from amaze" not in script or "rc_calls.start()" in script:
                continue
            for name in re.findall(r"\brc_calls\.(\w+)\(", script):
                if not hasattr(rc_calls, name):
                    continue
                debug.set_ui(None)
                getattr(rc_calls, name)()    # with no screen each stops after its prologue
                if debug._ui is not rc_calls.HoudiniUI:
                    missing.append("%s (%s)" % (tool.get("name"), name))
        self.assertEqual([], missing, "these tools' alerts would print instead of showing")

    def test_the_pane_calls_set_ui_before_the_log_starts(self):
        import inspect
        from amaze.panel import panel
        source = inspect.getsource(panel.AmazePanel.__init__)
        self.assertIn("rc_calls.start()", source)
        self.assertLess(source.index("rc_calls.start()"), source.index("debug.install()"),
                        "the session header is written before `rc_calls.start()` sets up the log")

    def test_save_to_amaze_calls_start(self):
        import inspect
        from amaze.utils import rc_calls
        self.assertIn("start()", inspect.getsource(rc_calls.save))


class AHeldDatabaseIsNeverReportedCorrupt(unittest.TestCase):
    """A database that is there but cannot be opened is read-only for now, never reported corrupt."""

    def test_held_is_read_only_not_alerted_and_checked_again(self):
        from amaze.core import guard, library_db, library_files
        prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        path = os.path.join(prefs.dir, library_files.MATERIALS)
        with test_support.refused_at_open(path), test_support.captured_log() as log:
            held = library_db.document(prefs, library_files.MATERIALS)
            self.assertEqual(guard.HELD, held.verdict, "premise: the file read as something else")
            self.assertFalse(library_db.accepts(prefs, library_files.MATERIALS),
                             "a database that cannot be opened takes changes")
        self.assertEqual([], log.messages("alert"), "a held database was alerted about")
        library_db.refresh(prefs)
        self.assertEqual(guard.FINE, library_db.document(prefs, library_files.MATERIALS).verdict,
                         "the database was not checked again once it could be opened")

    def test_the_next_change_reads_it_again_with_no_refresh(self):
        from amaze.core import guard, library_db, library_files
        prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        path = os.path.join(prefs.dir, library_files.MATERIALS)
        held = library_db.document(prefs, library_files.MATERIALS)
        rows = set(held.table("assets"))
        with test_support.refused_at_open(path):
            held.refresh()
            self.assertEqual((guard.HELD, False), (held.verdict, held.writable),
                             "premise: the file read as something else")
        self.assertTrue(library_db.accepts(prefs, library_files.MATERIALS),
                        "a database that opens again stays read-only until Preferences is opened")
        self.assertEqual(rows, set(held.table("assets")))
        self.assertTrue(held.put("assets", "ZZ9", {"id": "ZZ9", "name": "after"}))
        library_db.flush(prefs)
        again = guard.Guard(prefs.dir).read(library_files.MATERIALS).document
        self.assertIn("ZZ9", again["assets"], "the change made after it opened was not saved")


class APendingChangeKeepsItsUser(unittest.TestCase):
    """A change waiting for the save timer is saved as the user who made it, in its own library."""

    def test_a_switch_to_another_library_and_user_does_not_save_it_as_theirs(self):
        import shutil
        from amaze.core import documents, guard, library_db, library_files
        prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        first, anna = prefs.dir, prefs.library_user
        other = test_support.scratch_dir("amaze_other_library_")
        self.addCleanup(shutil.rmtree, other, True)
        library_db.set_scheduler(lambda: None)    # a panel's timer that has not fired yet
        held = library_db.document(prefs, library_files.MATERIALS)
        asset = sorted(held.table("assets"))[0]
        self.assertTrue(held.put_mine("favorites", asset, True))
        peer = documents.Library(first, "peer").document(library_files.MATERIALS)
        peer.put("assets", "PEER1", {"id": "PEER1", "name": "theirs"})
        self.assertTrue(peer.save())
        prefs.library_user, prefs.dir = "someone-else", other
        saved = library_db.flush()
        self.assertTrue(saved[library_files.MATERIALS])
        stored = guard.Guard(first).read(library_files.MATERIALS).document
        self.assertTrue(stored["favorites"].get(anna, {}).get(asset),
                        "the favorite made before the switch was dropped or saved as another user")
        self.assertNotIn("someone-else", stored["favorites"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
