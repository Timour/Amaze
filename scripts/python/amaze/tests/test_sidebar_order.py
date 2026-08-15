"""The sidebar's MANUAL order - one engine for every section.

The sections used to disagree three ways about the same list: the
asset sidebars sorted by name through their proxy (and "_All" loses a
name sort to any digit, so a category called "2" sat ABOVE All), Color
showed its stored list unsorted, and File was a third shape again.
The engine now is: the STORED list order is the order, "_All" is
pinned to row 0 by the database, and a press-hold on a row moves it.

What is pinned here:

* `Categories.move_category` - the one row-move, in place, refusing
  All and anything above it;
* `_normalize_all_category` - runs for EVERY category-bearing
  database (library.json included) and MOVES a stray `_All` to the
  front rather than only inserting a missing one;
* the sidebar proxy presents STORED order - no sort() anywhere on a
  sidebar proxy in panel.py, while the save dialog's dropdown keeps
  its alphabetical sort();
* the press-hold gesture's state machine (arm, cancel, fire, move,
  commit once, Esc restores);
* the reorder contract every section answers.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import category, database  # noqa: E402
from amaze.tests import test_support  # noqa: E402


def _categories(testcase, entries):
    """A real Categories over a fixture library, its list set IN PLACE
    (the model aliases the connector's document list - a rebind is the
    erasure test_category.py pins)."""
    prefs = test_support.fixture_prefs(testcase)
    test_support.reset_database_singletons()
    testcase.addCleanup(test_support.reset_database_singletons)
    model = category.Categories(preferences=prefs)
    model._categories[:] = list(entries)
    return model


class MoveCategoryTest(unittest.TestCase):
    """One row-move on the shared model, with All immovable."""

    def test_a_move_down_lands_after_its_target(self):
        model = _categories(self, ["_All", "a", "b", "c"])
        self.assertTrue(model.move_category(1, 3))
        self.assertEqual(["_All", "b", "c", "a"], model._categories)

    def test_a_move_up_lands_on_its_target(self):
        model = _categories(self, ["_All", "a", "b", "c"])
        self.assertTrue(model.move_category(3, 1))
        self.assertEqual(["_All", "c", "a", "b"], model._categories)

    def test_the_move_is_bracketed_by_the_move_signals(self):
        """beginMoveRows/endMoveRows, not a reset and not silence - a
        proxy and the selection follow a MOVE without losing the
        current row; research.md records what an unbracketed row-set
        change does to the native side."""
        model = _categories(self, ["_All", "a", "b"])
        seen = []
        model.rowsAboutToBeMoved.connect(lambda *a: seen.append("about"))
        model.rowsMoved.connect(lambda *a: seen.append("moved"))
        self.assertTrue(model.move_category(1, 2))
        self.assertEqual(["about", "moved"], seen)

    def test_all_cannot_move_and_nothing_moves_above_it(self):
        model = _categories(self, ["_All", "a", "b"])
        self.assertFalse(model.move_category(0, 2), "All itself moved")
        self.assertFalse(model.move_category(2, 0), "a row moved above All")
        self.assertEqual(["_All", "a", "b"], model._categories)

    def test_a_no_op_and_out_of_range_are_refused_silently(self):
        model = _categories(self, ["_All", "a", "b"])
        seen = []
        model.rowsAboutToBeMoved.connect(lambda *a: seen.append("about"))
        self.assertFalse(model.move_category(1, 1))
        self.assertFalse(model.move_category(1, 9))
        self.assertFalse(model.move_category(9, 1))
        self.assertEqual([], seen, "a refused move emitted signals")

    def test_the_move_mutates_in_place_and_does_not_save(self):
        """The list is the connector's own; the gesture saves ONCE on
        release, so the move itself must neither rebind nor write."""
        model = _categories(self, ["_All", "a", "b"])
        held = model._categories
        with mock.patch.object(model, "save") as save:
            self.assertTrue(model.move_category(1, 2))
        self.assertIs(held, model._categories, "the move rebound the list")
        save.assert_not_called()

    def test_the_saved_order_survives_a_reload(self):
        """The stored list IS the manual order - what a save writes is
        what the next session shows."""
        model = _categories(self, ["_All", "a", "b", "c"])
        self.assertTrue(model.move_category(1, 3))
        self.assertTrue(model.save())
        test_support.reset_database_singletons()
        reloaded = category.Categories(preferences=model.preferences)
        self.assertEqual(["_All", "b", "c", "a"], reloaded._categories)


class OrderSnapshotTest(unittest.TestCase):
    """Esc mid-gesture puts the order back exactly."""

    def test_restore_returns_the_snapshot_order_in_place(self):
        model = _categories(self, ["_All", "a", "b", "c"])
        held = model._categories
        snap = model.order_snapshot()
        model.move_category(1, 3)
        model.move_category(2, 1)
        seen = []
        model.modelAboutToBeReset.connect(lambda: seen.append("about"))
        model.modelReset.connect(lambda: seen.append("done"))
        model.restore_order(snap)
        self.assertEqual(["_All", "a", "b", "c"], model._categories)
        self.assertIs(held, model._categories, "restore rebound the list")
        self.assertEqual(["about", "done"], seen,
                         "a row-set replacement without its reset pair")

    def test_the_snapshot_is_a_copy_not_the_live_list(self):
        model = _categories(self, ["_All", "a"])
        snap = model.order_snapshot()
        self.assertIsNot(snap, model._categories)


class AllPinnedByTheDatabaseTest(unittest.TestCase):
    """`_normalize_all_category` is the invariant, not a seeding
    repair: every category-bearing database keeps `_All` present AND
    first. With the name sort gone, a stray `_All` would otherwise
    simply SHOW wherever it sits."""

    def _rewrite(self, prefs, filename, categories):
        """Plant a category order on disk. The fixture library carries
        only the primary; a missing secondary is seeded at the CURRENT
        schema, because a hand-written stamp below it has no migration
        steps left and is refused rather than upgraded."""
        path = os.path.join(prefs.dir, filename)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as handle:
                doc = json.load(handle)
        else:
            doc = {"version": database.SCHEMA_VERSION,
                   "tags": [], "assets": []}
        doc["categories"] = categories
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(doc, handle)

    def _load(self, prefs, filename):
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        return database.DatabaseConnector(filename).load(prefs.dir)

    def test_a_stray_all_moves_to_the_front_of_the_primary(self):
        """library.json was EXEMPT from the normalize - its seeds put
        _All first and the sort hid every stray. The manual order
        unhides them."""
        prefs = test_support.fixture_prefs(self)
        self._rewrite(prefs, "library.json", ["Wood", "_All", "Metal"])
        data = self._load(prefs, "library.json")
        self.assertEqual(["_All", "Wood", "Metal"], data["categories"])

    def test_a_stray_all_moves_to_the_front_of_a_secondary(self):
        prefs = test_support.fixture_prefs(self)
        self._rewrite(prefs, "cops.json", ["X", "_All", "Y"])
        data = self._load(prefs, "cops.json")
        self.assertEqual(["_All", "X", "Y"], data["categories"])

    def test_a_plain_all_is_still_rewritten(self):
        """The original repair stays: a pre-convention plain "All"
        becomes the marker, never a second row."""
        prefs = test_support.fixture_prefs(self)
        self._rewrite(prefs, "cops.json", ["All", "X"])
        data = self._load(prefs, "cops.json")
        self.assertEqual(["_All", "X"], data["categories"])


class SidebarShowsStoredOrderTest(unittest.TestCase):
    """The sidebar proxy PRESENTS, it does not sort."""

    def _proxy(self, entries):
        model = _categories(self, entries)
        proxy = category.CategoriesSidebarProxy()
        proxy.setSourceModel(model)
        proxy.hide_empty = False
        return model, proxy

    def test_the_proxy_presents_the_stored_order(self):
        entries = ["_All", "b", "2", "a"]
        model, proxy = self._proxy(entries)
        shown = [proxy.index(r, 0).data(model.CatSortRole)
                 for r in range(proxy.rowCount())]
        self.assertEqual(entries, shown)

    def test_the_proxy_follows_a_move(self):
        model, proxy = self._proxy(["_All", "a", "b", "c"])
        model.move_category(1, 3)
        shown = [proxy.index(r, 0).data(model.CatSortRole)
                 for r in range(proxy.rowCount())]
        self.assertEqual(["_All", "b", "c", "a"], shown)


class PanelWiresNoSidebarSortTest(unittest.TestCase):
    """The structure test for the wiring: the four sidebar proxies are
    built UNSORTED in panel.py, Color goes through the same proxy class
    as the other three, and the save dialog's dropdown keeps its
    alphabetical sort - the sidebar is where the manual order shows,
    a dropdown you type against stays predictable.

    Source-derived (grep for STRUCTURE, practice.md): the wiring is
    six lines in setup(), and an activate test would need the whole
    panel for what is a construction-time fact.
    """

    SIDEBAR_PROXIES = (
        "category_sorted_model",
        "cop_category_sorted_model",
        "code_category_sorted_model",
        "gradient_category_sorted_model",
    )

    @classmethod
    def setUpClass(cls):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "panel", "panel.py"),
                  encoding="utf-8") as handle:
            cls.panel_source = handle.read()
        # STRUCTURE, not prose: a wrapped call is the same call, so
        # the needles below match with all whitespace removed.
        cls.flat_source = "".join(cls.panel_source.split())

    def test_no_sidebar_proxy_is_sorted_or_sort_roled(self):
        for attr in self.SIDEBAR_PROXIES:
            for call in (".sort(", ".setSortRole(", ".setSortCaseSensitivity("):
                needle = "self.%s%s" % (attr, call)
                self.assertNotIn(
                    needle, self.flat_source,
                    "%s - the sidebar shows STORED order; sorting it "
                    "is the '2 above All' bug coming back" % needle)

    def test_color_goes_through_the_shared_sidebar_proxy(self):
        self.assertIn(
            "self.gradient_category_sorted_model="
            "category.CategoriesSidebarProxy(",
            self.flat_source,
            "Color's sidebar bypasses the shared proxy - the odd one "
            "out is how the sections drifted apart in the first place")
        self.assertIn(
            "self.gradient_category_sorted_model.setSourceModel("
            "self.gradient_categories_model)",
            self.flat_source)

    def test_the_save_dialog_dropdown_keeps_its_sort(self):
        self.assertIn(
            "self.usd_dialog_category_model.sort(0)", self.flat_source,
            "the dropdown's alphabetical sort was removed - that one "
            "is deliberate (typing against an alphabetical list)")


class ReorderContractTest(unittest.TestCase):
    """Every section answers the reorder contract - the gesture asks
    the CONTEXT, never a list of section keys (the sidebar's own
    retired-CATEGORY_SECTIONS lesson)."""

    def test_the_five_sections_reorder_and_online_does_not(self):
        from amaze.panel import sections
        for cls in sections.SECTION_CLASSES:
            self.assertTrue(
                getattr(cls, "reorders_sidebar", False),
                "%s does not answer the reorder gesture" % cls.key)
        self.assertFalse(
            getattr(sections.OnlineContext, "reorders_sidebar", True),
            "the online sources are fixed - nothing to reorder")

    def test_the_contract_methods_exist_on_the_base(self):
        from amaze.panel import sections
        for name in ("sidebar_movable", "move_sidebar_row",
                     "sidebar_order_snapshot", "restore_sidebar_order",
                     "commit_sidebar_order"):
            self.assertTrue(
                callable(getattr(sections.Section, name, None)),
                "Section.%s missing - the gesture has nothing to call"
                % name)


class _RecordingSection:
    """The contract the gesture speaks, recorded - the controller's
    state machine is under test here, not any section's mapping."""

    reorders_sidebar = True

    def __init__(self, model, proxy):
        self.model = model
        self.proxy = proxy
        self.commits = 0
        self.moves = []

    def sidebar_movable(self, index):
        return index.isValid() and index.row() > 0

    def move_sidebar_row(self, index, to_view_row):
        frm = self.proxy.mapToSource(self.proxy.index(index.row(), 0)).row()
        to = self.proxy.mapToSource(self.proxy.index(to_view_row, 0)).row()
        moved = self.model.move_category(frm, to)
        if moved:
            self.moves.append((frm, to))
        return moved

    def sidebar_order_snapshot(self):
        return self.model.order_snapshot()

    def restore_sidebar_order(self, snapshot):
        self.model.restore_order(snapshot)

    def commit_sidebar_order(self):
        self.commits += 1


