import hou

from amaze import branding

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
            "Please open the %s panel first." % branding.APP_NAME
        )
    return panel


def save_material() -> None:
    """Call Save Script from RC-Menus in Houdini Network Pane"""
    panel = _find_panel()
    if panel:
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
