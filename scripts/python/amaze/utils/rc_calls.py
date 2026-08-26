import hou

from amaze import branding
from amaze import messages

_PANEL_LABELS = (branding.APP_NAME, "AssetLib", "MatLib")


def _find_panel():
    """The app panel's root widget, or None - with the user told to open it first where there is a screen to tell, and the FIRST pane tab matching a known label winning. ▸r/status-bar"""
    ui = getattr(hou, "ui", None)
    if ui is None:
        return None
    panel = None
    for pane_tab in ui.paneTabs():
        if pane_tab.type() == hou.paneTabType.PythonPanel:
            if pane_tab.label() in _PANEL_LABELS:
                panel = pane_tab.activeInterfaceRootWidget()
                break
    if not panel:
        ui.displayMessage(
            messages.PANEL_NOT_OPEN % branding.APP_NAME
        )
    return panel


def save_material(node=None) -> None:
    """Node right-click `Save to Amaze` on a material - the save flow stays SELECTION-based because multi-selection saves are a feature, so this door bridges the click into the selection instead of passing the node through: an unselected clicked node becomes the whole selection (right-clicking an unselected builder used to save whatever ELSE was selected), a node already inside a multi-selection keeps the whole selection, and the selection write lands on the undo stack like the click it stands in for (research.md ▸ Node graph). This lived untestable in OPmenu.xml's scriptCode; ROADMAP R50 moved it here beside its three siblings."""
    panel = _find_panel()   # the panel FIRST, the selection write after: with no panel there is no save, and a refused save must not have cost the user the multi-selection they built
    if not panel:
        return
    if node is not None and not node.isSelected():
        node.setSelected(True, clear_all_selected=True)
    panel.save_asset()


def save_cop(node=None) -> None:
    """Node right-click `Save to Amaze` on a COP network container - PASS the clicked node, so the save does not depend on the selection state."""
    panel = _find_panel()
    if panel:
        panel.save_cop_from_node(node)


def save_gradient(node=None) -> None:
    """Node right-click `Save Gradient to Amaze` - PASS the clicked node, so the save does not depend on the selection state."""
    panel = _find_panel()
    if panel:
        panel.save_gradient_from_node(node)


def save_code(node=None) -> None:
    """Node right-click `Save Code to Amaze` - reads the clicked node's code/snippet parm."""
    panel = _find_panel()
    if panel:
        panel.save_code_from_node(node)
