"""The drag gesture replayed headlessly - real `QMouseEvent`s against the real view, asserting the STATE MACHINE, because a gesture ending with `_dragging` still True eats the next click. The drop ACTION is stubbed; the gesture is what is under test. ▸archive/test_drag_gesture.py"""

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
    """Everything the gesture asks its panel for, recorded. `_find_panel` duck-types on `import_asset` to recognise it, and the release VERBS are not here - they are the section's."""

    def __init__(self, section="material"):
        super().__init__()
        self.current_section = section
        self.calls = []
        self.hover_rows = []
        self._category = None
        self._node = None
        self._network = None    # None = released over nothing; empty network space is a sentinel
        self._file_path_outcome = True
        from amaze.core import file_library
        self.file_files_model = file_library.FileFiles

    def import_asset(self, *args, **kwargs):
        self.calls.append("import_asset")

    def _is_online(self):
        return False

    def _set_drag_hover_row(self, row):
        self.hover_rows.append(row)

    def _category_under_cursor(self):
        return self._category

    def _update_category_drag_hover_global(self):
        """Every drag walks the live move path that drives the sidebar hover glow."""

    def _node_under_cursor(self):
        return self._node

    def _ui_icon_path(self, filename):
        """The miss indicator asks the panel where its icons live."""
        import amaze
        return os.path.join(os.path.dirname(amaze.__file__), "ui", filename)

    def assign_category_active(self, category):
        self.calls.append("category:%s" % category)

    def _network_under_release(self):
        return self._network

    def _release_position(self):
        return None

    def _release_position_in(self, net):
        """The gated resolver the engine passes to creation doors."""
        return None


def _event(kind, pos, button=QtCore.Qt.MouseButton.LeftButton,
           buttons=None, global_pos=None):
    if global_pos is not None:
        # The short ctor reads the LIVE cursor, which headless cannot aim.
        return QtGui.QMouseEvent(
            kind, QtCore.QPointF(pos), QtCore.QPointF(pos),
            QtCore.QPointF(global_pos), button,
            buttons if buttons is not None else button,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )
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
        # Real section over the stub panel, verbs stubbed on the INSTANCE.
        from amaze.panel import sections
        self.section = sections.SECTION_INDEX[section](self.panel)
        self.panel.sections = {section: self.section}
        calls = self.panel.calls
        if section == "material":
            def _material(idx):
                calls.append("material")
                return True
            self.section.drop_material_at_release = _material
        elif section == "cop":
            def _cop(idx):
                calls.append("cop")
                return True
            self.section.drop_cop_at_release = _cop
        elif section == "file":
            def _geo(idx):
                calls.append("geo")
                return True

            def _open_hip(idx):
                calls.append("open_hip")

            def _file_path(idx, node):
                calls.append("file_path")
                return self.panel._file_path_outcome

            def _create_image(idx, dest, position=None):
                calls.append("create_image")
                return dest is not None
            self.section.drop_geo_at_release = _geo
            self.section.open_hip_scene = _open_hip
            self.section.drop_file_path_on_node = _file_path
            self.section.create_image_node_in = _create_image
        elif section == "gradient":
            def _gradient(idx, node):
                calls.append("gradient")

            def _create_gradient(idx, dest, position=None):
                calls.append("create_gradient")
                return dest is not None
            self.section.apply_gradient_to_node = _gradient
            self.section.create_gradient_node_in = _create_gradient
        elif section == "code":
            def _code(idx, node):
                calls.append("code")

            def _create_code(idx, dest, position=None):
                calls.append("create_code")
                return dest is not None
            self.section.drop_code_at_release = _code
            self.section.create_code_node_in = _create_code
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

    def release(self, pos=None, global_pos=None):
        self.view.mouseReleaseEvent(_event(
            QtCore.QEvent.Type.MouseButtonRelease, pos or self.item_pos(),
            global_pos=global_pos))


