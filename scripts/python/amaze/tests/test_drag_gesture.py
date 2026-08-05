"""The self-managed drag gesture, replayed headlessly.

Dragging is the app's busiest workflow and its least reachable code:
every path runs inside mouse handlers, so verifying it has meant
dragging tiles onto viewports by hand. The debug log's only slot
crashes - six of them - are all in mouseReleaseEvent.

These tests synthesise real QMouseEvents against the real
DragDropListView and assert the STATE MACHINE holds: what arms a drag,
what must not, and that every exit path leaves the widget clean. A
gesture that ends with _dragging still True eats the next click.

The release ACTION (import, assign, recategorise) is deliberately
stubbed - what is under test here is the gesture, not the drop.
"""

import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.panel import dragdrop_widgets  # noqa: E402
from amaze.tests import test_support  # noqa: E402,F401 - import redirects the debug log


class _StubPanel(QtWidgets.QWidget):
    """Everything the gesture asks its panel for, recorded."""

    def __init__(self, section="material"):
        super().__init__()
        self.current_section = section
        self.calls = []
        self.hover_rows = []
        self._category = None
        self._node = None
        # The File section's release dispatch reads the row KIND
        # through this attribute; the harness stamps kinds onto its
        # QStandardItems under the same role number.
        from amaze.core import file_library
        self.file_files_model = file_library.FileFiles

    # _find_panel duck-types on this attribute to recognise the panel
    # while walking up the parent chain - a stub without it is simply
    # not found, and the gesture never arms.
    def import_asset(self, *args, **kwargs):
        self.calls.append("import_asset")

    # -- what mousePressEvent / mouseMoveEvent consult ----------------
    def _is_online(self):
        return False

    def _set_drag_hover_row(self, row):
        self.hover_rows.append(row)

    def _category_under_cursor(self):
        return self._category

    def _node_under_cursor(self):
        return self._node

    def _ui_icon_path(self, filename):
        """The miss indicator asks the panel where its icons live."""
        import amaze
        return os.path.join(os.path.dirname(amaze.__file__), "ui", filename)

    # -- the release actions, stubbed ---------------------------------
    def drop_material_at_release(self, idx):
        self.calls.append("material")
        return True

    def drop_cop_at_release(self, idx):
        self.calls.append("cop")
        return True

    def drop_geo_at_release(self, idx):
        self.calls.append("geo")
        return True

    def assign_category_active(self, category):
        self.calls.append("category:%s" % category)

    def apply_gradient_to_node(self, idx, node):
        self.calls.append("gradient")

    def drop_code_at_release(self, idx, node):
        self.calls.append("code")


def _event(kind, pos, button=QtCore.Qt.MouseButton.LeftButton,
           buttons=None):
    return QtGui.QMouseEvent(
        kind, QtCore.QPointF(pos), button,
        buttons if buttons is not None else button,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )


class _Harness:
    """A real DragDropListView with a model, wired to a stub panel."""

    def __init__(self, testcase, section="material", rows=6,
                 kind=None):
        self.view = dragdrop_widgets.DragDropListView()
        testcase.addCleanup(self.view.deleteLater)
        model = QtGui.QStandardItemModel()
        from amaze.core import file_library
        for i in range(rows):
            item = QtGui.QStandardItem("asset_%d" % i)
            if kind is not None:
                item.setData(kind, file_library.FileFiles.KindRole)
            model.appendRow(item)
        self.view.setModel(model)
        self.view.resize(400, 300)
        self.panel = _StubPanel(section)
        testcase.addCleanup(self.panel.deleteLater)
        # _find_panel walks the parent chain; parenting the view to the
        # stub is how the real panel provides itself.
        self.view.setParent(self.panel)
        self.view.show()

    def item_pos(self, row=0):
        return self.view.visualRect(self.view.model().index(row, 0)).center()

    def press(self, pos=None):
        self.view.mousePressEvent(_event(
            QtCore.QEvent.Type.MouseButtonPress, pos or self.item_pos()))

    def move(self, pos):
        self.view.mouseMoveEvent(_event(
            QtCore.QEvent.Type.MouseMove, pos,
            QtCore.Qt.MouseButton.NoButton,
            QtCore.Qt.MouseButton.LeftButton))

    def release(self, pos=None):
        self.view.mouseReleaseEvent(_event(
            QtCore.QEvent.Type.MouseButtonRelease, pos or self.item_pos()))


