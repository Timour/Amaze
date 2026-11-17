"""The sidebar's MANUAL order: the STORED list is the order, "_All" pinned to row 0."""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import category  # noqa: E402
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
    """The one-off Sort by name: everything below All is sorted by name and saved; not a mode."""

    def test_the_categories_are_sorted_alphabetically_below_All(self):
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

    def test_All_keeps_row_zero_even_under_a_name_that_sorts_before_it(self):
        """The head/rest split: `abc` sorts before `All`, yet All must keep row 0."""
        model = _categories(self, ["_All", "abc", "b"])
        with mock.patch.object(model, "save"):
            model.sort_categories()
        self.assertEqual(["_All", "abc", "b"], model._categories)

    def test_a_category_sorts_where_its_LABEL_reads(self):
        """The sidebar shows `_WIP` as WIP, so it sorts after Apple, not by its stored spelling."""
        model = _categories(self, ["_All", "Apple", "_WIP"])
        with mock.patch.object(model, "save"):
            model.sort_categories()
        self.assertEqual(["_All", "Apple", "_WIP"], model._categories)

    def test_a_non_string_row_does_not_raise(self):
        """`_categories` is read raw from materials.json, so the sort accepts whatever it holds."""
        model = _categories(self, ["_All", "b", 3])
        with mock.patch.object(model, "save"):
            model.sort_categories()
        self.assertEqual(["_All", 3, "b"], model._categories)


class TheSortActionRestoresTheCurrentSidebarRow(unittest.TestCase):
    """Sort by name resets the model, clearing the selection; the verb restores the current row."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def _section(self):
        section = self.panel.sections["material"]
        _proxy, source = section._sidebar_categories()
        self.assertIsNotNone(source, "no Categories behind the sidebar")
        return section, source

    def test_the_menu_action_sorts_through_the_live_model(self):
        section, source = self._section()
        source._categories[:] = ["_All", "b", "a"]
        section.menu_sort_categories((), None)
        self.assertEqual(["_All", "a", "b"], source._categories)

    def test_the_current_row_stays_current_after_the_sort(self):
        section, source = self._section()
        source.beginResetModel()    # replacing every row needs a reset pair ▸r/model-contracts
        try:
            source._categories[:] = ["_All", "b", "a"]
        finally:
            source.endResetModel()
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
        self.panel.update_selected_cat()    # as a click does: the selected row sets the grid's filter

        section.menu_sort_categories((), None)

        self.assertTrue(
            cat_list.selectionModel().selectedIndexes(),
            "the sort left the sidebar with nothing selected while the "
            "grid kept its filter")
        self.assertEqual(
            "b", cat_list.currentIndex().data(),
            "the sort changed the current row away from the category "
            "selected before")


class DeletingTheLastOfACategorySelectsAll(unittest.TestCase):
    """Deleting the last asset of a hidden-when-empty category selects All in the sidebar."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))
        cls.panel._on_tab_toggled("material", True)

    def test_the_sidebar_selects_all_and_the_grid_shows_everything(self):
        panel = self.panel
        section = panel.sections["material"]
        proxy, source = section._sidebar_categories()
        source.set_renderer_filter("karma")    # empty categories hide only under a renderer filter
        proxy.hide_empty = True
        panel.refresh_sidebar_categories()
        self.assertTrue(
            panel._select_category("Karma_Mats"),
            "the fixture sidebar has no Karma_Mats row to select")
        model = panel.material_model
        rows = [model.index(row, 0) for row, asset in enumerate(model.assets)
                if "Karma_Mats" in list(asset.categories)]
        self.assertEqual(2, len(rows), "the fixture's Karma_Mats holds two")

        section.delete_rows(rows)

        self.assertIsNone(
            proxy.rowCount() and next(
                (proxy.index(r, 0) for r in range(proxy.rowCount())
                 if proxy.index(r, 0).data() == "Karma_Mats"), None),
            "the emptied category is still shown")
        current = panel.cat_list.currentIndex()
        self.assertTrue(current.isValid(), "the sidebar has no current row")
        self.assertEqual(
            "All", current.data(),
            "the sidebar did not move to All after its category was hidden")
        stored = getattr(panel.material_sorted_model, "_filters", {})
        self.assertNotIn(
            model.CategoryRole, stored,
            "the grid is still filtered on the category that was hidden")


