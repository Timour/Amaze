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

from amaze.core import category, file_moves, grid_columns, matx_sources, model_registry  # noqa: E402
from amaze.tests import test_support  # noqa: E402

NOMOD = QtCore.Qt.KeyboardModifier.NoModifier
LEFT, RIGHT = QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.MouseButton.RightButton
COUNT = category.SIDEBAR_COUNT_ROLE


def _grid_key(panel) -> str:
    """The category the grid shows, read from the grid's own models: "" for all."""
    if panel.pane.is_online():
        role = panel.pane.matx_online_model.CategoryRole
        return panel.pane.matx_sorted_model.filter_value(role) or ""
    if panel.pane.current_section == "file":
        return panel.pane.file_files_model.browsing()
    stack = panel.pane.active_section().stack()
    return stack.proxy.filter_value(stack.model.CategoryRole) or ""


def _row_key(panel, index) -> str:
    """What a click on this sidebar row shows, read from the row: "" for All."""
    if panel.pane.is_online():
        return index.data(category.SIDEBAR_KEY_ROLE) or ""
    model = panel.cat_list.model()
    if panel.pane.current_section == "file":
        return index.data(model.BrowseRole) or ""
    return str(index.data(category.SIDEBAR_KEY_ROLE) or "")


def _pump(seconds=0.05):
    test_support.pump_until(lambda: False, timeout=seconds)