class TestGestureArming(unittest.TestCase):

    def test_press_on_an_item_arms_the_drag(self):
        h = _Harness(self)
        h.press()
        self.assertIsNotNone(h.view._drag_start)
        self.assertEqual(h.view._drag_section, "material")
        self.assertTrue(h.view._drag_index.isValid())

    def test_press_on_empty_space_does_not_arm(self):
        """A press on empty grid used to arm anyway, producing a ghost
        drag whose invalid index reached the release handlers."""
        h = _Harness(self, rows=1)
        h.press(QtCore.QPoint(380, 280))
        self.assertIsNone(h.view._drag_start)
        self.assertIsNone(h.view._drag_index)

    def test_right_press_does_not_arm(self):
        h = _Harness(self)
        h.view.mousePressEvent(_event(
            QtCore.QEvent.Type.MouseButtonPress, h.item_pos(),
            QtCore.Qt.MouseButton.RightButton))
        self.assertIsNone(h.view._drag_start)

    def test_press_while_dragging_keeps_the_live_state(self):
        """A stray right/middle press mid-gesture must not clear the
        drag - that lost the drop and left the sidebar glowing."""
        h = _Harness(self)
        h.press()
        h.view._dragging = True
        armed = h.view._drag_index
        h.view.mousePressEvent(_event(
            QtCore.QEvent.Type.MouseButtonPress, h.item_pos(1),
            QtCore.Qt.MouseButton.RightButton))
        self.assertTrue(h.view._dragging)
        self.assertEqual(h.view._drag_index, armed)


