"""The sidebar's highlighted row and what the grid shows agree after every path that moves either."""

import json
import os
import shutil
import tempfile
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtTest, QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

from amaze.core import category, file_moves, matx_sources, model_registry  # noqa: E402
from amaze.helpers import ui_helpers  # noqa: E402
from amaze.tests import test_support  # noqa: E402

NOMOD = QtCore.Qt.KeyboardModifier.NoModifier
LEFT, RIGHT = QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.MouseButton.RightButton
COUNT = category.SIDEBAR_COUNT_ROLE


def _grid_key(panel) -> str:
    """The category the grid shows, read from the grid's own models: "" for all."""
    if panel._is_online():
        role = panel.matx_online_model.CategoryRole
        return panel.matx_sorted_model.filter_value(role) or ""
    if panel.current_section == "file":
        return panel.file_files_model.browsing()
    stack = panel.active_section().stack()
    return stack.proxy.filter_value(stack.model.CategoryRole) or ""


def _row_key(panel, index) -> str:
    """What a click on this sidebar row shows, read from the row: "" for All."""
    if panel._is_online():
        return panel.matx_source_model.category_at(index.row()) or ""
    model = panel.cat_list.model()
    if panel.current_section == "file":
        return index.data(model.BrowseRole) or ""
    stored = index.data(model.sourceModel().CatSortRole)
    return "" if category.is_all(stored) else str(stored)


def _pump(seconds=0.05):
    test_support.pump_until(lambda: False, timeout=seconds)


def _ui(**answers):
    """A fake `hou.ui`: every dialog returns its first button, `selectFile` the path given."""
    return types.SimpleNamespace(
        displayMessage=lambda *a, **k: 0, setStatusMessage=lambda *a, **k: None,
        selectFile=lambda *a, **k: answers.get("selectFile", ""))


def _check_ui(*wanted_labels):
    """A fake `hou.ui` for Check Library: each dialog picks the next wanted label, else closes."""
    wanted = list(wanted_labels)

    def answer(*_args, **kwargs):
        buttons = list(kwargs.get("buttons") or ())
        hit = [at for at, label in enumerate(buttons) if wanted and wanted[0] in label]
        if hit:
            wanted.pop(0)
            return hit[0]
        return kwargs.get("close_choice", 0)

    return types.SimpleNamespace(displayMessage=answer, setStatusMessage=lambda *a, **k: None,
                                 selectFromList=lambda *a, **k: ())


class _HighlightCase:
    """A visible fixture panel on section KEY, and the mouse actions that change its sidebar."""

    KEY = ""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.panel.resize(900, 700)
        self.panel.show()
        self.addCleanup(self.panel.hide)
        self.panel.section_tabs.setChecked(self.KEY)
        _pump()

    @property
    def view(self):
        return self.panel.cat_list

    def check(self, path, gesture=None, grid=None):
        """Run one path; one row is highlighted, the grid shows it, and that is `grid` when given."""
        with self.subTest(path=path):
            if gesture is not None:
                gesture()
            _pump()
            current = ui_helpers.live_current_index(self.view)
            self.assertIsNotNone(current, "the sidebar highlights no row")
            self.assertEqual([current], self.view.selectedIndexes(),
                             "the highlight is not the one current row")
            self.assertEqual(_grid_key(self.panel), _row_key(self.panel, current),
                             "the sidebar highlights another row than the grid shows")
            if grid is not None:
                self.assertEqual(grid, _grid_key(self.panel), "the grid shows another category")

    def row(self, key):
        """The sidebar row a click on which shows `key`, its subfolders searched too."""
        model = self.view.model()
        pending = [QtCore.QModelIndex()]
        while pending:
            parent = pending.pop()
            for number in range(model.rowCount(parent)):
                index = model.index(number, 0, parent)
                if _row_key(self.panel, index) == key:
                    return index
                pending.append(index)
        self.fail("premise: no sidebar row shows %r" % key)

    def at(self, index):
        self.view.scrollTo(index)
        return self.view.visualRect(index).center()

    def click(self, index, button=LEFT):
        QtTest.QTest.mouseClick(self.view.viewport(), button, NOMOD, self.at(index))
        _pump(0.01)

    def menu(self, index, *labels):
        """Right-click `index`, pick `labels` through the submenus; with none, dismiss the menu."""
        self.click(index, RIGHT)

        def pick(menu, *_args, **_kwargs):
            action = None
            for label in labels:
                action = next(a for a in menu.actions() if a.text() == label)
                menu = action.menu() or menu
            return action

        with mock.patch.object(QtWidgets.QMenu, "exec_", pick):
            self.panel.catlist_rc_menu()

    def _held(self, to):
        viewport = self.view.viewport()
        QtWidgets.QApplication.sendEvent(viewport, QtGui.QMouseEvent(
            QtCore.QEvent.Type.MouseMove, QtCore.QPointF(to),
            QtCore.QPointF(viewport.mapToGlobal(to)), LEFT, LEFT, NOMOD))

    def drag_select(self, start, end):
        """A left press on one row, held across to another and released there."""
        to = self.at(end)
        QtTest.QTest.mousePress(self.view.viewport(), LEFT, NOMOD, self.at(start))
        self._held(to)
        QtTest.QTest.mouseRelease(self.view.viewport(), LEFT, NOMOD, to)

    def reorder(self, grabbed, over, release_at=None, escape=False, turn=False):
        """Press and hold `grabbed`, move over `over`, run events, press Esc if asked, release."""
        to = self.at(over)
        QtTest.QTest.mousePress(self.view.viewport(), LEFT, NOMOD, self.at(grabbed))
        self.panel.sidebar_reorder._hold_fired()
        self._held(to)
        if turn:
            _pump()
        if escape:
            QtTest.QTest.keyClick(self.view, QtCore.Qt.Key.Key_Escape)
        QtTest.QTest.mouseRelease(self.view.viewport(), LEFT, NOMOD, release_at or to)

    def switch_library(self):
        test_support.apply_library(self, self.panel, test_support.seeded_library(self))