class TestGestureArming(unittest.TestCase):

    def test_press_on_an_item_arms_the_drag(self):
        h = _Harness(self)
        h.press()
        self.assertIsNotNone(h.view._drag_start)
        self.assertEqual(h.view._drag_section, "material")
        self.assertTrue(h.view._drag_index.isValid())

    def test_press_on_empty_space_does_not_arm(self):
        """A press on empty grid must not arm - a ghost drag carries an invalid index into the release handlers."""
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
        """A stray right or middle press mid-gesture must not clear the drag, or the drop is lost and the sidebar stays glowing."""
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
                # Geometry is a KIND in the File section, same import handler.
                ("file", "geometry", "geo")):
            h = self._armed(section, kind=kind)
            h.release()
            self.assertIn(expected, h.panel.calls,
                          "%s release did not dispatch" % section)

    def test_release_always_clears_the_gesture(self):
        """Every exit path - a gesture ending with `_dragging` True eats the next click."""
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
        """Whatever the drop raises, the gesture must not stay armed - or the panel is dead until it is reopened."""
        h = self._armed()

        def _boom(idx):
            raise hou.OperationFailed("Invalid node type name")

        h.section.drop_material_at_release = _boom
        with self.assertRaises(hou.OperationFailed):
            h.release()                  # guarded() re-raises by design
        self.assertFalse(h.view._dragging,
                         "a raising drop left the gesture armed")

    def test_a_LOCKED_asset_is_reported_not_crashed(self):
        """Houdini REFUSING is not a bug: a locked asset raises `hou.PermissionError`, and uncaught that reads as a slot crash and a drop that silently did nothing. It gets the gesture's own refusal - the tag flies back - and Houdini's sentence on the status bar. No dialog. ▸p/dialogs-are-a-bill"""
        h = self._armed()
        said = []

        def _locked(idx):
            raise hou.PermissionError(
                "Cannot create a node inside a locked asset")

        h.section.drop_material_at_release = _locked
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
        """`hou.ui` does not exist without a UI, and an `AttributeError` here turns the refusal back into the slot crash it prevents."""
        h = self._armed()

        def _locked(idx):
            raise hou.PermissionError(
                "Cannot create a node inside a locked asset")

        h.section.drop_material_at_release = _locked
        self.assertFalse(hasattr(hou, "ui"),
                         "this test needs a headless hou to mean anything")
        h.release()                      # must NOT raise
        self.assertFalse(h.view._dragging)

    def test_a_REAL_error_still_raises(self):
        """Only Houdini's refusal is caught - a real programming error must still crash where it can be seen."""
        h = self._armed()

        def _bug(idx):
            raise hou.OperationFailed("Invalid node type name")

        h.section.drop_material_at_release = _bug
        with self.assertRaises(hou.OperationFailed):
            h.release()

    def test_a_failing_drop_clears_the_PRESS_state_too(self):
        """`_dragging` is not the whole gesture - the four press-state fields are what move measures against, and left set, a later hover with no button held launches a drag nobody began."""
        h = self._armed()
        h.section.drop_material_at_release = self._boom
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
        """End to end: no button held, just a move, and a full gesture arms itself."""
        h = self._armed()
        h.section.drop_material_at_release = self._boom
        with self.assertRaises(hou.OperationFailed):
            h.release()

        h.move(QtCore.QPoint(h.item_pos().x() + 200,
                             h.item_pos().y() + 200))
        self.assertFalse(
            h.view._dragging,
            "a bare hover move started a drag the user never began")

    def test_a_failing_drop_cannot_carry_its_section_into_another(self):
        """A stale gesture keeps the OLD section, so a release after switching dispatches the wrong handler with an index into the wrong model."""
        h = self._armed("material")
        h.section.drop_material_at_release = self._boom
        with self.assertRaises(hou.OperationFailed):
            h.release()
        h.panel.calls.clear()

        h.panel.current_section = "file"
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
        """The release handler must filter by BUTTON, or right-clicking to back out performs the drop wherever the cursor is."""
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


