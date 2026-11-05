"""What every thumbnail path shares: a forgiving parm set, and the Scene Viewer's OCIO."""

import hou
from amaze.core import debug


def safe_set(node: hou.Node, parm_name: str, value, **kwargs) -> None:
    """Set a parm, skipping one this renderer build does not expose. ▸r/hou-errors"""
    parm = node.parm(parm_name)
    if parm is None:
        debug.event(
            "thumb", "parm skipped", parm=parm_name, node=node.path()
        )
        return
    try:
        parm.set(value, **kwargs)
    except (hou.Error, TypeError) as e:
        debug.event(
            "thumb", "parm skipped", parm=parm_name, node=node.path(),
            error=str(e)
        )


def ocio_from_viewer():
    """The Scene Viewer's OCIO display, view and working space; None with no GUI or viewer."""
    ui = getattr(hou, "ui", None)
    if ui is None:
        return None
    viewer = ui.curDesktop().paneTabOfType(hou.paneTabType.SceneViewer)
    if not viewer:
        return None
    space = "ACEScg"
    for candidate in hou.Color.ocio_spaces():
        if "acescg" in candidate.lower():
            space = candidate
            break
    return {
        "display": viewer.getOCIODisplay(),
        "view": viewer.getOCIOView(),
        "space": space,
    }