class TestGestureRelease(unittest.TestCase):

    def _armed(self, section="material", kind=None):
        h = _Harness(self, section, kind=kind)
        h.press()
        h.view._dragging = True          # as mouseMoveEvent would set
        h.view._drag_panel = h.panel
        return h

    def test_release_dispatches_to_the_section(self):
        for section, kind, expected in (
                ("material", None, "material"),
                ("cop", None, "cop"),
                # Geometry is a KIND inside the File section since the
                # merge - the release must reach the same import
                # handler it always did.
                ("file", "geometry", "geo")):
            h = self._armed(section, kind=kind)
            h.release()
            self.assertIn(expected, h.panel.calls,
                          "%s release did not dispatch" % section)

    def test_release_always_clears_the_gesture(self):
        """Every exit path: a gesture that ends with _dragging True
        eats the next click."""
        h = self._armed()
        h.release()
        self.assertFalse(h.view._dragging)
        self.assertIn(-1, h.panel.hover_rows,
                      "the drop-target glow was not cleared")

    def test_release_over_a_category_recategorises_instead(self):
        h = self._armed()
        h.panel._category = "Metal"
        h.release()
        self.assertIn("category:Metal", h.panel.calls)
        self.assertNotIn("material", h.panel.calls,
                         "a category drop also ran the material import")

    def test_release_over_nothing_is_silent_and_clean(self):
        h = self._armed("gradient")
        h.panel._node = None             # nothing under the cursor
        h.release()
        self.assertEqual(h.panel.calls, [])
        self.assertFalse(h.view._dragging)

    def test_a_failing_drop_still_clears_the_gesture(self):
        """The six logged slot crashes were all in release. Whatever
        the action raises, the gesture must not stay armed - or the
        panel is dead until the next panel reopen."""
        h = self._armed()

        def _boom(idx):
            raise hou.OperationFailed("Invalid node type name")

        h.panel.drop_material_at_release = _boom
        with self.assertRaises(hou.OperationFailed):
            h.release()                  # guarded() re-raises by design
        self.assertFalse(h.view._dragging,
                         "a raising drop left the gesture armed")

    def test_a_LOCKED_asset_is_reported_not_crashed(self):
        """Houdini REFUSING is not a bug, and it reached Qt as one.

        Dropping a material into a locked asset raises
        `hou.PermissionError("Cannot create a node inside a locked
        asset")`. Nothing caught it: the exception left
        mouseReleaseEvent, Qt logged a slot crash, and the user saw a
        drop that silently did nothing. Five times in one session on
        2026-08-03, found by reading the debug log rather than by any
        test.

        It gets the gesture's own vocabulary for a drop that did not
        land - the tag flies back - plus Houdini's own sentence for
        why, on the status bar. No dialog.
        """
        h = self._armed()
        said = []

        def _locked(idx):
            raise hou.PermissionError(
                "Cannot create a node inside a locked asset")

        h.panel.drop_material_at_release = _locked
        # hou.ui is absent headless, so it is STOOD UP here rather than
        # patched - which also proves the handler reaches it when it
        # exists. The guard for when it does not is the test below.
        stub = type("_UI", (), {"setStatusMessage":
                                staticmethod(
                                    lambda *a, **k: said.append(a[0]))})()
        with mock.patch.object(hou, "ui", stub, create=True):
            h.release()                  # must NOT raise

        self.assertFalse(h.view._dragging,
                         "a refused drop left the gesture armed")
        self.assertTrue(said, "the refusal was swallowed silently - the "
                              "user sees a drop that did nothing")
        self.assertIn(
            "locked asset", said[0],
            "the message does not say WHY the drop did not land: %r"
            % said[0])

    def test_a_headless_session_still_absorbs_the_refusal(self):
        """`hou.ui` does not exist without a UI, and an AttributeError
        raised inside this handler would turn the refusal it absorbs
        back into the slot crash it prevents."""
        h = self._armed()

        def _locked(idx):
            raise hou.PermissionError(
                "Cannot create a node inside a locked asset")

        h.panel.drop_material_at_release = _locked
        self.assertFalse(hasattr(hou, "ui"),
                         "this test needs a headless hou to mean anything")
        h.release()                      # must NOT raise
        self.assertFalse(h.view._dragging)

    def test_a_REAL_error_still_raises(self):
        """The other half. Only Houdini's refusal is caught; a genuine
        programming error must still crash where it can be seen, or the
        catch becomes the bare `except Exception` that makes a failure
        indistinguishable from an honest empty result."""
        h = self._armed()

        def _bug(idx):
            raise hou.OperationFailed("Invalid node type name")

        h.panel.drop_material_at_release = _bug
        with self.assertRaises(hou.OperationFailed):
            h.release()

    def test_a_failing_drop_clears_the_PRESS_state_too(self):
        """_dragging is not the whole gesture.

        It is cleared before the try block, so the test above passes even
        when the four press-state fields survive - and those are what
        mouseMoveEvent measures against. A raising drop left _drag_start,
        _drag_section, _drag_panel and _drag_index set, and the method's
        own comment describes what that costs: a later hover move with NO
        button held measures a large distance from the stale start point
        and launches a drag the user never began."""
        h = self._armed()
        h.panel.drop_material_at_release = self._boom
        with self.assertRaises(hou.OperationFailed):
            h.release()

        leaked = {
            "_drag_start": h.view._drag_start,
            "_drag_section": h.view._drag_section,
            "_drag_panel": h.view._drag_panel,
            "_drag_index": h.view._drag_index,
        }
        still_set = {k: v for k, v in leaked.items() if v is not None}
        self.assertEqual(
            {}, still_set,
            "a raising drop left press state armed: %s - the next hover "
            "move launches a phantom drag" % sorted(still_set))

    def test_a_phantom_drag_cannot_start_after_a_failing_drop(self):
        """The behaviour the leak causes, end to end: no button held,
        just a mouse move, and a full gesture arms itself."""
        h = self._armed()
        h.panel.drop_material_at_release = self._boom
        with self.assertRaises(hou.OperationFailed):
            h.release()

        h.move(QtCore.QPoint(h.item_pos().x() + 200,
                             h.item_pos().y() + 200))
        self.assertFalse(
            h.view._dragging,
            "a bare hover move started a drag the user never began")

    def test_a_failing_drop_cannot_carry_its_section_into_another(self):
        """Worse than a phantom drag: the stale gesture keeps the OLD
        section, so a release after switching sections dispatches the
        wrong handler with an index into the wrong model."""
        h = self._armed("material")
        h.panel.drop_material_at_release = self._boom
        with self.assertRaises(hou.OperationFailed):
            h.release()
        h.panel.calls.clear()

        h.panel.section = "geometry"     # the user switched tabs
        h.move(QtCore.QPoint(h.item_pos().x() + 200,
                             h.item_pos().y() + 200))
        h.release()
        self.assertNotIn(
            "material", h.panel.calls,
            "a stale gesture dispatched the previous section's handler "
            "after the user had switched sections")

    def _release_with(self, harness, button):
        harness.view.mouseReleaseEvent(_event(
            QtCore.QEvent.Type.MouseButtonRelease,
            harness.item_pos(), button))

    def test_a_right_click_cancels_the_drag_instead_of_dropping(self):
        """mousePressEvent already swallows a stray right press
        mid-gesture; the release handler did not filter by button, so
        right-clicking to back out PERFORMED the drop wherever the
        cursor happened to be - a real import or assignment."""
        h = self._armed()
        self._release_with(h, QtCore.Qt.MouseButton.RightButton)
        self.assertEqual(
            [], h.panel.calls,
            "a right-button release performed the drop")
        self.assertFalse(h.view._dragging,
                         "the cancelled gesture stayed armed")
        self.assertIsNone(h.view._drag_start,
                          "the cancelled gesture left press state behind")

    def test_a_middle_click_cancels_too(self):
        h = self._armed()
        self._release_with(h, QtCore.Qt.MouseButton.MiddleButton)
        self.assertEqual([], h.panel.calls)

    def test_the_left_button_still_drops(self):
        """The filter must not break the only gesture that matters."""
        h = self._armed()
        self._release_with(h, QtCore.Qt.MouseButton.LeftButton)
        self.assertIn("material", h.panel.calls,
                      "a normal left release stopped dropping")

    @staticmethod
    def _boom(idx):
        raise hou.OperationFailed("Invalid node type name")

    def test_release_without_a_press_is_harmless(self):
        h = _Harness(self)
        h.release()
        self.assertFalse(h.view._dragging)
        self.assertEqual(h.panel.calls, [])


