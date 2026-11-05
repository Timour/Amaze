import glob
import os
import sys

import hou
from PySide6 import QtGui

from amaze import branding
from amaze import messages
from amaze.core import debug
from amaze.helpers import helpers


class HoudiniSpeaker:
    """The log's dialogs and status line through Houdini, and what it records about Houdini."""

    @staticmethod
    def dialog(text: str) -> None:
        """A warning shown at the top of the event loop, outside any mouse release or pump."""
        ui = getattr(hou, "ui", None)
        if ui is None:
            raise AttributeError("no hou.ui in this session")
        helpers.run_at_top_of_loop(lambda: ui.displayMessage(
            text, severity=hou.severityType.Warning,  # type: ignore
            title=messages.TITLE_AMAZE,
        ), "alert dialog")

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


def node_renderer(node) -> str:
    """The renderer a scene node's type implies, "" for none, by the save door's own detector."""
    if node is None:
        return ""
    from amaze.render import nodes
    return nodes.NodeHandler(None).get_renderer_from_node(node)    # the detector reads no preferences


def convertible(node, target) -> bool:
    """Whether the right-click offers `Convert to <target>`: no dialog, no panel, as context code must."""
    from amaze.core import renderers
    from amaze.render.material_conversion import engine
    renderer = node_renderer(node)
    return bool(renderer) and renderers.normalized(renderer) != target \
        and engine.can_convert(renderer, target)    # a target whose plugin is not loaded is not offered


def convert(node, target) -> None:
    """Right-click `Convert to <target>`: the panel's engine on the node itself, its twin beside it."""
    start()
    if node is None:
        return
    from amaze.core import renderers
    from amaze.render.material_conversion import engine
    from amaze.render.material_conversion.report import ConversionReport
    ui = getattr(hou, "ui", None)
    renderer = node_renderer(node)
    report = ConversionReport(node.name())
    reason = engine.why_not(renderer, target)
    if reason:    # before the build: a missing plugin makes it raise
        if ui is not None:
            ui.displayMessage(reason)
        return
    word = renderers.get(target).engine    # the menu item's own word, Karma, where the library label says MaterialX
    with hou.undos.group("Convert to %s" % word):    # one undo step per menu command, as Houdini's own
        made = engine.convert(node, renderer, target, node.parent(),
                              "%s_%s" % (node.name(), word.lower()), report)
        if made.builder is not None:
            made.builder.setCurrent(True, True)    # current and selected, as a node from the Tab menu is
    if ui is None:    # no screen to say it on: the twin is the answer
        return
    if made.shader is not None and report.is_clean():    # summary_lines always holds the name line, so cleanliness is asked
        HoudiniSpeaker.status(messages.NODE_CONVERTED % (node.name(), word))
    else:
        ui.displayMessage(messages.CONVERSION_SUMMARY % (
            1 if made.shader is not None else 0, 1, renderers.label(renderer), word,
            "\n".join(report.summary_lines())))


def _shelf_tool(*names):
    """A shelf tool's prologue: (ui, each of `names` imported), or None when it must stop there."""
    start()
    ui = getattr(hou, "ui", None)
    if ui is None:    # a shelf tool runs where there is a screen to answer on
        return None
    try:
        for name in names:
            __import__(name)    # the import statement's own door, so a broken install is said
    except ImportError as exc:
        ui.displayMessage(messages.AMAZE_NOT_IMPORTABLE % exc)
        return None
    return (ui,) + tuple(sys.modules[name] for name in names)


def capture() -> None:
    """The shelf's Capture: the panel button's own capture, a refusal shown in a dialog."""
    tool = _shelf_tool("amaze.core.scene_captures", "amaze.prefs.prefs")
    if tool is None:
        return
    ui, scene_captures, prefs_module = tool
    preferences = prefs_module.Prefs()
    preferences.load()
    try:
        scene_captures.capture_open_scene(preferences)
    except scene_captures.CaptureRefused as exc:
        ui.displayMessage(str(exc))
    else:
        HoudiniSpeaker.status("thumbnail captured for %s"
                              % hou.hipFile.basename())    # "untitled.hip" when unsaved, never ""


def check_for_updates() -> None:
    """The shelf's Updates: the About tab's verdict and questions, in Houdini's message box."""
    tool = _shelf_tool("amaze.core.updater", "amaze.dialogs.update_dialog")
    if tool is None:
        return
    ui, updater, update_dialog = tool
    found = updater.check()
    library = updater.configured_library()
    if not found:    # up to date, no release, or unreachable: the sentence is the whole answer
        ui.displayMessage(found.sentence, title=messages.TITLE_AMAZE)
    elif ui.displayMessage(
            messages.UPDATE_OFFER % updater.offer_line(found, library),
            buttons=messages.BUTTONS_INSTALL_UPDATE,
            close_choice=1, title=messages.TITLE_AMAZE) == 0 \
            and update_dialog.confirmed(found, library):    # Continue or Cancel, as on the About tab
        update_dialog.install_and_say(found)


def reload_asset_files() -> None:
    """The shelf's Reload: package asset files installed or re-read, so their install scripts run."""
    tool = _shelf_tool("amaze.helpers.hostos")
    if tool is None:
        return
    _ui, hostos = tool
    hfs = os.path.realpath(hou.getenv("HFS") or "")
    loaded = {hostos.comparable_path(p): p for p in hou.hda.loadedFiles()}    # one spelling each
    new, again = [], []
    for root in hou.houdiniPath():
        if hfs and os.path.realpath(root).startswith(hfs):
            continue    # Houdini's own otls, not a package's
        for path in sorted(glob.glob(os.path.join(root, "otls", "*.hda"))):
            known = loaded.get(hostos.comparable_path(path))
            if known:
                hou.hda.reloadFile(known)    # its install script registers any embedded viewer state
                again.append(known)
            else:
                hou.hda.installFile(path)
                new.append(path)
    HoudiniSpeaker.status("%d asset files reloaded, %d new" % (len(again), len(new)))
