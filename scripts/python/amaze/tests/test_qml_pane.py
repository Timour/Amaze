"""The Amaze (QML) pane builds, loads its QML silently, shows its sidebar, and Qt deletes it."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # the first QApplication picks the platform ▸p/first-app-picks-the-platform
from PySide6 import QtCore, QtQuick, QtWidgets
import shiboken6

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401
from amaze.core import grid_columns  # noqa: E402
from amaze.qml import pane as qml_pane  # noqa: E402
from amaze.tests import test_support  # noqa: E402


class TheQmlPaneOpensAndCloses(unittest.TestCase):

    def test_it_builds_with_no_qml_warning_and_qt_deletes_it_on_the_main_thread(self):
        widget_panel = test_support.fixture_panel(self)    # the fixture library, and a second pane on it
        said = []

        def hear(_kind, context, text):
            if ".qml" in text or context.category in ("qml", "js"):
                said.append(text)

        previous = QtCore.qInstallMessageHandler(hear)
        try:
            panel = qml_pane.QmlPanel()
            self.addCleanup(test_support.stop_panel_workers, panel)
            panel.setAttribute(QtCore.Qt.WidgetAttribute.WA_DontShowOnScreen)
            panel.resize(840, 420)
            panel.show()
            QtWidgets.QApplication.processEvents()
        finally:
            QtCore.qInstallMessageHandler(previous)

        self.assertEqual([], said, "the pane's QML reported errors or warnings while it loaded")
        self.assertIsNotNone(panel.view.rootObject(), "the pane's QML did not load")
        self.assertIsNot(widget_panel.pane, panel.pane, "the two panes share one engine")
        self.assertIs(widget_panel.pane.material_model, panel.pane.material_model,
                      "the two panes on one library read separate models")

        parts = (panel, panel.view, panel.state, panel.pane)
        main = QtWidgets.QApplication.instance().thread()
        self.assertTrue(all(part.thread() == main for part in parts), "a part lives off the main thread")
        panel.close()
        panel.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)    # Qt's own loop, no collector
        self.assertEqual([False] * len(parts), [shiboken6.isValid(part) for part in parts],
                         "the pane, its QML view, its state or its engine outlived the close")

    def test_the_sidebar_loads_silently_and_shows_the_sections_rows(self):
        test_support.fixture_panel(self)
        said = []

        def hear(_kind, context, text):
            if ".qml" in text or context.category in ("qml", "js"):
                said.append(text)

        previous = QtCore.qInstallMessageHandler(hear)
        try:
            panel = qml_pane.QmlPanel()
            self.addCleanup(test_support.stop_panel_workers, panel)
            self.addCleanup(QtCore.QCoreApplication.sendPostedEvents, None, QtCore.QEvent.Type.DeferredDelete)
            self.addCleanup(panel.deleteLater)
            panel.setAttribute(QtCore.Qt.WidgetAttribute.WA_DontShowOnScreen)
            panel.resize(840, 420)
            panel.show()
            QtWidgets.QApplication.processEvents()
            panel.view.grabFramebuffer()    # a frame: the tree makes its rows as it is drawn
        finally:
            QtCore.qInstallMessageHandler(previous)

        self.assertEqual([], said, "the sidebar's QML reported errors or warnings")
        trees = [item for item in panel.view.rootObject().findChildren(QtQuick.QQuickItem)
                 if item.metaObject().className().startswith("SidebarTree")]
        self.assertEqual(1, len(trees), "the pane has not one sidebar tree")
        engine = panel.pane.sidebar
        section = panel.pane.active_section()
        self.assertIs(getattr(panel.pane, section.sidebar_attr), engine.model,
                      "the engine does not show the section's own sidebar rows")
        self.assertGreater(engine.model.rowCount(), 1, "the fixture's section has no rows below All")
        self.assertEqual(engine.model.rowCount(), trees[0].property("rows"),
                         "the tree does not show every row of the section's sidebar")
        self.assertIs(engine.selection, trees[0].property("selectionModel"),
                      "the tree keeps a selection other than the one the engine moves")

    def test_the_grid_loads_silently_and_shows_the_sections_tiles(self):
        test_support.fixture_panel(self)
        said = []

        def hear(_kind, context, text):
            if ".qml" in text or context.category in ("qml", "js"):
                said.append(text)

        previous = QtCore.qInstallMessageHandler(hear)
        try:
            panel = qml_pane.QmlPanel()
            self.addCleanup(test_support.stop_panel_workers, panel)
            self.addCleanup(QtCore.QCoreApplication.sendPostedEvents, None, QtCore.QEvent.Type.DeferredDelete)
            self.addCleanup(panel.deleteLater)
            panel.setAttribute(QtCore.Qt.WidgetAttribute.WA_DontShowOnScreen)
            panel.resize(840, 420)
            panel.show()
            QtWidgets.QApplication.processEvents()
            panel.view.grabFramebuffer()    # a frame: the grid makes its tiles as it is drawn
            QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)    # as Houdini's loop
        finally:
            QtCore.qInstallMessageHandler(previous)

        self.assertEqual([], said, "the grid's QML reported errors or warnings")

        def walk(item):
            yield item
            for child in item.childItems():
                yield from walk(child)

        views = [item for item in walk(panel.view.rootObject())
                 if item.metaObject().className().startswith("QQuickGridView")]
        self.assertEqual(1, len(views), "the pane has not one tile grid")
        section = panel.pane.active_section()
        proxy = getattr(panel.pane, section.proxy_attr)
        self.assertIs(proxy, views[0].property("model"), "the grid does not show the section's own tiles")
        tiles = [item for item in views[0].property("contentItem").childItems()
                 if item.metaObject().className().startswith("Tile_")]
        self.assertGreater(proxy.rowCount(), 1, "the fixture's section has no tiles")
        self.assertEqual(proxy.rowCount(), len(tiles), "the grid does not show every tile of the section")

    def test_the_list_shows_the_rows_in_its_sections_columns_and_keeps_the_grids_selection(self):
        test_support.fixture_panel(self)
        said = []

        def hear(_kind, context, text):
            if ".qml" in text or context.category in ("qml", "js"):
                said.append(text)

        previous = QtCore.qInstallMessageHandler(hear)
        try:
            panel = qml_pane.QmlPanel()
            self.addCleanup(test_support.stop_panel_workers, panel)
            self.addCleanup(QtCore.QCoreApplication.sendPostedEvents, None, QtCore.QEvent.Type.DeferredDelete)
            self.addCleanup(panel.deleteLater)
            self.addCleanup(panel.pane.set_view_mode, "grid")    # the prefs the fixture's panels share
            panel.setAttribute(QtCore.Qt.WidgetAttribute.WA_DontShowOnScreen)
            panel.resize(2000, 420)    # wide enough for Qt to lay out every column
            panel.show()
            panel.state.setViewMode("list")
            QtWidgets.QApplication.processEvents()
            panel.view.grabFramebuffer()    # a frame: the table makes its cells as it is drawn
            QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)    # as Houdini's loop
        finally:
            QtCore.qInstallMessageHandler(previous)
        self.assertEqual([], said, "the list's QML reported errors or warnings")

        def views(kind):
            found, items = [], [panel.view.rootObject()]
            while items:
                item = items.pop()
                found += [item] if item.metaObject().className().startswith(kind) else []
                items += item.childItems()
            return found

        def laid_out():    # the headings Qt gave a width, which an empty list has too
            header, = views("HorizontalHeaderView")
            return [key for column, key in enumerate(grid_columns.KEYS) if 0 < QtCore.QMetaObject.invokeMethod(
                header, "columnWidth", QtCore.Qt.ConnectionType.DirectConnection,
                QtCore.Q_RETURN_ARG("qreal"), QtCore.Q_ARG(int, column))]

        for number, (key, _label) in enumerate(panel.pane.tabs()):
            panel.state.chooseTab(number)
            QtWidgets.QApplication.processEvents()
            panel.view.grabFramebuffer()
            table, = views("QQuickTableView")
            proxy = getattr(panel.pane, panel.pane.active_section().proxy_attr)
            self.assertIs(proxy, table.property("model"), "the %s list does not show its section's rows" % key)
            self.assertEqual(list(panel.pane.active_section().shown_list_columns()), laid_out(),
                             "the %s list's columns are not its section's" % key)

        panel.state.chooseTab(0)
        QtWidgets.QApplication.processEvents()
        panel.view.grabFramebuffer()
        selection = panel.pane.active_section().grid_selection_model()
        self.assertGreater(selection.model().rowCount(), 3, "the first section has too few rows to pick two")
        self.assertEqual(selection.model().rowCount(), views("QQuickTableView")[0].property("rows"), "the list lacks rows")
        panel.state.clickTile(1, 0)
        panel.state.clickTile(3, QtCore.Qt.KeyboardModifier.ControlModifier.value)
        for mode in ("grid", "list"):
            panel.state.setViewMode(mode)
            QtWidgets.QApplication.processEvents()
            panel.view.grabFramebuffer()
            QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
            self.assertEqual([1, 3], sorted(index.row() for index in grid_columns.selected_rows(selection)),
                             "switching to %s mode changed the one selection" % mode)
        table, = views("QQuickTableView")
        self.assertIs(selection, table.property("selectionModel"), "the list keeps a selection of its own")


if __name__ == "__main__":
    unittest.main()