def _ui(**answers):
    """A fake `hou.ui`: every dialog returns its first button, `selectFile` the path given."""
    return types.SimpleNamespace(
        displayMessage=lambda *a, **k: 0, setStatusMessage=lambda *a, **k: None,
        selectFile=lambda *a, **k: answers.get("selectFile", ""))


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
            current = grid_columns.live_current_index(self.view)
            self.assertIsNotNone(current, "the sidebar highlights no row")
            self.assertEqual([current], self.view.selected_rows(),
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

    def _move_with_button_held(self, to):
        viewport = self.view.viewport()
        QtWidgets.QApplication.sendEvent(viewport, QtGui.QMouseEvent(
            QtCore.QEvent.Type.MouseMove, QtCore.QPointF(to),
            QtCore.QPointF(viewport.mapToGlobal(to)), LEFT, LEFT, NOMOD))

    def drag_select(self, start, end):
        """A left press held from one row to another; a drag Qt starts takes the release itself."""
        to = self.at(end)
        dragged = []
        view_type = type(self.view)
        real = view_type.startDrag

        def start_drag(view, actions):
            dragged.append(actions)
            return real(view, actions)

        QtTest.QTest.mousePress(self.view.viewport(), LEFT, NOMOD, self.at(start))
        with mock.patch.object(view_type, "startDrag", start_drag):
            self._move_with_button_held(to)
        if not dragged:
            QtTest.QTest.mouseRelease(self.view.viewport(), LEFT, NOMOD, to)
        return bool(dragged)

    def reorder(self, grabbed, over, escape=False, turn=False):
        """Press `grabbed` as a drag does, then drop it on `over` as Qt would; `escape` drops nothing."""
        QtTest.QTest.mouseClick(self.view.viewport(), LEFT, NOMOD, self.at(grabbed))
        model = self.view.model()
        if turn:
            _pump()
        if not escape:
            data = model.mimeData([grabbed])
            model.dropMimeData(data, QtCore.Qt.DropAction.MoveAction, -1, -1, over)

    def switch_library(self):
        test_support.apply_library(self, self.panel, test_support.seeded_library(self))


class _AssetSidebarPaths(_HighlightCase):
    """Material, Color, Node and Code run the same steps on their own categories."""

    FILTERS_HIDE = True    # a Kind filter that hides a category; Color's size filter hides none

    def setUp(self):
        super().setUp()
        categories = self.panel.pane.active_section().stack().categories
        for name in ("Kept", "Other"):
            categories.check_add_category(name)
        self.panel.pane.sidebar.refresh()
        _pump()

    def select_row(self, key="Kept"):
        self.click(self.row(key))

    def _category_name_entered(self, name):
        return mock.patch.object(self.panel, "ask_name", lambda _title, _default, then: then(name))

    def _peer_adds(self, name):
        """Another machine adds category `name`; `model_registry.refresh_all` merges it in."""
        categories = self.panel.pane.active_section().stack().categories
        path = os.path.join(self.panel.pane.prefs.dir, categories.DB_FILENAME)
        with open(path, encoding="utf-8-sig") as handle:
            document = json.load(handle)
        document.setdefault("categories", {})[name] = {"order": len(document["categories"])}
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=4)
        self.assertTrue(model_registry.refresh_all(self.panel.pane.prefs),
                        "premise: the merge did not read the other machine's write")

    def test_every_path_leaves_the_highlight_on_the_grids_row(self):
        panel, section = self.panel, self.panel.pane.active_section()
        self.check("activate", grid="")
        self.check("a click", self.select_row, grid="Kept")

        def right_press_then(*labels):
            def gesture():
                self.select_row()
                self.menu(self.row("Other"), *labels)
            return gesture

        self.check("a right press, the menu dismissed", right_press_then(), grid="Kept")
        with self._category_name_entered("Added"):
            self.check("a right press, Add", right_press_then("Add"), grid="Kept")
        self.check("a right press, Label", right_press_then("Label", "Red"), grid="Kept")
        self.check("a right press, Sort by name", right_press_then("Sort by name"), grid="Kept")
        with self._category_name_entered("Renamed"):
            self.check("a right press, Rename another", right_press_then("Rename"), grid="Kept")

        def delete_another():
            self.select_row()
            self.menu(self.row("Renamed"), "Delete")
        self.check("a right press, Delete another", delete_another, grid="Kept")

        def drag_select():
            self.select_row()
            self.assertTrue(self.drag_select(self.row("Kept"), self.row("Added")),
                            "premise: a press dragged from a category does not start the reorder")
        self.check("a press dragged onto another row starts a reorder; nothing else is chosen",
                   drag_select, grid="Kept")

        def reorder_off_the_row():
            self.select_row()
            self.reorder(self.row("Added"), self.row(""))
        self.check("a reorder released over All", reorder_off_the_row, grid="Added")

        def reorder_cancelled_with_esc():
            self.select_row()
            self.reorder(self.row("Added"), self.row("Kept"), escape=True)
        self.check("a reorder taken back with Esc", reorder_cancelled_with_esc, grid="Added")    # the pressed row was chosen

        if self.FILTERS_HIDE:
            def filter_hides():
                self.select_row()
                section.apply_filter("no such kind")
            self.check("the Filter hides the row", filter_hides, grid="")
            self.check("the Filter shows it again", lambda: section.apply_filter(None), grid="")

        def star():
            self.select_row()
            panel.cb_favsonly.setChecked(True)
        self.check("the Favourites star", star, grid="Kept")
        panel.cb_favsonly.setChecked(False)

        def tab_and_back():
            self.select_row()
            panel.section_tabs.setChecked("file")
            _pump()
            panel.section_tabs.setChecked(self.KEY)
        self.check("a tab switch and back", tab_and_back, grid="Kept")

        def online_and_back():
            self.select_row()
            panel.pane.enter_online()
            _pump()
            panel.pane.leave_online()
        self.check("entering and leaving Online", online_and_back, grid="Kept")
        self.check("a library switch", self.switch_library, grid="")

    def test_a_change_made_elsewhere_leaves_the_highlight_on_the_grids_row(self):
        """Another machine's and a second panel's edits reach this sidebar via the shared model."""
        categories = self.panel.pane.active_section().stack().categories

        def peer_merge():
            self.select_row()
            self._peer_adds("Peer")
        self.check("a peer merge through the registry", peer_merge, grid="Kept")
        second = test_support.reopened_panel(self)
        theirs = second.pane.sections[self.KEY]

        def second_panel_sorts():
            self.select_row()
            categories.check_add_category("Aardvark")    # last in the list: the sort has a row to move
            theirs.menu_sort_categories([], None)
        self.check("a second panel's Sort by name", second_panel_sorts, grid="Kept")

        def second_panel_deletes_it():
            self.select_row()
            row = getattr(second.pane, theirs.sidebar_attr).index_of("Kept")
            self.assertTrue(row.isValid(), "premise: the second panel has no Kept row")
            theirs.menu_remove_category([row], row)
        self.check("a second panel deletes the row", second_panel_deletes_it, grid="")

    def test_a_reorder_held_across_a_turn_follows_the_grabbed_row(self):
        """Row moves during a press-and-hold reorder do not reselect the sidebar row mid-drag."""
        def held_across_a_turn():
            self.select_row()
            self.reorder(self.row("Other"), self.row("Kept"), turn=True)
        self.check("a reorder held across an event-loop turn", held_across_a_turn, grid="Other")

    def test_a_burst_of_resets_reselects_the_row_once(self):
        """However many resets arrive in one event-loop turn, `reselect_sidebar_row` runs once."""
        section = self.panel.pane.active_section()
        categories = section.stack().categories
        self.select_row()
        order, calls = list(categories._categories), []
        with mock.patch.object(section, "reselect_sidebar_row", lambda: calls.append(1)):
            categories.restore_order(order[:1] + order[:0:-1])    # one reset
            categories.restore_order(order)    # and a second, in the same turn
            _pump()
        self.assertEqual([1], calls, "two resets in one turn ran reselect_sidebar_row %d times" % len(calls))


