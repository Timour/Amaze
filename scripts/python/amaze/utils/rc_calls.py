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


def _chosen(node) -> list:
    """The selection when `node` is in it, else `node` alone: the save door's rule."""
    selected = list(hou.selectedNodes())
    return selected if node in selected else [node]


def _refusal(node, renderer, target) -> str:
    """Why `node` cannot become `target`, or "" when it can."""
    from amaze.render.material_conversion import engine
    if not renderer:
        return messages.NODE_NOT_A_MATERIAL % node.name()
    return engine.why_not(renderer, target)


def _convert_one(node, renderer, target, word, swap, report):
    """One node's twin beside it, or with `swap` in its place, current and selected."""
    from amaze.render.material_conversion import engine
    old_name, old_position = node.name(), node.position()    # read before a swap destroys the node
    made = engine.convert(node, renderer, target, node.parent(),
                          "%s_%s" % (old_name, word.lower()), report)
    if made.builder is not None:
        made.builder.setPosition(old_position)    # a scripted createNode lands at the origin
        helpers.auto_place(made.builder)    # to a free tile beside it, moving no other node
        swapped = swap and made.shader is not None    # no shader: the old node stays, as a plain convert leaves it
        if swapped:
            node.destroy()
            made.builder.setName(old_name)    # exact: references by path reach the twin; a refusal undoes the whole step
            made.builder.setPosition(old_position)
        made.builder.setCurrent(True, True)    # current and selected, as a node from the Tab menu is
    return made


def convert(node, target, swap=False) -> None:
    """Right-click `Convert to <target>`: each chosen node's twin, or with `swap` in its place."""
    start()
    if node is None:
        return
    from amaze.core import renderers
    from amaze.render.material_conversion import engine
    from amaze.render.material_conversion.report import ConversionReport
    ui = getattr(hou, "ui", None)
    chosen = _chosen(node)
    word = renderers.get(target).engine    # the menu item's own word, Karma, where the library label says MaterialX
    label = ("Convert and Swap to %s" if swap else "Convert to %s") % word
    skipped, reports, sources, twins = [], [], set(), []
    with hou.undos.group(label):    # one undo step per menu command, as Houdini's own; it covers the destroys
        for each in chosen:
            renderer = node_renderer(each)
            reason = _refusal(each, renderer, target)    # before the build: a missing plugin makes it raise
            if reason:
                skipped.append(reason if not renderer
                               else messages.NODE_SKIPPED_LINE % (each.name(), reason))
                continue
            sources.add(renderers.normalized(renderer))
            report = ConversionReport(each.name())
            made = _convert_one(each, renderer, target, word, swap, report)
            reports.append((made, report))
            if made.builder is not None:
                twins.append(made.builder)
        for twin in twins:
            twin.setSelected(True)    # setCurrent(True, True) cleared the twins made before it
    if ui is None:    # no screen to say it on: the twins are the answer
        return
    made_count = sum(1 for made, _report in reports if made.shader is not None)
    if len(chosen) == 1 and skipped:    # one node refused: its sentence is the whole answer
        ui.displayMessage(_refusal(node, node_renderer(node), target))
    elif not skipped and made_count == len(chosen) \
            and all(report.is_clean() for _made, report in reports):    # summary_lines always holds the name line
        if len(chosen) > 1:
            HoudiniSpeaker.status(messages.NODES_SWAPPED % (made_count, word) if swap
                                  else messages.NODES_CONVERTED % (made_count, word))
        else:
            name = reports[0][1].mat_name    # the source's name, which a swapped twin now holds
            HoudiniSpeaker.status(messages.NODE_SWAPPED % (name, word) if swap
                                  else messages.NODE_CONVERTED % (name, word))
    else:
        shown = " and ".join(renderers.label(source)
                             for source in engine.targets() if source in sources)
        lines = skipped + [line for _made, report in reports for line in report.summary_lines()]
        ui.displayMessage(messages.CONVERSION_SUMMARY % (
            made_count, len(chosen), shown, word, "\n".join(lines)))


VIEWPORT_PROPERTIES = (
    "ogl_diff", "ogl_spec", "ogl_rough", "ogl_metallic", "ogl_emit", "ogl_alpha",
    "ogl_normalmap", "ogl_roughmap", "ogl_metallicmap", "ogl_emissionmap", "ogl_opacitymap",
    "ogl_numtex",
)    # Houdini's own material properties ▸r/viewport-ogl-block

VIEWPORT_CHANNELS = (
    ("ogl_diff", ("base_color",), "ogl_tex1"),
    ("ogl_spec", ("refl_color", "specular_color"), None),
    ("ogl_rough", ("refl_roughness", "specular_roughness"), "ogl_roughmap"),
    ("ogl_metallic", ("metalness", "base_metalness"), "ogl_metallicmap"),
    ("ogl_emit", ("emission_color",), "ogl_emissionmap"),
    ("ogl_alpha", ("opacity_color", "geometry_opacity"), "ogl_opacitymap"),
)    # property, shader parm (Standard, then OpenPBR), map slot ▸r/redshift-nodes