class FileRowsReleaseOnNodes(unittest.TestCase):
    """Image, unknown and geometry rows ride the same gesture and a release on a node hands over the spelled path - geometry falls back to its import, image and unknown MISS."""

    def _drag(self, harness):
        harness.press()
        start = harness.item_pos()
        harness.move(QtCore.QPoint(start.x() + 60, start.y() + 60))

    def test_an_image_release_on_a_node_hands_over_the_path(self):
        from amaze.core import file_library
        h = _Harness(self, section="file", kind=file_library.KIND_IMAGE)
        h.panel._node = object()
        self._drag(h)
        h.release()
        self.assertEqual(["file_path"], h.panel.calls)

    def test_an_unknown_row_behaves_exactly_like_an_image(self):
        from amaze.core import file_library
        h = _Harness(self, section="file", kind=file_library.KIND_OTHER)
        h.panel._node = object()
        self._drag(h)
        h.release()
        self.assertEqual(["file_path"], h.panel.calls)

    def test_an_image_on_empty_network_space_runs_the_creation_rule(self):
        from amaze.core import file_library
        h = _Harness(self, section="file", kind=file_library.KIND_IMAGE)
        h.panel._network = object()
        self._drag(h)
        h.release()
        self.assertEqual(["create_image"], h.panel.calls,
                         "an image released on empty network space "
                         "must run the creation rule")
        self.assertFalse(h.view._dragging, "the gesture stayed live")

    def test_an_image_over_nothing_at_all_is_a_silent_miss(self):
        from amaze.core import file_library
        h = _Harness(self, section="file", kind=file_library.KIND_IMAGE)
        self._drag(h)
        h.release()
        self.assertEqual([], h.panel.calls,
                         "off any editor there is no network and "
                         "nothing is consulted")

    def test_an_unknown_file_on_no_node_is_still_a_miss(self):
        from amaze.core import file_library
        h = _Harness(self, section="file", kind=file_library.KIND_OTHER)
        self._drag(h)
        h.release()
        self.assertEqual([], h.panel.calls,
                         "an unknown file has no creation rule")

    def test_a_gradient_on_empty_network_space_runs_the_creation_rule(self):
        h = _Harness(self, section="gradient")
        h.panel._network = object()
        self._drag(h)
        h.release()
        self.assertEqual(["create_gradient"], h.panel.calls)

    def test_a_gradient_on_a_node_hands_over_instead(self):
        h = _Harness(self, section="gradient")
        h.panel._node = object()
        self._drag(h)
        h.release()
        self.assertEqual(["gradient"], h.panel.calls)

    def test_code_on_empty_network_space_runs_the_creation_rule(self):
        h = _Harness(self, section="code")
        h.panel._network = object()
        self._drag(h)
        h.release()
        self.assertEqual(["create_code"], h.panel.calls)

    def test_a_node_that_takes_nothing_is_a_MISS_for_geometry_too(self):
        """ONE rule on nodes - a refused hand-over does not quietly become an import beside the node."""
        from amaze.core import file_library
        h = _Harness(self, section="file", kind=file_library.KIND_GEO)
        h.panel._node = object()
        h.panel._file_path_outcome = False
        self._drag(h)
        h.release()
        self.assertEqual(["file_path"], h.panel.calls,
                         "a refused node hand-over ran another verb")

    def test_geometry_on_a_node_hands_over_like_everything_else(self):
        from amaze.core import file_library
        h = _Harness(self, section="file", kind=file_library.KIND_GEO)
        h.panel._node = object()
        self._drag(h)
        h.release()
        self.assertEqual(["file_path"], h.panel.calls)

    def test_geometry_on_no_node_imports(self):
        from amaze.core import file_library
        h = _Harness(self, section="file", kind=file_library.KIND_GEO)
        self._drag(h)
        h.release()
        self.assertEqual(["geo"], h.panel.calls,
                         "the no-node release lost the geometry import")

    def test_hip_on_a_node_hands_over_like_everything_else(self):
        from amaze.core import file_library
        h = _Harness(self, section="file", kind=file_library.KIND_HIP)
        h.panel._node = object()
        self._drag(h)
        h.release()
        self.assertEqual(["file_path"], h.panel.calls,
                         "a hip on a node must hand over the path, "
                         "not load the scene")