class GuardedSlotsTest(unittest.TestCase):
    """Every Qt event handler this project overrides must be wrapped.

    research.md: *PySide swallows exceptions in Qt slots before
    sys.excepthook* - so an exception in an unwrapped handler vanishes
    entirely: no log record, no traceback, and the gesture half-done.
    `debug.guarded` records it (crash tier, Debug Mode or not) and
    re-raises, which is the only reason those six release crashes in the
    real log were readable at all.

    Checked on the ATTRIBUTE, not in the source: `guarded` wraps with
    functools.wraps, so a wrapped handler carries `__wrapped__` and an
    unwrapped one does not. A grep for the decorator line would also
    match it inside a docstring or a comment - and this file's own
    module docstring names it twice.

    It does NOT protect against a SIGSEGV. research.md is explicit that
    a segfault bypasses guarded(), the excepthook and every `except` in
    the codebase, because the process is dying rather than raising.
    """

    #: Qt handlers whose bodies run project code. paintEvent and
    #: sizeHint are deliberately absent: they are pure painting and
    #: measurement, called from Qt's own layout pass, and wrapping them
    #: would put a log write in a repaint loop.
    HANDLERS = (
        "mousePressEvent", "mouseMoveEvent", "mouseReleaseEvent",
        "dragEnterEvent", "dragMoveEvent", "dropEvent",
    )

    def _widget_classes(self):
        """The project's own QWidget subclasses, from the two modules
        that carry the gesture and the shared controls."""
        from amaze.helpers import ui_helpers

        found = []
        for module in (dragdrop_widgets, ui_helpers):
            for name in dir(module):
                value = getattr(module, name)
                if not (isinstance(value, type)
                        and value.__module__ == module.__name__):
                    continue
                # A QWidget, OR any class that defines a Qt handler.
                # The gesture moved onto a plain MIXIN 2026-08-04 so it
                # could serve both the list and the table view - and a
                # QWidget-only scan stopped seeing its slots at all,
                # which is a guard silently switching itself off. The
                # property is "an overridden handler is wrapped",
                # wherever it is defined.
                if issubclass(value, QtWidgets.QWidget) or any(
                        handler in value.__dict__
                        for handler in self.HANDLERS):
                    found.append(value)
        return found

    def test_every_overridden_handler_is_wrapped(self):
        classes = self._widget_classes()
        self.assertTrue(classes, "no widget classes found - this test is "
                                 "not looking where it thinks it is")
        checked, unwrapped = 0, []
        for cls in classes:
            for handler in self.HANDLERS:
                function = cls.__dict__.get(handler)
                if function is None:
                    continue            # inherited, not overridden here
                checked += 1
                if not hasattr(function, "__wrapped__"):
                    unwrapped.append("%s.%s" % (cls.__name__, handler))
        self.assertGreaterEqual(
            checked, 8,
            "only %d overridden handlers found - the scan is missing the "
            "classes it was written for" % checked)
        self.assertEqual(
            [], unwrapped,
            "unguarded Qt slot(s): an exception in one of these is "
            "swallowed by PySide with nothing in the log - %s"
            % ", ".join(unwrapped))

    def test_a_guarded_handler_still_returns_what_the_body_returns(self):
        """A wrapper that ate the return value would break every handler
        that ends `return super().mousePressEvent(e)` - ClickSlider's
        does, and a swallowed return changes the event's accept path."""
        from amaze.core import debug

        @debug.guarded("Probe.mousePressEvent")
        def handler(_self, value):
            return ("body ran", value)

        self.assertEqual(("body ran", 7), handler(None, 7))

    def test_a_guarded_handler_re_raises(self):
        """The wrapper RECORDS and re-raises; swallowing here would turn
        a crash into a silently half-finished gesture."""
        from amaze.core import debug

        @debug.guarded("Probe.mouseReleaseEvent")
        def handler(_self):
            raise ValueError("boom")

        with self.assertRaises(ValueError):
            handler(None)