BUMP_INPUTS = ("bump_input", "geometry_normal")    # Standard Material's, then OpenPBR's

HEIGHT_FIELD = "0"    # redshift::BumpMap inputType: a height field is no normal map


def previewable(node) -> bool:
    """Whether the right-click offers `Viewport Preview`: no dialog, no panel."""
    return node_renderer(node) == "Redshift"


def _wired(node, input_name):
    """The node wired into `node`'s input called `input_name`, or None."""
    names, inputs = node.inputNames(), node.inputs()
    index = names.index(input_name) if input_name in names else len(inputs)
    return inputs[index] if index < len(inputs) else None


def _sampler(node):
    """`node` when it is a Texture Sampler, else None."""
    if node is not None and node.type().name() == "redshift::TextureSampler":
        return node
    return None


def _normal_texture(shader):
    """What the normal map slot reads: a Normal Map's own file, or the sampler under a Bump Map."""
    for input_name in BUMP_INPUTS:
        wired = _wired(shader, input_name)
        if wired is None:
            continue
        kind = wired.type().name()
        if kind == "redshift::NormalMap":
            return wired
        if kind == "redshift::BumpMap" and wired.parm("inputType").eval() != HEIGHT_FIELD:
            return _sampler(_wired(wired, "input"))
    return None


def _viewport_block(builder) -> None:
    """The OpenGL properties `builder` lacks, added to its OpenGL folder as the library's are."""
    group = builder.parmTemplateGroup()
    missing = [hou.properties.parmTemplate("material", name)
               for name in VIEWPORT_PROPERTIES if group.find(name) is None]
    if not missing:
        return
    if group.findFolder("OpenGL") is None:    # by label: the classic builder's folder has another name
        group.append(hou.FolderParmTemplate("OpenGL", "OpenGL", folder_type=hou.folderType.Tabs))
    for template in missing:
        group.appendToFolder(group.findFolder("OpenGL"), template)
    builder.setParmTemplateGroup(group)


def _follow_file(builder, slot, texture) -> None:
    """`builder`'s map `slot` a string reference to `texture`'s file."""
    builder.parm(slot).setExpression('chs("%s/tex0")' % builder.relativePathTo(texture),
                                     hou.exprLanguage.Hscript)


def _follow(builder, shader) -> bool:
    """Each OpenGL property a reference into `shader`, each map slot its sampler; False for none."""
    plan = []
    for prop, sources, slot in VIEWPORT_CHANNELS:
        channel = next((shader.parmTuple(s) for s in sources
                        if shader.parmTuple(s) is not None), None)
        if channel is not None:
            plan.append((prop, channel, slot))
    if not plan:
        return False
    _viewport_block(builder)
    path = builder.relativePathTo(shader)
    for prop, channel, slot in plan:
        for index, parm in enumerate(builder.parmTuple(prop)):
            component = channel[min(index, len(channel) - 1)]    # Alpha reads a colour's first component
            parm.setExpression('ch("%s/%s")' % (path, component.name()), hou.exprLanguage.Hscript)
        sampler = _sampler(_wired(shader, channel.name())) if slot else None    # each parm is its own input
        if sampler is not None:
            if slot == "ogl_tex1" and builder.parm("ogl_numtex").eval() < 1:
                builder.parm("ogl_numtex").set(1)    # the first diffuse texture layer
            _follow_file(builder, slot, sampler)
    normal = _normal_texture(shader)
    if normal is not None:
        _follow_file(builder, "ogl_normalmap", normal)
    return True


def viewport_preview(node) -> None:
    """Right-click `Viewport Preview`: each chosen Redshift material shown by its shader's values."""
    start()
    if node is None:
        return
    from amaze.core import material
    chosen = _chosen(node)
    skipped, added = [], []
    with hou.undos.group("Viewport Preview"):    # one undo step for the whole selection
        for each in chosen:
            shader = material.redshift_surface_shader(each) if previewable(each) else None
            if not previewable(each):
                skipped.append(messages.VIEWPORT_PREVIEW_NOT_REDSHIFT % each.name())
            elif shader is None:
                skipped.append(messages.VIEWPORT_PREVIEW_NO_SHADER % each.name())
            elif not _follow(each, shader):
                skipped.append(messages.VIEWPORT_PREVIEW_NO_CHANNELS
                               % (each.name(), shader.type().description()))
            else:
                added.append(each)
    ui = getattr(hou, "ui", None)
    if ui is None:    # no screen to say it on: the block is the answer
        return
    if skipped:
        ui.displayMessage(messages.VIEWPORT_PREVIEW_SKIPPED
                          % (len(added), len(chosen), "\n".join(skipped)))
    elif len(added) > 1:
        HoudiniSpeaker.status(messages.VIEWPORT_PREVIEWS_ADDED % len(added))
    else:
        HoudiniSpeaker.status(messages.VIEWPORT_PREVIEW_ADDED % added[0].name())


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