class MoveCategoryTest(unittest.TestCase):
    """One row-move on the shared model, with All immovable."""

    def test_a_move_down_goes_after_its_target_and_up_takes_its_place(self):
        for source, target, order in ((1, 3, ["_All", "b", "c", "a"]),
                                      (3, 1, ["_All", "c", "a", "b"])):
            with self.subTest(source=source, target=target):
                model = _categories(self, ["_All", "a", "b", "c"])
                self.assertTrue(model.move_category(source, target))
                self.assertEqual(order, model._categories)

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

    def test_a_no_op_and_out_of_range_return_false_and_emit_nothing(self):
        model = _categories(self, ["_All", "a", "b"])
        seen = []
        model.rowsAboutToBeMoved.connect(lambda *a: seen.append("about"))
        self.assertFalse(model.move_category(1, 1))
        self.assertFalse(model.move_category(1, 9))
        self.assertFalse(model.move_category(9, 1))
        self.assertEqual([], seen, "a rejected move emitted signals")

    def test_the_move_mutates_in_place_and_does_not_save(self):
        """The gesture saves ONCE on release: the move neither rebinds nor writes."""
        model = _categories(self, ["_All", "a", "b"])
        held = model._categories
        with mock.patch.object(model, "save") as save:
            self.assertTrue(model.move_category(1, 2))
        self.assertIs(held, model._categories, "the move rebound the list")
        save.assert_not_called()

    def test_the_saved_order_is_kept_after_a_reload(self):
        """What a save writes is what the next session shows."""
        model = _categories(self, ["_All", "a", "b", "c"])
        self.assertTrue(model.move_category(1, 3))
        self.assertTrue(model.save())
        test_support.reset_database_singletons()
        reloaded = category.Categories(preferences=model.preferences)
        self.assertEqual(["_All", "b", "c", "a"], [one for one in reloaded._categories
                                                   if one in ("_All", "a", "b", "c")])


class OrderSnapshotTest(unittest.TestCase):
    """Esc mid-gesture puts the order back exactly."""

    def test_restore_returns_the_snapshot_order_in_place(self):
        model = _categories(self, ["_All", "a", "b", "c"])
        held = model._categories
        snap = model.order_snapshot()
        self.assertIsNot(snap, model._categories, "the snapshot is the live list")
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


class SidebarShowsStoredOrderTest(unittest.TestCase):
    """The sidebar proxy shows the stored order; it does not sort."""

    def _proxy(self, entries):
        model = _categories(self, entries)
        proxy = category.CategoriesSidebarProxy()
        proxy.setSourceModel(model)
        proxy.hide_empty = False
        return model, proxy

    def test_the_proxy_presents_the_stored_order_and_follows_a_move(self):
        model, proxy = self._proxy(["_All", "b", "2", "a"])

        def shown():
            return [proxy.index(r, 0).data(model.CatSortRole)
                    for r in range(proxy.rowCount())]

        self.assertEqual(["_All", "b", "2", "a"], shown())
        model.move_category(1, 3)
        self.assertEqual(["_All", "2", "a", "b"], shown())


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
        # A call wrapped over lines is the same call: the searches ignore whitespace.
        cls.flat_source = "".join(cls.panel_source.split())

    def test_no_sidebar_proxy_is_sorted_or_sort_roled(self):
        for attr in self.SIDEBAR_PROXIES:
            for call in (".sort(", ".setSortRole(", ".setSortCaseSensitivity("):
                needle = "self.%s%s" % (attr, call)
                self.assertNotIn(
                    needle, self.flat_source,
                    "%s - the sidebar shows STORED order; sorting it "
                    "is the '2 above All' bug again" % needle)

    def test_color_goes_through_the_shared_sidebar_proxy(self):
        """Every sidebar, Color included, is built by `_sidebar_proxy`, which never sorts."""
        for attr in self.SIDEBAR_PROXIES:
            self.assertIn(
                "self.%s=self._sidebar_proxy(" % attr, self.flat_source,
                "%s does not use the shared sidebar proxy - one section built "
                "differently is how the sections came to differ before" % attr)
        start = self.panel_source.index("def _sidebar_proxy(")
        body = self.panel_source[start:self.panel_source.index("\n    def ", start + 1)]
        self.assertIn("category.CategoriesSidebarProxy(", body)
        for call in (".sort(", ".setSortRole(", ".setSortCaseSensitivity("):
            self.assertNotIn(call, body, "the shared sidebar proxy sorts")

    def test_the_save_dialog_dropdown_keeps_its_sort(self):
        """Alphabetical by the label a row shows, sorted only in `category_names_from`."""
        from amaze.panel.panel import AmazePanel

        class _Stored:    # the three calls `category_names_from` makes on a Categories model
            CatSortRole = 256

            def __init__(self, names):
                self.names = names

            def rowCount(self):
                return len(self.names)

            def index(self, row, _column):
                return row

            def data(self, row, _role):
                return self.names[row]

        self.assertEqual(
            ["Karma_Mats", "usds", "_WIP"],
            AmazePanel.category_names_from(
                _Stored(["_All", "usds", "_WIP", "Karma_Mats"])),
            "the dropdown is not alphabetical by label - `_WIP` reads "
            "WIP and sorts there - or it offers All as a category")
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "panel", "sections.py"),
                  encoding="utf-8") as handle:
            sections_flat = "".join(handle.read().split())
        self.assertIn(    # the three asset sections share one body over their own categories
            "returnpanel.category_names_from(st.categories),", sections_flat,
            "the asset sections' list no longer comes straight from "
            "`category_names_from`")


