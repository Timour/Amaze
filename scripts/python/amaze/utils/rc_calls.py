import hou

from amaze import branding
from amaze import messages


def _find_panel():
    """The app panel's root widget, or None - with the user told to open it first where there is a screen to tell, and the FIRST pane tab matching a known label winning. ▸r/status-bar"""
    ui = getattr(hou, "ui", None)
    if ui is None:
        return None
    panel = None
    for pane_tab in ui.paneTabs():
        if pane_tab.type() == hou.paneTabType.PythonPanel:
            if pane_tab.label() == branding.APP_NAME:
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
    door = getattr(panel, "save_from_node", None)
    if door is None:    # the menu reloads from disk, the panel does not: an update awaits a restart
        ui = getattr(hou, "ui", None)
        if ui is not None:
            ui.displayMessage(messages.RESTART_TO_FINISH_UPDATE)
        return
    if node is not None and not node.isSelected():
        node.setSelected(True, clear_all_selected=True)
    door(node)