class _AssetSidebarPaths(_HighlightCase):
    """Material, Color, Node and Code run the same steps on their own categories."""

    FILTERS_HIDE = True    # a Kind filter that hides a category; Color's size filter hides none

    def setUp(self):
        super().setUp()
        categories = self.panel.active_section().stack().categories
        for name in ("Kept", "Other"):
            categories.check_add_category(name)
        self.panel.refresh_sidebar_categories()
        _pump()

    def stand(self, key="Kept"):
        self.click(self.row(key))

    def _answer(self, name):
        return mock.patch.object(self.panel, "ask_category_name", lambda *_a, **_k: name)

    def _peer_adds(self, name):
        """Another machine adds category `name`; `model_registry.refresh_all` merges it in."""
        categories = self.panel.active_section().stack().categories
        path = os.path.join(self.panel.prefs.dir, categories.DB_FILENAME)
        with open(path, encoding="utf-8-sig") as handle:
            document = json.load(handle)
        document.setdefault("categories", {})[name] = {"order": len(document["categories"])}
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=4)
        self.assertTrue(model_registry.refresh_all(self.panel.prefs),
                        "premise: the merge did not read the other machine's write")

    def test_every_path_leaves_the_highlight_on_the_grids_row(self):
        panel, section = self.panel, self.panel.active_section()
        self.check("activate", grid="")
        self.check("a click", self.stand, grid="Kept")

        def right_press_then(*labels):
            def gesture():
                self.stand()
                self.menu(self.row("Other"), *labels)
            return gesture

        self.check("a right press, the menu dismissed", right_press_then(), grid="Kept")
        with self._answer("Added"):
            self.check("a right press, Add", right_press_then("Add"), grid="Kept")
        self.check("a right press, Label", right_press_then("Label", "Red"), grid="Kept")
        self.check("a right press, Sort by name", right_press_then("Sort by name"), grid="Kept")
        with self._answer("Renamed"):
            self.check("a right press, Rename another", right_press_then("Rename"), grid="Kept")

        def delete_another():
            self.stand()
            self.menu(self.row("Renamed"), "Delete")
        self.check("a right press, Delete another", delete_another, grid="Kept")

        def drag_select():
            self.stand()
            self.drag_select(self.row("Kept"), self.row("Added"))
        self.check("a press dragged onto another row", drag_select, grid="Added")

        def reorder_off_the_row():
            self.stand()
            self.reorder(self.row("Added"), self.row(""))
        self.check("a reorder released over All", reorder_off_the_row, grid="Added")

        def reorder_taken_back():
            self.stand()
            self.reorder(self.row("Added"), self.row("Kept"), escape=True)
        self.check("a reorder taken back with Esc", reorder_taken_back, grid="Kept")

        if self.FILTERS_HIDE:
            def filter_hides():
                self.stand()
                section.apply_filter("no such kind")
            self.check("the Filter hides the row", filter_hides, grid="")
            self.check("the Filter shows it again", lambda: section.apply_filter(None), grid="")

        def star():
            self.stand()
            panel.cb_favsonly.setChecked(True)
        self.check("the Favourites star", star, grid="Kept")
        panel.cb_favsonly.setChecked(False)

        def clean_up():
            self.stand()
            panel.prefs.add_file_favorite(os.path.join(panel.prefs.file_folders[0], "gone.exr"))
            with mock.patch.object(hou, "ui", _check_ui("Fix Safe"), create=True):
                test_support.repair_from_preferences(self, panel)
        self.check("Check Library", clean_up, grid="")    # a re-read selects the first row, as Reload does

        def tab_and_back():
            self.stand()
            panel.section_tabs.setChecked("file")
            _pump()
            panel.section_tabs.setChecked(self.KEY)
        self.check("a tab switch and back", tab_and_back, grid="Kept")

        def online_and_back():
            self.stand()
            panel.enter_online_world()
            _pump()
            panel.leave_online_world()
        self.check("entering and leaving Online", online_and_back, grid="Kept")
        self.check("a library switch", self.switch_library, grid="")

    def test_a_change_made_elsewhere_leaves_the_highlight_on_the_grids_row(self):
        """Another machine's and a second panel's edits reach this sidebar via the shared model."""
        categories = self.panel.active_section().stack().categories

        def peer_merge():
            self.stand()
            self._peer_adds("Peer")
        self.check("a peer merge through the registry", peer_merge, grid="Kept")
        second = test_support.reopened_panel(self)
        theirs = second.sections[self.KEY]

        def second_panel_sorts():
            self.stand()
            categories.check_add_category("Aardvark")    # last in the list: the sort has a row to move
            theirs.menu_sort_categories([], None)
        self.check("a second panel's Sort by name", second_panel_sorts, grid="Kept")

        def second_panel_deletes_it():
            self.stand()
            row = second._sidebar_row_stored(getattr(second, theirs.sidebar_attr), "Kept")
            self.assertIsNotNone(row, "premise: the second panel has no Kept row")
            theirs.menu_remove_category([row], row)
        self.check("a second panel deletes the row", second_panel_deletes_it, grid="")

    def test_a_reorder_held_across_a_turn_follows_the_grabbed_row(self):
        """Row moves during a press-and-hold reorder do not reselect the sidebar row mid-drag."""
        def held_across_a_turn():
            self.stand()
            self.reorder(self.row("Other"), self.row("Kept"), turn=True)
        self.check("a reorder held across an event-loop turn", held_across_a_turn, grid="Other")

    def test_a_burst_of_resets_stands_again_once(self):
        """However many resets arrive in one event-loop turn, `reselect_sidebar_row` runs once."""
        section = self.panel.active_section()
        categories = section.stack().categories
        self.stand()
        order, stood = categories.order_snapshot(), []
        with mock.patch.object(section, "reselect_sidebar_row", lambda: stood.append(1)):
            categories.restore_order(order[:1] + order[:0:-1])    # one reset
            categories.restore_order(order)    # and a second, in the same turn
            _pump()
        self.assertEqual([1], stood, "two resets in one turn ran reselect_sidebar_row %d times" % len(stood))