class TheBehaviourTableCells(unittest.TestCase):
    """One cell per release situation - `(section, row kind, what is under the release)` and its expected dispatch, over every aim state."""

    CELLS = (
        ("material aims itself", "material", None,
         dict(node=True), ["material"]),
        ("material over nothing still aims itself", "material", None,
         dict(), ["material"]),
        ("node networks aim themselves", "cop", None,
         dict(), ["cop"]),
        ("a gradient hands to the node", "gradient", None,
         dict(node=True), ["gradient"]),
        ("a gradient creates on network space", "gradient", None,
         dict(network=True), ["create_gradient"]),
        ("a gradient over nothing misses", "gradient", None,
         dict(), []),
        ("the node wins over the network behind it", "gradient", None,
         dict(node=True, network=True), ["gradient"]),
        ("code hands to the node", "code", None,
         dict(node=True), ["code"]),
        ("code creates on network space", "code", None,
         dict(network=True), ["create_code"]),
        ("code over nothing misses", "code", None,
         dict(), []),
        ("an image hands the path to the node", "file", "image",
         dict(node=True), ["file_path"]),
        ("an image creates on network space", "file", "image",
         dict(network=True), ["create_image"]),
        ("an image over nothing misses", "file", "image",
         dict(), []),
        ("geometry hands the path to the node", "file", "geo",
         dict(node=True), ["file_path"]),
        ("geometry imports when no node takes it", "file", "geo",
         dict(), ["geo"]),
        ("geometry ignores the network - its import aims itself",
         "file", "geo", dict(network=True), ["geo"]),
        ("a hip hands the path to the node", "file", "hip",
         dict(node=True), ["file_path"]),
        ("a hip inside the panel misses", "file", "hip",
         dict(inside=True), []),
        ("a hip outside the panel loads the scene", "file", "hip",
         dict(outside=True), ["open_hip"]),
        ("an unknown file hands the path to the node", "file", "other",
         dict(node=True), ["file_path"]),
        ("an unknown file has no creation rule", "file", "other",
         dict(network=True), []),
        ("the sidebar category outranks every target", "gradient", None,
         dict(node=True, category="Metals"), ["category:Metals"]),
    )

    _KINDS = None

    def _kind(self, name):
        from amaze.core import file_library
        return {
            "image": file_library.KIND_IMAGE,
            "geo": file_library.KIND_GEO,
            "hip": file_library.KIND_HIP,
            "other": file_library.KIND_OTHER,
        }[name]

    def test_every_cell_of_the_matrix(self):
        for name, section, kind, aim, expected in self.CELLS:
            with self.subTest(cell=name):
                h = _Harness(self, section=section,
                             kind=self._kind(kind) if kind else None)
                h.panel.resize(400, 300)
                if aim.get("node"):
                    h.panel._node = object()
                if aim.get("network"):
                    h.panel._network = object()
                if aim.get("category"):
                    h.panel._category = aim["category"]
                h.press()
                # Armed directly - these cells pin the RELEASE dispatch only.
                h.view._dragging = True
                h.view._drag_panel = h.panel
                global_pos = None
                if aim.get("outside"):
                    global_pos = QtCore.QPoint(2000, 2000)
                elif aim.get("inside"):
                    global_pos = QtCore.QPoint(50, 50)
                h.release(global_pos=global_pos)
                self.assertEqual(expected, h.panel.calls, name)
                self.assertFalse(h.view._dragging,
                                 "the gesture stayed live after: " + name)


class TheParameterPaneHandOff(unittest.TestCase):
    """A File gesture crossing into a Parameters pane becomes the ONE real `QDrag` - a field is a Qt widget and only mime fills it. Every other section stays self-managed."""

    class _Pane:
        def type(self):
            return hou.paneTabType.Parm

    class _UI:
        def __init__(self, pane):
            self._pane = pane

        def paneTabUnderCursor(self):
            return self._pane

        def paneTabs(self):
            """An empty answer keeps the viewport hover inert under the mock."""
            return []

    def _armed(self, section, kind=None):
        h = _Harness(self, section=section, kind=kind)
        h.press()
        start = h.item_pos()
        h.move(QtCore.QPoint(start.x() + 60, start.y() + 60))
        self.assertTrue(h.view._dragging, "premise: the gesture armed")
        return h

    def _with_parm_pane_under_cursor(self, harness, move_to):
        ran = []
        harness.view._run_file_path_drag = lambda: ran.append(True)
        had_ui = hasattr(hou, "ui")
        real = getattr(hou, "ui", None)
        hou.ui = self._UI(self._Pane())
        try:
            harness.move(move_to)
        finally:
            if had_ui:
                hou.ui = real
            else:
                del hou.ui
        return ran

    def test_a_file_gesture_over_a_parm_pane_promotes(self):
        from amaze.core import file_library
        h = self._armed("file", file_library.KIND_IMAGE)
        start = h.item_pos()
        ran = self._with_parm_pane_under_cursor(
            h, QtCore.QPoint(start.x() + 90, start.y() + 90))
        self.assertEqual([True], ran, "the hand-off did not run")
        self.assertFalse(h.view._dragging,
                         "the gesture stayed live after the hand-off")

    def test_a_material_gesture_never_promotes(self):
        # Mocked BEFORE arming - every move asks `hou.ui`, absent headless.
        ran = []
        had_ui = hasattr(hou, "ui")
        real = getattr(hou, "ui", None)
        hou.ui = self._UI(self._Pane())
        try:
            h = self._armed("material")
            h.view._run_file_path_drag = lambda: ran.append(True)
            start = h.item_pos()
            h.move(QtCore.QPoint(start.x() + 90, start.y() + 90))
        finally:
            if had_ui:
                hou.ui = real
            else:
                del hou.ui
        self.assertEqual([], ran, "a material drag promoted to a "
                         "file-path drag")
        self.assertTrue(h.view._dragging,
                        "the material gesture must survive the pane "
                        "crossing")
        h.release()