if __name__ == "__main__":
    unittest.main()


class TheGestureRunsOnBOTHViews(unittest.TestCase):
    """Step 2 of the QTableView migration. List mode is becoming a real
    table, and the self-managed gesture has to run there too - a second
    copy of a 541-line press-move-release cycle is not an option, and a
    real QDrag is not either (it traps the gesture in a nested run loop
    where the per-move viewport picking cannot run - tried, shipped,
    reverted, re-verified; devlog #80).

    So it is a MIXIN over QAbstractItemView, and these pin that both
    views actually get it.
    """

    VIEWS = ("DragDropListView", "DragDropTableView")

    def test_both_views_are_built_on_the_one_gesture(self):
        for name in self.VIEWS:
            with self.subTest(view=name):
                view = getattr(dragdrop_widgets, name)
                self.assertTrue(
                    issubclass(view, dragdrop_widgets.GridGestureMixin),
                    "%s does not carry the shared gesture" % name)

    def test_neither_view_redefines_a_gesture_handler(self):
        """A second copy is the thing this shape exists to prevent."""
        for name in self.VIEWS:
            view = getattr(dragdrop_widgets, name)
            for handler in ("mousePressEvent", "mouseMoveEvent",
                            "mouseReleaseEvent", "_release", "_begin_drag"):
                with self.subTest(view=name, handler=handler):
                    self.assertNotIn(
                        handler, view.__dict__,
                        "%s defines its own %s - the gesture is shared, "
                        "or it is not one gesture" % (name, handler))

    def test_the_table_view_carries_the_arming_rules(self):
        """The rules are class data on the mixin; a view that lost them
        would arm on nothing, or on everything."""
        table = dragdrop_widgets.DragDropTableView
        self.assertEqual(dragdrop_widgets.GridGestureMixin.ARMED_SECTIONS,
                         table.ARMED_SECTIONS)
        self.assertEqual(
            dragdrop_widgets.GridGestureMixin.NODE_TARGET_SECTIONS,
            table.NODE_TARGET_SECTIONS)

    def test_the_table_view_selects_ROWS_and_MANY(self):
        """QTableView defaults to ExtendedSelection where QListView
        defaults to Single - measured. The grid is multi-select, so the
        table says so rather than inheriting a difference."""
        view = dragdrop_widgets.DragDropTableView()
        self.addCleanup(view.deleteLater)
        self.assertEqual(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection,
            view.selectionMode())
        self.assertEqual(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows,
            view.selectionBehavior())

    def test_the_table_view_hides_the_row_numbers(self):
        """A vertical header of row numbers is a table's default and
        has no meaning here - the row IS the asset."""
        view = dragdrop_widgets.DragDropTableView()
        self.addCleanup(view.deleteLater)
        self.assertFalse(view.verticalHeader().isVisible())
        self.assertFalse(view.showGrid(),
                         "the table paints Qt's own grid lines over a "
                         "row that draws its own dividers")

    def test_the_debug_helper_survives_a_view_with_no_gridSize(self):
        """The one QListView-only call in 541 lines. A table has no
        grid size, and this runs inside the scroll path."""
        view = dragdrop_widgets.DragDropTableView()
        self.addCleanup(view.deleteLater)
        self.assertFalse(hasattr(view, "gridSize"))
        view.setModel(QtGui.QStandardItemModel(3, 1))
        # Debug-gated, so it only runs with Debug Mode on - which is
        # exactly when a crash in it would be least welcome.
        from amaze.core import debug as debug_mod
        was_on = debug_mod.is_on()
        debug_mod.configure(True)
        self.addCleanup(debug_mod.configure, was_on)
        view._log_scroll_geometry(          # must not raise
            None, view.verticalScrollBar(), 0, 0)