class MaterialSidebarTest(_AssetSidebarPaths, unittest.TestCase):
    KEY = "material"


class ColorSidebarTest(_AssetSidebarPaths, unittest.TestCase):
    KEY = "gradient"
    FILTERS_HIDE = False


class NodeSidebarTest(_AssetSidebarPaths, unittest.TestCase):
    KEY = "cop"


class CodeSidebarTest(_AssetSidebarPaths, unittest.TestCase):
    KEY = "code"


class FileSidebarTest(_HighlightCase, unittest.TestCase):
    """Locations and their subfolders, file moves, and Check Library setting a location aside."""

    KEY = "file"

    def setUp(self):
        super().setUp()
        self.folders = self.panel.file_folders_model
        self.loc = self.folders.registered_at(self.folders._offset())    # the first location
        self.nested = self.loc + "nested"
        self.second = self.add(test_support.fresh_files_folder(self))
        self.read(self.loc, self.nested)

    def locations(self) -> list:
        return [self.folders.data(self.folders.index(row, 0), self.folders.PathRole)
                for row in range(self.folders._offset(), self.folders.rowCount())]

    def added_since(self, before) -> str:
        """The one location registered since `before`, in the form its sidebar row stores."""
        found = [path for path in self.locations() if path not in before]
        self.assertEqual(1, len(found), "premise: not one new location: %s" % found)
        return found[0]

    def add(self, folder) -> str:
        before = self.locations()
        self.assertTrue(self.folders.add_folder(folder), "premise: %s was not added" % folder)
        return self.added_since(before)

    def read(self, location, folder):
        """Expand `location` until its row for `folder` is loaded."""
        self.folders.data(self.folders.index_of(location), COUNT)
        self.assertTrue(test_support.pump_until(lambda: self.folders.index_of(folder).isValid()),
                        "premise: %s never appeared under its location" % folder)
        self.view.expand(self.folders.index_of(location))
        _pump()

    def stand(self, key=None):
        self.click(self.row(self.loc if key is None else key))

    def _move_one_file_into(self, folder):
        self.stand()
        proxy = self.panel.thumblist.model()
        selection = self.panel.thumblist.selectionModel()
        selection.select(proxy.index(0, 0), QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect)
        self.assertTrue(self.panel.active_section().move_files_to(folder), "premise: no move started")
        self.assertTrue(test_support.pump_until(lambda: not file_moves.mover.busy()), "the move never finished")

    def remember_unread(self, name) -> str:
        """A new subfolder set as the last folder, the File tab entered before its row is loaded."""
        folder = os.path.join(self.loc, name)
        os.makedirs(folder)
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        self.panel.section_tabs.setChecked("material")
        _pump()
        self.panel.prefs.last_file_folder = folder
        self.panel.section_tabs.setChecked("file")
        self.assertFalse(self.folders.index_of(folder).isValid(), "premise: its row is already loaded")
        return folder

    def test_every_path_leaves_the_highlight_on_the_grids_row(self):
        panel, loc, nested, second = self.panel, self.loc, self.nested, self.second
        self.check("activate on the remembered location", grid=loc)
        self.check("a click on a location", self.stand, grid=loc)
        self.check("a click on a subfolder", lambda: self.stand(nested), grid=nested)

        def dismissed_over_a_subfolder():
            self.stand(nested)
            self.menu(self.row(second))
        self.check("on a subfolder, a right press elsewhere dismissed",
                   dismissed_over_a_subfolder, grid=nested)

        def right_press_then(*labels):
            def gesture():
                self.stand()
                self.menu(self.row(second), *labels)
            return gesture

        with mock.patch.object(panel, "ask_category_name", lambda *_a, **_k: "Named"):
            self.check("a right press, Rename", right_press_then("Rename", "Edit"), grid=loc)
        self.check("a right press, Label", right_press_then("Label", "Red"), grid=loc)
        self.check("a right press, Show", right_press_then("Show", "Pathname"), grid=loc)
        picked = tempfile.mkdtemp(prefix="amaze_added_location_")
        self.addCleanup(shutil.rmtree, picked, ignore_errors=True)
        before = self.locations()
        with mock.patch.object(hou, "ui", _ui(selectFile=picked), create=True):
            self.check("a right press, Add", right_press_then("Add"), grid=loc)
        added = self.added_since(before)
        with mock.patch.object(hou, "ui", _ui(), create=True):
            self.check("a right press, Locate cancelled", right_press_then("Locate"), grid=loc)
        self.check("a file move landing", lambda: self._move_one_file_into(nested), grid=loc)

        def undo_from_the_sidebar():
            self.stand()
            self.menu(self.row(""), "Undo Move")
            self.assertTrue(test_support.pump_until(lambda: not file_moves.mover.busy()), "never moved back")
        self.check("a right press, Undo Move", undo_from_the_sidebar, grid=loc)

        def drag_select():
            self.stand()
            self.drag_select(self.row(loc), self.row(second))
        self.check("a press dragged onto another row", drag_select, grid=second)

        def reorder_off_the_row():
            self.stand()
            self.reorder(self.row(second), self.row(""))
        self.check("a reorder released over All", reorder_off_the_row, grid=second)

        def reorder_taken_back():
            self.stand()
            self.reorder(self.row(second), self.row(loc), escape=True)
        self.check("a reorder taken back with Esc", reorder_taken_back, grid=loc)

        def star():
            self.stand()
            panel.cb_favsonly.setChecked(True)
        self.check("the Favourites star", star, grid=loc)
        panel.cb_favsonly.setChecked(False)

        def unfolding_then_a_click():
            late = self.remember_unread("late")
            self.click(self.row(""))
            self.read(loc, late)
        self.check("a remembered subfolder still unfolding, a click elsewhere",
                   unfolding_then_a_click, grid="")
        later = loc + "later"

        def unfolding_then_a_dismissed_menu():
            self.remember_unread("later")
            self.menu(self.row(second))
            self.read(loc, later)
        self.check("a remembered subfolder still unfolding, a right press dismissed",
                   unfolding_then_a_dismissed_menu, grid=later)

        def tab_and_back():
            self.stand(nested)
            panel.section_tabs.setChecked("material")
            _pump()
            panel.section_tabs.setChecked("file")
        self.check("a tab switch and back", tab_and_back, grid=nested)

        def remove_another():
            self.stand()
            self.menu(self.row(added), "Remove")
        self.check("a right press, Remove another location", remove_another, grid=loc)
        self.check("a library switch", self.switch_library)

    def test_a_location_set_aside_or_located_from_the_blank(self):
        """Check Library and the empty grid's Locate run through the panel's own functions."""
        panel = self.panel
        made = tempfile.mkdtemp(prefix="amaze_gone_location_")
        self.addCleanup(shutil.rmtree, made, ignore_errors=True)
        gone = self.add(made)

        def clean_up():
            self.stand(gone)
            shutil.rmtree(gone)
            with mock.patch.object(hou, "ui", _check_ui("Fix Safe"), create=True):
                test_support.repair_from_preferences(self, panel)
        self.check("Check Library sets the browsed location aside", clean_up)

        missing = tempfile.mkdtemp(prefix="amaze_missing_location_")
        self.add(missing)
        shutil.rmtree(missing)

        def locate_cancelled():
            self.stand("")
            with mock.patch.object(hou, "ui", _ui(), create=True):
                panel.locate_unreadable_folder()
        self.check("the blank's Locate, cancelled", locate_cancelled, grid="")

    def test_a_browsed_subfolder_removed_on_disk(self):
        """Its row is removed at the next read:the highlight and the grid move to its location."""
        def removed_then_read():
            self.stand(self.nested)
            shutil.rmtree(self.nested)
            self.folders.refresh_counts()
            self.folders.data(self.folders.index_of(self.loc), COUNT)
            self.assertTrue(test_support.pump_until(lambda: not self.folders.index_of(self.nested).isValid()),
                            "premise: the removed subfolder's row stayed")
        self.check("a browsed subfolder removed on disk, then read again", removed_then_read,
                   grid=self.loc)


