import hou
from PySide6 import QtCore, QtGui

from amaze import branding
from amaze import messages
from amaze.core import debug


class HoudiniSpeaker:
    """The log's dialogs and status line through Houdini, and what it records about Houdini."""

    @staticmethod
    def dialog(text: str) -> None:
        """A warning shown once Qt is idle, so it never lands inside a mouse release."""
        ui = getattr(hou, "ui", None)
        if ui is None:
            raise AttributeError("no hou.ui in this session")
        QtCore.QTimer.singleShot(0, lambda: ui.displayMessage(
            text, severity=hou.severityType.Warning,  # type: ignore
            title=messages.TITLE_AMAZE,
        ))

    @staticmethod
    def status(text: str) -> None:
        """Houdini's status line, which says who is speaking. ▸r/status-bar"""
        ui = getattr(hou, "ui", None)
        if ui is None:
            raise AttributeError("no hou.ui in this session")
        ui.setStatusMessage(
            "Amaze: %s" % text,
            severity=hou.severityType.Message,  # type: ignore
        )

    @staticmethod
    def houdini_version() -> str:
        return hou.applicationVersionString()

    @staticmethod
    def describe(info: dict) -> None:
        """The session header's Houdini, UI scales and renderer plugins, filled into `info`."""
        info["houdini"] = hou.applicationVersionString()
        info["product"] = hou.applicationName()
        try:
            info["ui_scale"] = float(getattr(hou, "ui", None).globalScaleFactor())
        except Exception:
            pass
        try:
            screen = QtGui.QGuiApplication.primaryScreen()
            if screen is not None:
                info["device_pixel_ratio"] = float(screen.devicePixelRatio())
        except Exception:
            pass
        try:
            from amaze.helpers import theme

            info["effective_ui_scale"] = float(theme.UI_SCALE)
        except Exception:
            pass
        for label, type_name in (
            ("redshift", "redshift_vopnet"),
            ("octane", "octane_vopnet"),
            ("mtlx", "mtlxstandard_surface"),
        ):
            info["has_" + label] = bool(
                hou.vopNodeTypeCategory().nodeTypes().get(type_name)
            )


def start() -> None:
    """The first call of the pane and of every shelf tool: the log speaks through Houdini."""
    debug.hand_over(HoudiniSpeaker)


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
    start()
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
