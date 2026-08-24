"""The sidebar's MANUAL order: the STORED list is the order, "_All" pinned to row 0."""

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
    """A real Categories over a fixture library, its list set IN PLACE."""
    prefs = test_support.fixture_prefs(testcase)
    test_support.reset_database_singletons()
    testcase.addCleanup(test_support.reset_database_singletons)
    model = category.Categories(preferences=prefs)
    model._categories[:] = list(entries)
    return model


class SortByNameTest(unittest.TestCase):
    """The menu's one-off Sort by name: everything below All lands alphabetically, saved at once - and the user drags on from there, so it is not a mode."""

    def test_the_categories_land_alphabetically_below_All(self):
        model = _categories(self, ["_All", "b", "Zed", "a"])
        with mock.patch.object(model, "save") as save:
            model.sort_categories()
        self.assertEqual(["_All", "a", "b", "Zed"], model._categories)
        save.assert_called_once_with()

    def test_an_already_sorted_list_saves_nothing(self):
        model = _categories(self, ["_All", "a", "b"])
        with mock.patch.object(model, "save") as save:
            model.sort_categories()
        self.assertEqual(["_All", "a", "b"], model._categories)
        save.assert_not_called()

    def test_All_keeps_row_zero_even_under_a_name_that_beats_it(self):
        """The head/rest split, pinned: `abc` sorts before `All`, so a plain sorted() over the whole list would push the All row out of row 0 - the one place the database loader and move_category both refuse to allow."""
        model = _categories(self, ["_All", "abc", "b"])
        with mock.patch.object(model, "save"):
            model.sort_categories()
        self.assertEqual(["_All", "abc", "b"], model._categories)

    def test_a_category_sorts_where_its_LABEL_reads(self):
        """The sidebar strips a leading underscore for display, so `_WIP` reads WIP and belongs after Apple - sorting the stored spelling put it first."""
        model = _categories(self, ["_All", "Apple", "_WIP"])
        with mock.patch.object(model, "save"):
            model.sort_categories()
        self.assertEqual(["_All", "Apple", "_WIP"], model._categories)

    def test_a_non_string_row_does_not_raise(self):
        """`_categories` comes straight off library.json and normalize_categories only runs from Clean Library, so the sort must survive what the file can hold."""
        model = _categories(self, ["_All", "b", 3])
        with mock.patch.object(model, "save"):
            model.sort_categories()
        self.assertEqual(["_All", 3, "b"], model._categories)


class TheSortVerbKeepsTheSidebarStandingSomewhere(unittest.TestCase):
    """Sort by name lands through a model RESET, which clears the selection and the current index with signals blocked - so the verb has to put the user back where they were, or the grid stays filtered with nothing highlighted."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def _section(self):
        section = self.panel.sections["material"]
        _proxy, source = section._sidebar_categories()
        self.assertIsNotNone(source, "no Categories behind the sidebar")
        return section, source

    def test_the_menu_verb_sorts_through_the_live_model(self):
        section, source = self._section()
        source._categories[:] = ["_All", "b", "a"]
        section.menu_sort_categories((), None)
        self.assertEqual(["_All", "a", "b"], source._categories)

    def test_the_row_you_were_standing_on_stays_under_you(self):
        section, source = self._section()
        source._categories[:] = ["_All", "b", "a"]
        source.layoutChanged.emit()
        cat_list = self.panel.cat_list
        proxy = cat_list.model()
        standing = None
        for row in range(proxy.rowCount()):
            if proxy.index(row, 0).data() == "b":
                standing = proxy.index(row, 0)
        self.assertIsNotNone(standing, "the fixture sidebar has no b row")
        cat_list.setCurrentIndex(standing)
        cat_list.selectionModel().select(
            standing,
            QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect)

        section.menu_sort_categories((), None)

        self.assertTrue(
            cat_list.selectionModel().selectedIndexes(),
            "the sort left the sidebar with nothing selected while the "
            "grid kept its filter")
        self.assertEqual(
            "b", cat_list.currentIndex().data(),
            "the sort moved the user off the category they were "
            "standing in")


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
        """beginMoveRows/endMoveRows, not a reset and not silence. ▸r/press-gestures"""
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
        """The gesture saves ONCE on release: the move neither rebinds nor writes."""
        model = _categories(self, ["_All", "a", "b"])
        held = model._categories
        with mock.patch.object(model, "save") as save:
            self.assertTrue(model.move_category(1, 2))
        self.assertIs(held, model._categories, "the move rebound the list")
        save.assert_not_called()

    def test_the_saved_order_survives_a_reload(self):
        """What a save writes is what the next session shows."""
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
    """Every category-bearing database keeps `_All` present AND first."""

    def _rewrite(self, prefs, filename, categories):
        """Plant a category order on disk, seeding at the CURRENT schema."""
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
        """library.json is no longer exempt from the normalize."""
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
        """A pre-convention plain "All" becomes the marker, never a second row."""
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
    """Source-derived: the four sidebar proxies are built UNSORTED in panel.py."""

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
        # A wrapped call is the same call: the needles match whitespace-free.
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
            "self.save_dialog_category_model.sort(0)", self.flat_source,
            "the dropdown's alphabetical sort was removed - that one "
            "is deliberate (typing against an alphabetical list)")


class ReorderContractTest(unittest.TestCase):
    """Every section answers the reorder contract; the gesture asks the CONTEXT."""

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
    """The contract the gesture speaks, recorded - the state machine is under test."""

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
    """The press-hold state machine, replayed headlessly; no test sleeps."""

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
        """A save that changes nothing still spends a write."""
        _model, _proxy, view, section, controller = self._harness()
        pos = self._press(view, controller, 1)
        controller._hold_fired()
        self._release(view, controller, pos)
        self.assertEqual(0, section.commits)

    def test_a_reset_returns_every_field_to_its_born_state(self):
        """The blank slate is written ONCE: a field one of the pair misses reddens here."""
        _model, _proxy, view, _section, controller = self._harness()
        born = dict(vars(controller))
        self._press(view, controller, 1)
        controller._hold_fired()
        self._move(view, controller, self._row_center(view, 3))
        controller._reset()
        self.assertEqual(born, dict(vars(controller)))

    def test_a_reset_lets_the_closed_hand_cursor_go(self):
        _model, _proxy, view, _section, controller = self._harness()
        self._press(view, controller, 1)
        controller._hold_fired()
        self.assertEqual(QtCore.Qt.CursorShape.ClosedHandCursor,
                         view.viewport().cursor().shape())
        controller._reset()
        self.assertNotEqual(QtCore.Qt.CursorShape.ClosedHandCursor,
                            view.viewport().cursor().shape())

    def test_a_section_that_does_not_reorder_never_arms(self):
        _model, _proxy, view, section, controller = self._harness()
        section.reorders_sidebar = False
        self._press(view, controller, 1)
        self.assertFalse(controller._hold_timer.isActive())


class FolderOrderTest(unittest.TestCase):
    """The File sidebar speaks the same gesture; a move goes through `locations`."""

    def _base(self):
        """A realpath'd scratch root - the location store speaks resolved paths."""
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
        """A second Prefs over the same settings.json - the next session."""
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
        """The door NORMALISES what it is handed, like every sibling. ▸p/one-file-one-table"""
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
        """Red for the plausible wrong fix: normalising the CALLER alone. ▸p/one-file-one-table"""
        from amaze.core import locations
        from amaze.helpers import hostos
        base = self._base()
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
