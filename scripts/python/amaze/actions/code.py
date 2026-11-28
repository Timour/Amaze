"""The Code section's actions that need Houdini: run a snippet, set one on a node. ▸p/layer-plan"""

import traceback

import hou
from PySide6 import QtCore

from amaze import messages
from amaze.helpers import helpers, hostos

RUNS = "python"    # the one language Run runs, as the language is stored, lower case


def shelf_kwargs(name: str, held) -> dict:
    """The `kwargs` a shelf click with `held` keys gives its script ▸r/shelf-kwargs."""
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


def run(name: str, code: str, language: str,
        held=QtCore.Qt.KeyboardModifier.NoModifier) -> str:
    """Run a Python snippet in this Houdini as one undo step: "", or why it did not run or stopped."""
    if str(language or "").lower() != RUNS:
        return messages.SNIPPET_NOT_PYTHON % (name, language or "Code")
    try:
        compiled = compile(str(code or ""), "<snippet %s>" % name, "exec")
    except SyntaxError as exc:
        return messages.SNIPPET_RUN_FAILED % (name, "line %s: %s" % (exc.lineno, exc.msg))
    try:
        with hou.undos.group("Run %s" % name):
            exec(compiled, {"__name__": "__main__", "hou": hou,    # noqa: S102
                            "kwargs": shelf_kwargs(name, held)})
    except (Exception, SystemExit):                          # noqa: BLE001
        traceback.print_exc()
        return messages.SNIPPET_RUN_FAILED % (
            name, traceback.format_exc().strip().splitlines()[-1])
    return ""


def apply_to_node(model, row: int, node) -> tuple:
    """Set `row`'s snippet on `node`'s code parm: (ok, reason), the reason naming what's missing."""
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
    except hou.Error as exc:    # a locked parm raises PermissionError, not OperationFailed ▸r/hou-errors
        return (False, "Could not set the parameter: %s" % exc)
    return (True, "")