class SidebarChoiceTest(_HighlightCase, unittest.TestCase):
    """What a click, a Ctrl-click and the arrow keys on the sidebar choose."""

    KEY = "material"

    def setUp(self):
        super().setUp()
        categories = self.panel.pane.active_section().stack().categories
        for name in ("Kept", "Other", "Third"):
            categories.check_add_category(name)
        self.panel.pane.sidebar.refresh()
        _pump()
        self.click(self.row("Kept"))

    def _choices(self):
        """Every category the active section is asked to show from now on."""
        section = self.panel.pane.active_section()
        patcher = mock.patch.object(section, "select_category")
        chosen = patcher.start()
        self.addCleanup(patcher.stop)
        return chosen

    def test_a_ctrl_click_on_the_highlighted_row_keeps_it_highlighted(self):
        def ctrl_click():
            QtTest.QTest.mouseClick(self.view.viewport(), LEFT,
                                    QtCore.Qt.KeyboardModifier.ControlModifier, self.at(self.row("Kept")))
        self.check("a ctrl-click on the highlighted row", ctrl_click, grid="Kept")

    def test_a_click_on_the_highlighted_row_shows_it_again(self):
        chosen = self._choices()
        self.click(self.row("Kept"))
        self.assertEqual(1, chosen.call_count, "a click on the highlighted row did not show it again")
        self.click(self.row("Other"))
        self.assertEqual(2, chosen.call_count, "a click on another row was not shown exactly once")

    def test_the_arrow_keys_show_only_the_row_they_stop_on(self):
        from amaze.panel import panel as panel_mod
        chosen = self._choices()
        for _step in range(2):
            QtTest.QTest.keyClick(self.view, QtCore.Qt.Key.Key_Down)
        self.assertEqual(0, chosen.call_count, "each arrow step showed its row at once")
        _pump(panel_mod.SIDEBAR_KEY_PAUSE_MS / 1000.0 + 0.15)
        self.assertEqual(1, chosen.call_count, "the row the keys stopped on was not shown once")
        current = grid_columns.live_current_index(self.view)
        self.assertEqual(current.row(), chosen.call_args[0][0].row(), "another row than the highlighted one was shown")

    def test_a_click_after_the_arrow_keys_wins_over_their_pause(self):
        from amaze.panel import panel as panel_mod
        chosen = self._choices()
        QtTest.QTest.keyClick(self.view, QtCore.Qt.Key.Key_Down)
        self.click(self.row("Kept"))
        _pump(panel_mod.SIDEBAR_KEY_PAUSE_MS / 1000.0 + 0.15)
        self.assertEqual(1, chosen.call_count, "the key's pause showed its row after the click")
        self.assertEqual("Kept", _row_key(self.panel, chosen.call_args[0][0]))


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
    """Locations and their subfolders, file moves, and the empty grid's Locate."""

    KEY = "file"

    def setUp(self):
        super().setUp()
        self.folders = self.panel.pane.file_folders_model
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

    def select_row(self, key=None):
        self.click(self.row(self.loc if key is None else key))

    def _move_one_file_into(self, folder):
        self.select_row()
        proxy = self.panel.thumblist.model()
        selection = self.panel.thumblist.selectionModel()
        selection.select(proxy.index(0, 0), QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect)
        self.assertTrue(self.panel.pane.active_section().move_files_to(folder), "premise: no move started")
        self.assertTrue(test_support.pump_until(lambda: not file_moves.mover.busy()), "the move never finished")

    def remember_unread(self, name) -> str:
        """A new subfolder set as the last folder, the File tab entered before its row is loaded."""
        folder = os.path.join(self.loc, name)
        os.makedirs(folder)
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        self.panel.section_tabs.setChecked("material")
        _pump()
        self.panel.pane.prefs.last_file_folder = folder
        self.panel.section_tabs.setChecked("file")
        self.assertFalse(self.folders.index_of(folder).isValid(), "premise: its row is already loaded")
        return folder

    def test_every_path_leaves_the_highlight_on_the_grids_row(self):
        panel, loc, nested, second = self.panel, self.loc, self.nested, self.second
        self.check("activate on the remembered location", grid=loc)
        self.check("a click on a location", self.select_row, grid=loc)
        self.check("a click on a subfolder", lambda: self.select_row(nested), grid=nested)

        def dismissed_over_a_subfolder():
            self.select_row(nested)
            self.menu(self.row(second))
        self.check("on a subfolder, a right press elsewhere dismissed",
                   dismissed_over_a_subfolder, grid=nested)

        def right_press_then(*labels):
            def gesture():
                self.select_row()
                self.menu(self.row(second), *labels)
            return gesture

        with mock.patch.object(panel, "ask_name", lambda _title, _default, then: then("Named")):
            self.check("a right press, Rename", right_press_then("Rename", "Edit"), grid=loc)
        self.check("a right press, Label", right_press_then("Label", "Red"), grid=loc)
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
            self.select_row()
            self.menu(self.row(""), "Undo Move")
            self.assertTrue(test_support.pump_until(lambda: not file_moves.mover.busy()), "never moved back")
        self.check("a right press, Undo Move", undo_from_the_sidebar, grid=loc)

        def drag_select():
            self.select_row()
            self.assertTrue(self.drag_select(self.row(loc), self.row(second)),
                            "premise: a press dragged from a location does not start the reorder")
        self.check("a press dragged onto another row starts a reorder; nothing else is chosen",
                   drag_select, grid=loc)

        def reorder_off_the_row():
            self.select_row()
            self.reorder(self.row(second), self.row(""))
        self.check("a reorder released over All", reorder_off_the_row, grid=second)

        def reorder_cancelled_with_esc():
            self.select_row()
            self.reorder(self.row(second), self.row(loc), escape=True)
        self.check("a reorder taken back with Esc", reorder_cancelled_with_esc, grid=second)    # the pressed row was chosen

        def star():
            self.select_row()
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
            self.select_row(nested)
            panel.section_tabs.setChecked("material")
            _pump()
            panel.section_tabs.setChecked("file")
        self.check("a tab switch and back", tab_and_back, grid=nested)

        def remove_another():
            self.select_row()
            self.menu(self.row(added), "Remove")
        self.check("a right press, Remove another location", remove_another, grid=loc)
        self.check("a library switch", self.switch_library)

    def test_a_location_located_from_the_blank(self):
        """The empty grid's Locate runs through the panel's own functions."""
        panel = self.panel
        missing = tempfile.mkdtemp(prefix="amaze_missing_location_")
        self.add(missing)
        shutil.rmtree(missing)

        def locate_cancelled():
            self.select_row("")
            with mock.patch.object(hou, "ui", _ui(), create=True):
                panel.locate_unreadable_folder()
        self.check("the blank's Locate, cancelled", locate_cancelled, grid="")

    def test_a_browsed_subfolder_removed_on_disk(self):
        """Its row is removed at the next read:the highlight and the grid move to its location."""
        def removed_then_read():
            self.select_row(self.nested)
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
        self.online = self.panel.pane.matx_online_model
        self.addCleanup(setattr, self.online, "_all", self.online._all)

    def fetch_catalogue(self, *categories):
        """A catalogue fetch with one record per category; the shared disk cache is unchanged."""
        online = self.online
        records = [matx_sources.MatxRecord(source=online._source_filter, uid="probe-%s" % name,
                                           title="Probe %s" % name, category=name)
                   for name in categories]
        with mock.patch.object(online, "_save_cache", lambda _records: None):
            online._on_catalogue(records, [], online._generation)

    def test_every_path_leaves_the_highlight_on_the_grids_row(self):
        panel = self.panel
        self.check("entering Online", panel.pane.enter_online, grid="")
        self.check("a catalogue landing", lambda: self.fetch_catalogue("Metal", "Wood"), grid="")
        self.check("a click on a category", lambda: self.click(self.row("Metal")), grid="Metal")
        self.check("a catalogue landing that keeps it",
                   lambda: self.fetch_catalogue("Brick", "Metal", "Wood"), grid="Metal")
        self.check("a right press, no menu", lambda: self.menu(self.row("Wood")), grid="Metal")

        def drag_select():
            self.click(self.row("Metal"))
            self.drag_select(self.row("Metal"), self.row("Brick"))
        self.check("a press dragged onto another row", drag_select, grid="Brick")

        def search():
            self.click(self.row("Metal"))
            panel.line_filter.setText("Probe")
            panel.pane.search(panel.line_filter.text())
        self.check("the search box", search, grid="Metal")

        def fetch_without_it():
            self.click(self.row("Wood"))
            self.fetch_catalogue("Brick", "Metal")
        self.check("a catalogue landing that drops it", fetch_without_it, grid="")

        def leave_and_return():
            panel.pane.leave_online()
            _pump()
            panel.pane.enter_online()
        self.check("leaving and entering again", leave_and_return, grid="")
        self.check("a library switch", self.switch_library, grid="")


if __name__ == "__main__":
    unittest.main()