class GuardedSlotsTest(unittest.TestCase):
    """Every overridden Qt handler must carry `debug.guarded`, or an exception in it vanishes with no record and no traceback. Checked on `__wrapped__`, never by grepping the source, which matches the decorator named in prose. It does NOT survive a SIGSEGV. ▸r/qt-windows-macos"""

    HANDLERS = (
        "mousePressEvent", "mouseMoveEvent", "mouseReleaseEvent",
        "dragEnterEvent", "dragMoveEvent", "dropEvent",
    )

    def _widget_classes(self):
        """This project's widget classes - a QWidget OR any class defining a Qt handler, because the gesture lives on a MIXIN a QWidget-only scan would miss."""
        from amaze.helpers import ui_helpers

        found = []
        for module in (dragdrop_widgets, ui_helpers):
            for name in dir(module):
                value = getattr(module, name)
                if not (isinstance(value, type)
                        and value.__module__ == module.__name__):
                    continue
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
        """A wrapper eating the return breaks every handler ending `return super()...` and changes the event's accept path."""
        from amaze.core import debug

        @debug.guarded("Probe.mousePressEvent")
        def handler(_self, value):
            return ("body ran", value)

        self.assertEqual(("body ran", 7), handler(None, 7))

    def test_a_guarded_handler_re_raises(self):
        """The wrapper RECORDS and re-raises - swallowing turns a crash into a silently half-finished gesture."""
        from amaze.core import debug

        @debug.guarded("Probe.mouseReleaseEvent")
        def handler(_self):
            raise ValueError("boom")

        with self.assertRaises(ValueError):
            handler(None)


class TheGestureRunsOnBOTHViews(unittest.TestCase):
    """The gesture is a MIXIN over `QAbstractItemView` so both views get it without a second copy. A real `QDrag` is not an option - it traps the gesture in a nested run loop where per-move viewport picking cannot run."""

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
        """The arming rules are class data on the mixin - a view without them arms on nothing, or on everything."""
        table = dragdrop_widgets.DragDropTableView
        self.assertEqual(dragdrop_widgets.GridGestureMixin.ARMED_SECTIONS,
                         table.ARMED_SECTIONS)

    def test_the_table_view_selects_ROWS_and_MANY(self):
        """`QTableView` defaults to ExtendedSelection where `QListView` defaults to Single, so the table says so rather than inheriting the difference."""
        view = dragdrop_widgets.DragDropTableView()
        self.addCleanup(view.deleteLater)
        self.assertEqual(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection,
            view.selectionMode())
        self.assertEqual(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows,
            view.selectionBehavior())

    def test_the_table_view_hides_the_row_numbers(self):
        """A table's default row numbers mean nothing here - the row IS the asset."""
        view = dragdrop_widgets.DragDropTableView()
        self.addCleanup(view.deleteLater)
        self.assertFalse(view.verticalHeader().isVisible())
        self.assertFalse(view.showGrid(),
                         "the table paints Qt's own grid lines over a "
                         "row that draws its own dividers")

    def test_the_debug_helper_survives_a_view_with_no_gridSize(self):
        """The one `QListView`-only call in the gesture: a table has no grid size, and this runs inside the scroll path under Debug Mode."""
        view = dragdrop_widgets.DragDropTableView()
        self.addCleanup(view.deleteLater)
        self.assertFalse(hasattr(view, "gridSize"))
        view.setModel(QtGui.QStandardItemModel(3, 1))
        from amaze.core import debug as debug_mod
        was_on = debug_mod.is_on()
        debug_mod.configure(True)
        self.addCleanup(debug_mod.configure, was_on)
        view._log_scroll_geometry(          # must not raise
            None, view.verticalScrollBar(), 0, 0)


if __name__ == "__main__":
    unittest.main()