class OnlineSidebarTest(_HighlightCase, unittest.TestCase):
    """The catalogue's categories, which a finished fetch can replace while the user browses."""

    KEY = "material"

    def setUp(self):
        super().setUp()
        self.online = self.panel.matx_online_model
        self.addCleanup(setattr, self.online, "_all", self.online._all)

    def land(self, *categories):
        """A catalogue fetch with one record per category; the shared disk cache is unchanged."""
        online = self.online
        records = [matx_sources.MatxRecord(source=online._source_filter, uid="probe-%s" % name,
                                           title="Probe %s" % name, category=name)
                   for name in categories]
        with mock.patch.object(online, "_save_cache", lambda _records: None):
            online._on_catalogue(records, [], online._generation)

    def test_every_path_leaves_the_highlight_on_the_grids_row(self):
        panel = self.panel
        self.check("entering Online", panel.enter_online_world, grid="")
        self.check("a catalogue landing", lambda: self.land("Metal", "Wood"), grid="")
        self.check("a click on a category", lambda: self.click(self.row("Metal")), grid="Metal")
        self.check("a catalogue landing that keeps it",
                   lambda: self.land("Brick", "Metal", "Wood"), grid="Metal")
        self.check("a right press, no menu", lambda: self.menu(self.row("Wood")), grid="Metal")

        def drag_select():
            self.click(self.row("Metal"))
            self.drag_select(self.row("Metal"), self.row("Brick"))
        self.check("a press dragged onto another row", drag_select, grid="Brick")

        def search():
            self.click(self.row("Metal"))
            panel.line_filter.setText("Probe")
            panel.filter_thumb_view()
        self.check("the search box", search, grid="Metal")

        def landing_drops_it():
            self.click(self.row("Wood"))
            self.land("Brick", "Metal")
        self.check("a catalogue landing that drops it", landing_drops_it, grid="")

        def leave_and_return():
            panel.leave_online_world()
            _pump()
            panel.enter_online_world()
        self.check("leaving and entering again", leave_and_return, grid="")
        self.check("a library switch", self.switch_library, grid="")


if __name__ == "__main__":
    unittest.main()
