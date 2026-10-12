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


def save(node=None) -> None:
    """Right-click `Save to Amaze`. ▸p/save-section-row"""
    panel = _find_panel()   # first: a refused save must not cost the selection
    if not panel:
        return
    if node is not None and not node.isSelected():
        node.setSelected(True, clear_all_selected=True)
    panel.save_from_node(node)