def _mouse(kind, pos, buttons=QtCore.Qt.MouseButton.LeftButton):
    return QtGui.QMouseEvent(
        kind, QtCore.QPointF(pos), QtCore.QPointF(pos),
        QtCore.QPointF(pos), QtCore.Qt.MouseButton.LeftButton,
        buttons, QtCore.Qt.KeyboardModifier.NoModifier)


class HoldGestureTest(unittest.TestCase):
    """The press-hold state machine, replayed headlessly against a
    real view over the real models. The hold TIME is the platform's
    own (`QApplication.startDragTime`), never a literal in the
    controller; firing is driven directly so no test sleeps."""

    def _harness(self, entries=("_All", "a", "b", "c")):
        from amaze.panel import sidebar

        model = _categories(self, list(entries))
        proxy = category.CategoriesSidebarProxy()
        proxy.setSourceModel(model)
        proxy.hide_empty = False

        view = QtWidgets.QListView()
        self.addCleanup(view.deleteLater)
        view.setModel(proxy)
        view.resize(200, 300)

        section = _RecordingSection(model, proxy)

        class _Panel:
            cat_list = view

            def _section(self):
                return section

        controller = sidebar.SidebarReorder(_Panel())
        return model, proxy, view, section, controller

    def _row_center(self, view, row):
        return view.visualRect(view.model().index(row, 0)).center()

    def _press(self, view, controller, row):
        pos = self._row_center(view, row)
        event = _mouse(QtCore.QEvent.Type.MouseButtonPress, pos)
        controller.eventFilter(view.viewport(), event)
        return pos

    def _move(self, view, controller, pos):
        event = _mouse(QtCore.QEvent.Type.MouseMove, pos)
        return controller.eventFilter(view.viewport(), event)

    def _release(self, view, controller, pos):
        event = _mouse(QtCore.QEvent.Type.MouseButtonRelease, pos,
                       buttons=QtCore.Qt.MouseButton.NoButton)
        return controller.eventFilter(view.viewport(), event)

    def test_the_hold_time_is_the_platforms_own(self):
        _model, _proxy, view, _section, controller = self._harness()
        self._press(view, controller, 1)
        self.assertTrue(controller._hold_timer.isActive())
        self.assertEqual(
            QtWidgets.QApplication.startDragTime(),
            controller._hold_timer.interval())

    def test_a_press_on_all_never_arms(self):
        _model, _proxy, view, _section, controller = self._harness()
        self._press(view, controller, 0)
        self.assertFalse(controller._hold_timer.isActive())

    def test_a_release_before_the_hold_stays_a_click(self):
        model, _proxy, view, section, controller = self._harness()
        pos = self._press(view, controller, 1)
        self._release(view, controller, pos)
        self.assertFalse(controller._hold_timer.isActive())
        self.assertEqual([], section.moves)
        self.assertEqual(0, section.commits)
        self.assertEqual(["_All", "a", "b", "c"], model._categories)

    def test_a_move_past_the_threshold_cancels_the_hold(self):
        _model, _proxy, view, section, controller = self._harness()
        pos = self._press(view, controller, 1)
        distance = QtWidgets.QApplication.startDragDistance() + 2
        away = QtCore.QPoint(pos.x() + distance, pos.y())
        self._move(view, controller, away)
        self.assertFalse(controller._hold_timer.isActive())
        controller._hold_fired()  # a late timer must find nothing armed
        self.assertFalse(controller.reordering())

    def test_the_fired_hold_moves_rows_and_commits_once(self):
        model, _proxy, view, section, controller = self._harness()
        self._press(view, controller, 1)
        controller._hold_fired()
        self.assertTrue(controller.reordering())
        target = self._row_center(view, 3)
        self._move(view, controller, target)
        self.assertEqual(["_All", "b", "c", "a"], model._categories)
        self._release(view, controller, target)
        self.assertFalse(controller.reordering())
        self.assertEqual(1, section.commits)

    def test_nothing_lands_above_all(self):
        model, _proxy, view, section, controller = self._harness()
        self._press(view, controller, 2)
        controller._hold_fired()
        self._move(view, controller, self._row_center(view, 0))
        self.assertEqual(
            "_All", model._categories[0],
            "the drag placed a row above All")
        self._release(view, controller, self._row_center(view, 1))
        self.assertEqual(["_All", "b", "a", "c"], model._categories)

    def test_escape_restores_the_order_and_commits_nothing(self):
        model, _proxy, view, section, controller = self._harness()
        self._press(view, controller, 1)
        controller._hold_fired()
        self._move(view, controller, self._row_center(view, 3))
        self.assertNotEqual(["_All", "a", "b", "c"], model._categories)
        esc = QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress,
                              QtCore.Qt.Key.Key_Escape,
                              QtCore.Qt.KeyboardModifier.NoModifier)
        controller.eventFilter(view, esc)
        self.assertFalse(controller.reordering())
        self.assertEqual(["_All", "a", "b", "c"], model._categories)
        self._release(view, controller, self._row_center(view, 3))
        self.assertEqual(0, section.commits)

    def test_a_release_without_a_move_commits_nothing(self):
        """Holding without dragging anywhere writes nothing - a save
        that changes nothing still spends a write."""
        _model, _proxy, view, section, controller = self._harness()
        pos = self._press(view, controller, 1)
        controller._hold_fired()
        self._release(view, controller, pos)
        self.assertEqual(0, section.commits)

    def test_a_section_that_does_not_reorder_never_arms(self):
        _model, _proxy, view, section, controller = self._harness()
        section.reorders_sidebar = False
        self._press(view, controller, 1)
        self.assertFalse(controller._hold_timer.isActive())


