"""The Code section's verbs that need Houdini: run a snippet, set one onto a node. ▸m/layer-plan"""

import traceback

import hou
from PySide6 import QtCore, QtGui

from amaze.helpers import helpers, hostos


def shelf_kwargs(name: str) -> dict:
    """The `kwargs` a shelf click gives its script, so shelf scripts run unchanged ▸r/shelf-kwargs."""
    held = QtGui.QGuiApplication.keyboardModifiers()
    keys = QtCore.Qt.KeyboardModifier
    mac = hostos.is_macos()
    ctrl, cmd = keys.ControlModifier, keys.MetaModifier
    if mac and not QtCore.QCoreApplication.testAttribute(
            QtCore.Qt.ApplicationAttribute.AA_MacDontSwapCtrlAndMeta):
        ctrl, cmd = cmd, ctrl    # on a Mac Qt names Command "Control" unless the app turns that off
    return {"pane": None, "viewport": None, "panename": "", "toolname": name,
            "shiftclick": bool(held & keys.ShiftModifier), "ctrlclick": bool(held & ctrl),
            "altclick": bool(held & keys.AltModifier), "cmdclick": mac and bool(held & cmd),
            "requestnew": True, "branch": False, "autoplace": False,
            "inputs": [], "inputnodename": "", "outputindex": -1,
            "outputs": [], "outputnodename": "", "inputindex": -1}


def run_python(name: str, code: str) -> str:
    """Run a Python snippet in this Houdini as one undo step: "" or its error's last line."""
    try:
        compiled = compile(str(code or ""), "<snippet %s>" % name, "exec")
    except SyntaxError as exc:
        return "line %s: %s" % (exc.lineno, exc.msg)
    try:
        with hou.undos.group("Run %s" % name):
            exec(compiled, {"__name__": "__main__", "hou": hou,    # noqa: S102
                            "kwargs": shelf_kwargs(name)})
    except (Exception, SystemExit):                          # noqa: BLE001
        traceback.print_exc()
        return traceback.format_exc().strip().splitlines()[-1]
    return ""


def apply_to_node(model, row: int, node) -> tuple:
    """The snippet in `row` onto `node`'s code parm: (ok, reason), the reason saying what is missing."""
    if not 0 <= row < len(model.assets):
        return (False, "No snippet selected.")
    if node is None:
        return (False, "Select a node with a code/snippet parameter.")
    parm = helpers.find_code_parm(node)
    if parm is None:
        return (
            False,
            '"%s" has no code/snippet parameter to set.' % node.name(),
        )
    try:
        parm.set(model.assets[row].code)
    except hou.OperationFailed as exc:
        return (False, "Could not set the parameter: %s" % exc)
    return (True, "")