class ReorderContractTest(unittest.TestCase):
    """Every section has the reorder methods; the gesture calls them on the CONTEXT."""

    def test_the_five_sections_reorder_and_online_does_not(self):
        from amaze.panel import sections
        for cls in sections.SECTION_CLASSES:
            self.assertTrue(
                getattr(cls, "reorders_sidebar", False),
                "%s does not support the reorder gesture" % cls.key)
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
    """Records the section calls the gesture makes; the state machine is under test."""

    reorders_sidebar = True

    def __init__(self, model, proxy):
        self.model = model
        self.proxy = proxy
        self.commits = 0
        self.moves = []
        self.reselects = 0

    def reselect_sidebar_row(self):
        self.reselects += 1

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

            def active_section(self):
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

    def test_nothing_moves_above_all(self):
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
        self.assertEqual(1, section.reselects,
                         "`reselect_sidebar_row` was not called to restore the cleared highlight")
        self._release(view, controller, self._row_center(view, 3))
        self.assertEqual(0, section.commits)

    def test_a_release_without_a_move_commits_nothing(self):
        """A save that changes nothing still spends a write."""
        _model, _proxy, view, section, controller = self._harness()
        pos = self._press(view, controller, 1)
        controller._hold_fired()
        self._release(view, controller, pos)
        self.assertEqual(0, section.commits)

    def test_a_reset_returns_every_field_to_its_initial_state(self):
        """The initial state is written ONCE: a field that `_reset` misses fails here."""
        _model, _proxy, view, _section, controller = self._harness()
        born = dict(vars(controller))
        self._press(view, controller, 1)
        controller._hold_fired()
        self._move(view, controller, self._row_center(view, 3))
        controller._reset()
        self.assertEqual(born, dict(vars(controller)))

    def test_a_reset_unsets_the_closed_hand_cursor(self):
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
    """The File sidebar uses the same gesture; a move goes through `locations`."""

    def _base(self):
        """A realpath'd scratch root - the location store uses resolved paths."""
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
        """`move_registered` NORMALISES the path given, like the others. ▸p/one-file-one-table"""
        from amaze.core import locations
        base = self._base()
        one, two, three = (os.path.join(base, n) for n in ("1", "2", "3"))
        prefs = self._prefs([one, two, three])
        detour = os.path.join(base, "elsewhere", os.pardir, "1")
        self.assertNotEqual(detour, one, "the detour spelling was normalised "
                                         "before `move_registered` got it")
        self.assertTrue(locations.move_registered(prefs, detour, 2))
        self.assertEqual([test_support.posix_path(p)
                          for p in (two, three, one)],
                         prefs.file_folders)

    def test_a_move_works_where_the_STORED_spelling_is_not_the_absolute(self):
        """Fails for the likely wrong fix: normalising in the CALLER alone. ▸p/one-file-one-table"""
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

    def test_the_model_move_respects_the_scene_row(self):
        from amaze.core import file_library
        base = self._base()
        one, two, hip = (os.path.join(base, n) for n in ("1", "2", "hip"))
        prefs = self._prefs([one, two])
        os.makedirs(hip)
        model = file_library.FileFolders(prefs)
        self.assertTrue(model.set_scene_folder(hip), "premise: no scene row")
        seen = []
        model.rowsAboutToBeMoved.connect(lambda *a: seen.append("about"))
        model.rowsMoved.connect(lambda *a: seen.append("moved"))
        self.assertFalse(model.move_folder(1, 3), "the scene row moved")
        self.assertFalse(model.move_folder(2, 1), "a location moved above the scene row")
        self.assertEqual([], seen)
        self.assertTrue(model.move_folder(2, 3))
        self.assertEqual(["about", "moved"], seen)
        self.assertEqual([test_support.posix_path(p) for p in (two, one)],
                         prefs.file_folders)
        self.assertEqual(model.SCENE_LABEL, model.index(1, 0).data())

    def test_sort_by_name_orders_the_locations_by_the_label_shown(self):
        """A one-off, below All and the scene row; a renamed location sorts as its rename reads."""
        from amaze.core import file_library
        base = self._base()
        cherry, apple, zebra, hip = (os.path.join(base, n) for n in ("cherry", "Apple", "zebra", "hip"))
        prefs = self._prefs([cherry, zebra, apple])
        os.makedirs(hip)
        model = file_library.FileFolders(prefs)
        self.assertTrue(model.set_scene_folder(hip), "premise: no scene row")
        prefs.set_file_folder_name(zebra, "Banana")
        self.assertEqual("Banana", model.display_name(test_support.posix_path(zebra)),
                         "premise: the rename is the label")
        with mock.patch.object(prefs, "save") as save:
            self.assertTrue(model.sort_folders())
        save.assert_not_called()    # staged like a move; the menu action commits once
        self.assertEqual([test_support.posix_path(p) for p in (apple, zebra, cherry)],
                         prefs.file_folders)
        self.assertEqual(model.SCENE_LABEL, model.index(1, 0).data(), "the scene row moved")
        self.assertEqual(["Apple", "Banana", "cherry"],
                         [model.index(row, 0).data() for row in (2, 3, 4)])
        self.assertFalse(model.sort_folders(), "an already sorted list was sorted again")

    def test_the_file_menu_action_sorts_and_saves_once(self):
        from amaze.core import file_library, locations
        from amaze.panel import sections
        base = self._base()
        two, one = (os.path.join(base, n) for n in ("2", "1"))
        prefs = self._prefs([two, one])
        model = file_library.FileFolders(prefs)
        section = sections.FileSection.__new__(sections.FileSection)    # the menu action alone, with no panel
        with mock.patch.object(sections.FileSection, "_p", lambda _s, _name: model), \
                mock.patch.object(sections.FileSection, "shown_sidebar_key", lambda _s: ""), \
                mock.patch.object(sections.FileSection, "select_sidebar_key") as stand, \
                mock.patch.object(sections.FileSection, "panel", mock.Mock(prefs=prefs), create=True), \
                mock.patch.object(locations, "commit_registered_order") as commit:
            section.menu_sort_locations([], None)
            commit.assert_called_once()
            stand.assert_called_once_with("")
            section.menu_sort_locations([], None)
            commit.assert_called_once()    # nothing moved, nothing saved
        self.assertEqual([test_support.posix_path(p) for p in (one, two)], prefs.file_folders)


class EverySidebarSourceMovesCategories(unittest.TestCase):
    """`_sidebar_categories` returns any source it finds, and the reorder calls `move_category`."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def test_every_sidebar_with_a_source_holds_one_that_moves_categories(self):
        """Checked for every context the panel built, through the lookup the reorder uses."""
        panel = self.panel
        sourced = []
        for key, context in dict(panel.sections, online=panel.online_context).items():
            _proxy, source = context._sidebar_categories()
            if source is None:
                continue
            sourced.append(key)
            self.assertTrue(
                hasattr(source, "move_category"),
                "%s's sidebar is over a %s, which has no move_category, so a "
                "reorder raises" % (key, type(source).__name__))
        self.assertIn("material", sourced,
                      "premise: the Material sidebar has no source, so this checks nothing")


if __name__ == "__main__":
    unittest.main()