class FolderOrderTest(unittest.TestCase):
    """The File sidebar speaks the same gesture: the ORDER of the
    registered locations is the settings copy's, user-authored now,
    and a move goes through `locations` - the module that owns both
    ends of the copy - never an index assignment into whatever list
    the accessor hands back."""

    def _base(self):
        """A realpath'd scratch root: macOS tempdirs live under the
        /var -> /private/var symlink, and the location store speaks in
        resolved paths - comparing against the literal spelling fails
        on the alias, not on the behaviour."""
        base = os.path.realpath(tempfile.mkdtemp(prefix="amaze_folders_"))
        self.addCleanup(shutil.rmtree, base, True)
        return base

    def _prefs(self, folders):
        prefs = test_support.fixture_prefs(self)
        for path in folders:
            os.makedirs(path, exist_ok=True)
            prefs.add_file_folder(path)
        return prefs

    def _reloaded(self, fixture):
        """A second Prefs over the same settings.json - the next
        session, as `load()` would build it."""
        from amaze.prefs import prefs as prefs_mod
        p = prefs_mod.Prefs()
        p.path = fixture.path
        p.load()
        p.dir = fixture.dir
        return p

    def test_a_move_reorders_registered_paths(self):
        from amaze.core import locations
        base = self._base()
        one, two, three = (os.path.join(base, n) for n in ("1", "2", "3"))
        prefs = self._prefs([one, two, three])
        self.assertTrue(locations.move_registered(prefs, one, 2))
        self.assertEqual([test_support.posix_path(p)
                          for p in (two, three, one)],
                         prefs.file_folders)

    def test_a_move_accepts_ANY_spelling_of_a_registered_path(self):
        """The door NORMALISES what it is handed, like every sibling in
        the module - `set_record`, `relocate_record`, `set_favourite`,
        `record` and `is_favourite` all do it first thing.

        `move_registered` read `registered_paths` (canonical) and then
        compared the caller's `path` RAW, so one legal spelling of a
        registered location answered "not registered" and the move
        returned False without saying why. On Windows that is EVERY
        `os.path.join` spelling, which is how it was found (ROADMAP
        line 17, measured on the parity VM 2026-08-15).

        The red is earned PORTABLY, with a non-normalised spelling
        rather than a native separator: `os.sep` is already `/` here, so
        trusting the Windows run would be trusting the platform to prove
        a contract the code owes on all three.
        """
        from amaze.core import locations
        base = self._base()
        one, two, three = (os.path.join(base, n) for n in ("1", "2", "3"))
        prefs = self._prefs([one, two, three])
        detour = os.path.join(base, "elsewhere", os.pardir, "1")
        self.assertNotEqual(detour, one, "the detour spelling collapsed "
                                         "before the door ever saw it")
        self.assertTrue(locations.move_registered(prefs, detour, 2))
        self.assertEqual([test_support.posix_path(p)
                          for p in (two, three, one)],
                         prefs.file_folders)

    def test_a_move_works_where_the_STORED_spelling_is_not_the_absolute(self):
        """A guard on the REPAIR, not on the original defect - it is
        green either side of the bug above and red for a plausible wrong
        fix, which is the only reason it is worth a line.

        Under home the two spellings of one folder diverge:
        `storage_path_key` shortens to `~/1` while `registered_paths`
        hands back the expanded absolute. Normalising only the CALLER's
        side - the one-line repair ROADMAP line 17 proposed - puts `~/1`
        against a list of absolutes, so every move under home returns
        False while the tempdir cases keep passing and look like proof.
        Both sides are normalised instead, which is what the siblings do.

        `_home_root` is the sanctioned seam: its own docstring says it
        exists so a test can pin home without patching the world.
        """
        from amaze.core import locations
        from amaze.helpers import hostos
        base = self._base()
        # CANONICAL, because the real `_home_root` is
        # `canonical_path_key(expanduser("~"))` - a stand-in spelled the
        # host's way makes `storage_path_key`'s startswith test fail on
        # Windows and the home branch never fires, which is the one
        # thing this test needs to happen.
        with mock.patch.object(hostos, "_home_root",
                               return_value=test_support.posix_path(base)):
            one, two, three = (os.path.join(base, n)
                               for n in ("1", "2", "3"))
            prefs = self._prefs([one, two, three])
            self.assertEqual(
                "~/1", hostos.storage_path_key(one),
                "the home branch never fired, so this proves nothing")
            self.assertTrue(locations.move_registered(prefs, one, 2))
            self.assertEqual([test_support.posix_path(p)
                              for p in (two, three, one)],
                             prefs.file_folders)

    def test_the_move_alone_does_not_save(self):
        from amaze.core import locations
        base = self._base()
        one, two = (os.path.join(base, n) for n in ("1", "2"))
        prefs = self._prefs([one, two])
        with mock.patch.object(prefs, "save") as save:
            self.assertTrue(locations.move_registered(prefs, one, 1))
        save.assert_not_called()

    def test_commit_persists_the_order(self):
        from amaze.core import locations
        base = self._base()
        one, two = (os.path.join(base, n) for n in ("1", "2"))
        prefs = self._prefs([one, two])
        locations.move_registered(prefs, one, 1)
        locations.commit_registered_order(prefs)
        reloaded = self._reloaded(prefs)
        self.assertEqual([test_support.posix_path(p) for p in (two, one)],
                         reloaded.file_folders)

    def test_the_model_move_brackets_and_respects_the_all_row(self):
        from amaze.core import file_library
        base = self._base()
        one, two = (os.path.join(base, n) for n in ("1", "2"))
        prefs = self._prefs([one, two])
        model = file_library.FileFolders(prefs)
        seen = []
        model.rowsAboutToBeMoved.connect(lambda *a: seen.append("about"))
        model.rowsMoved.connect(lambda *a: seen.append("moved"))
        self.assertFalse(model.move_folder(0, 2), "the All row moved")
        self.assertFalse(model.move_folder(1, 0), "a folder moved above All")
        self.assertEqual([], seen)
        self.assertTrue(model.move_folder(1, 2))
        self.assertEqual(["about", "moved"], seen)
        self.assertEqual([test_support.posix_path(p) for p in (two, one)],
                         prefs.file_folders)


if __name__ == "__main__":
    unittest.main()
