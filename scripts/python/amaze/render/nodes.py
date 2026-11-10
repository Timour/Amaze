"""Node interaction with Houdini: save, import, convert. ▸r/node-items"""

import json
import os
import re
from typing import NamedTuple
import hou


from amaze import messages
from amaze.core import material, material_files
from amaze.core import renderers
from amaze.core import texstore
from amaze.prefs import prefs
from amaze.core import debug
from amaze.helpers import hostos, wording
from amaze.render import cop_nodes


def make_karma_builder(parent: hou.Node, name: str) -> hou.Node:
    """The mtlx builder, starters gone, connectors KEPT for wiring."""
    import voptoolutils
    builder = parent.createNode("subnet")
    builder.setName(wording.sanitize_usd_path(name), unique_name=True)
    builder = voptoolutils._setupMtlXBuilderSubnet(
        subnet_node=builder,
        name=name,
        mask=voptoolutils.MTLX_TAB_MASK,
        folder_label="MaterialX Builder",
        render_context="mtlx",
    )
    for child in builder.children():
        if child.type().name() in (
            "mtlxstandard_surface",
            "mtlxdisplacement",
            "kma_material_properties",
        ):
            child.destroy()
    return builder


def wire_builder_output(builder, surface_node, displacement_node=None):
    """Wire shader/displacement into a builder, either flavour."""
    connectors = {}
    suboutput = None
    for child in builder.children():
        tname = child.type().name()
        if tname == "subnetconnector":
            kind = child.parm("connectorkind")
            if kind is not None and kind.eval() == 1:      # output
                pn = child.parm("parmname")
                connectors[pn.eval() if pn else ""] = child
        elif tname == "suboutput":
            suboutput = child

    try:
        if connectors:
            wired = False
            if surface_node is not None and "surface" in connectors:
                connectors["surface"].setInput(0, surface_node)
                wired = True
            if displacement_node is not None and "displacement" in connectors:
                connectors["displacement"].setInput(0, displacement_node)
            return wired
        if suboutput is not None:
            if surface_node is not None:
                suboutput.setInput(0, surface_node)
            if displacement_node is not None:
                suboutput.setInput(1, displacement_node)
            return surface_node is not None
    except hou.Error as exc:      # InvalidInput is a sibling ▸r/hou-errors
        debug.event("karma", "could not wire builder output", error=str(exc))
        debug.note("could not wire builder output: %s" % exc)
    return False


def _plumbing_role(node):
    """What a connector or subnet input/output is for: equal roles answer the same output."""
    tname = node.type().name()
    if tname == "subnetconnector":
        kind, name = node.parm("connectorkind"), node.parm("parmname")
        return (tname, kind.eval() if kind else None, name.eval() if name else "")
    if tname in ("subinput", "suboutput"):
        return (tname,)
    return None


def replace_stock_plumbing(builder, loaded) -> int:
    """Saved connectors replace the builder's own of the same role, keeping their wiring."""
    saved = {}
    for node in loaded:
        role = _plumbing_role(node)
        if role is not None:
            saved.setdefault(role, node)
    replaced = 0
    for stock in [c for c in builder.children() if c not in loaded]:
        keeper = saved.get(_plumbing_role(stock))
        if keeper is None:
            continue
        name = stock.name()
        stock.destroy()
        keeper.setName(name)    # the stock name: the network reads as a fresh builder
        replaced += 1
    return replaced


def custom_node_color(node) -> list:
    """The node's chosen color as [r, g, b]; [] when it is default grey."""
    try:
        rgb = [float(c) for c in node.color().rgb()]
    except (AttributeError, TypeError, ValueError, hou.Error):
        return []
    if all(abs(c - 0.8) < 0.001 for c in rgb):
        return []
    return [round(c, 4) for c in rgb]


def apply_node_color(node, color) -> None:
    """Restore a captured color; a bad triple must never fail an import."""
    if not color or node is None:
        return
    try:
        node.setColor(hou.Color((color[0], color[1], color[2])))
    except (IndexError, TypeError, hou.Error):
        pass


KARMA_SURFACES = ("mtlxopen_pbr_surface", "mtlxstandard_surface")    # saved loose, without a builder
CONNECTORS = ("subnetconnector", "suboutput")    # a container's plumbing, not the material's


def is_marked_builder(node, renderer) -> bool:
    """`renderer`'s own builder: a plain subnet carrying its mark, tested as the renderer tests it."""
    try:
        return (bool(renderer.builder_mark) and node.type().name() == "subnet"
                and node.userData(renderer.builder_mark) == "1")
    except (AttributeError, hou.Error):
        return False


def is_octane_builder(node) -> bool:
    """Octane's own builder, a plain subnet with Octane's marker. ▸r/octane-builder"""
    return is_marked_builder(node, renderers.OCTANE)


def saved_as_own_builder(renderer, saved_type) -> bool:
    """A `renderer` asset whose .interface starts with a plain subnet: its own builder, saved whole."""
    return bool(renderer.builder_mark) and saved_type == "subnet"


def copy_network(nodes, staging) -> hou.Node:
    """A loose surface's `nodes` and the dots on their wires, copied into a fresh subnet."""
    holder = staging.createNode("subnet")
    for child in holder.children():    # the subnet's own default plumbing
        child.destroy()
    copy_with_dots(nodes, holder)
    return holder


def surface_terminal_wired(builder) -> bool:
    """Is a surface terminal wired? Three shapes. ▸r/save-shape"""
    for child in builder.children():
        tname = child.type().name()
        if tname == "subnetconnector":
            kind = child.parm("connectorkind")
            pn = child.parm("parmname")
            if (kind is not None and kind.eval() == 1
                    and pn is not None and pn.eval() == "surface"):
                return any(child.inputs())
        elif tname == "suboutput":
            inputs = child.inputs()
            return bool(inputs) and inputs[0] is not None
        elif tname in material.REDSHIFT_TERMINALS:
            return any(child.inputs())
    return False


def activate_shader_inputs(builder) -> int:
    """Turn ON every `__activate__*` toggle, recursively. ▸r/activate-inputs"""
    count = 0
    for node in builder.allSubChildren():
        for parm in node.parms():
            if "__activate__" in parm.name():
                try:
                    if parm.eval() != 1:
                        parm.set(1)
                        count += 1
                except hou.Error:
                    pass
    return count




BUILDER_FORMAT = 1


def builder_sidecar_path(preferences, mat_id: str) -> str:
    """Where an asset's builder sidecar lives, contained."""
    return material.payload_path(preferences, mat_id, material.BUILDER_SUFFIX)


def ensure_asset_folder(preferences, path: str) -> None:
    """Make `path`'s folder if it is inside the library; refuse if it is not. ▸p/library-creation-doors"""
    folder = os.path.dirname(path)
    if not folder:
        return
    root = preferences.dir
    try:
        inside = os.path.relpath(folder, root)
    except ValueError:  # another drive, a UNC share or an empty path: never inside ▸r/relpath-valueerror
        raise hostos.PathEscape("%r does not stay inside %r" % (folder, root))
    hostos.contained_join(root, inside)  # also answers for a library folder not created yet
    os.makedirs(folder, exist_ok=True)


def capture_builder(node) -> str:
    """Type, interface, non-default values as JSON. ▸p/structure-signature"""
    values = {}
    for parm in node.parms():
        try:
            keys = parm.keyframes()
        except hou.Error:
            keys = ()
        if len(keys) > 1:      # `expression()` raises on these, and `eval()` would bake them
            try:
                values[parm.name()] = _keyed_spec(parm, keys)
            except (hou.Error, TypeError, ValueError) as exc:
                debug.event("save", "parm could not be captured",
                            parm=parm.name(), error=str(exc))
            continue
        expression = None
        try:
            expression = parm.expression()
            language = parm.expressionLanguage().name()
        except hou.Error:      # no expression; family matters ▸r/hou-errors
            expression = None
        if expression is not None:
            values[parm.name()] = {"expr": expression, "lang": language}
            continue
        try:
            if parm.isAtDefault():
                continue
            if parm.parmTemplate().type() == hou.parmTemplateType.String:
                values[parm.name()] = {"str": parm.unexpandedString()}
            else:
                value = parm.eval()
                json.dumps(value)      # serialisable HERE, not at the dump
                values[parm.name()] = {"val": value}
        except (hou.Error, TypeError, ValueError) as exc:
            debug.event("save", "parm could not be captured",
                        parm=parm.name(), error=str(exc))
    return json.dumps({
        "format": BUILDER_FORMAT,
        "type": node.type().name(),
        "dialog_script": node.parmTemplateGroup().asDialogScript(),
        "values": values,
    }, indent=2, sort_keys=True)


def _keyed_spec(parm, keys) -> dict:
    """Every keyframe as Houdini writes it, plus the value now for a reader that knows no keys."""
    now = parm.eval()
    json.dumps(now)
    spec = {"keys": [key.asJSON() for key in keys]}
    spec["str" if parm.parmTemplate().type() == hou.parmTemplateType.String else "val"] = now
    return spec


def _restore_keys(parm, keys) -> None:
    """`keys` as `_keyed_spec` wrote them, set on `parm` in one call."""
    kind = (hou.StringKeyframe if parm.parmTemplate().type() == hou.parmTemplateType.String
            else hou.Keyframe)
    made = []
    for spec in keys:
        key = kind()
        key.fromJSON(spec)
        made.append(key)
    parm.setKeyframes(made)


def read_builder_sidecar(path: str) -> dict:
    """The sidecar as a dict, or {}; absent is ordinary, unusable logs."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        debug.event("import", "builder sidecar unreadable",
                    path=path, error=str(exc))
        return {}
    if not isinstance(data, dict) or "dialog_script" not in data:
        debug.event("import", "builder sidecar has the wrong shape",
                    path=path)
        return {}
    if data.get("format", 1) > BUILDER_FORMAT:      # newer Amaze; read anyway
        debug.event("import", "builder sidecar from a newer format",
                    path=path, format=data.get("format"))
    return data


def apply_builder(node, data: dict) -> None:
    """Restore interface then values, in that order; failures are per-parm."""
    script = data.get("dialog_script") or ""
    if script:
        try:
            group = node.parmTemplateGroup()
            group.setToDialogScript(script)
            node.setParmTemplateGroup(group)
        except hou.Error as exc:
            debug.event("import", "builder interface could not be applied",
                        node=node.path(), error=str(exc))
    for name, spec in (data.get("values") or {}).items():
        parm = node.parm(name)
        if parm is None:
            continue
        try:
            if "keys" in spec:
                _restore_keys(parm, spec["keys"])
            elif "expr" in spec:
                language = getattr(hou.exprLanguage, spec.get("lang") or "", None)    # none before the field
                parm.setExpression(spec["expr"], language=language)
            elif "str" in spec:
                parm.set(spec["str"])
            else:
                parm.set(spec["val"])
        except (hou.Error, TypeError, ValueError) as exc:
            debug.event("import", "builder parm could not be restored",
                        node=node.path(), parm=name, error=str(exc))


def structure_signature(node) -> str:
    """A digest of a network's SHAPE. ▸p/structure-signature"""
    while True:      # a lone wrapping container is transparent
        children = node.children()
        if len(children) == 1 and children[0].children():
            node = children[0]
            continue
        break

    plumbing = ("subinput", "subnetconnector", "suboutput")

    lines = []
    root = node.path()
    items = [node] + list(node.allSubChildren())
    for child in items:
        if child.type().name() in plumbing:
            continue
        rel = "." if child is node else child.path()[len(root) + 1:]
        lines.append("N %s|%s" % (rel, child.type().name()))
        for connection in child.inputConnections():
            source = connection.inputNode()
            if source is not None and source.type().name() in plumbing:
                continue
            source_rel = ("." if source is node
                          else source.path()[len(root) + 1:]) \
                if source is not None else "<none>"
            lines.append("W %s[%d] <- %s[%d]"
                         % (rel, connection.inputIndex(), source_rel,
                            connection.outputIndex()))
    import hashlib
    return hashlib.sha256(
        "\n".join(sorted(lines)).encode("utf-8")).hexdigest()[:16]


def staged_asset(preferences, mat, loader) -> "object":
    """Load a saved asset into staging for loader(); always destroyed."""
    with hou.undos.disabler():      # else undo resurrects it ▸r/undo-groups
        staging = hou.node("/obj").createNode("matnet")
        try:
            handler = NodeHandler(preferences)
            saved_type = material_files.get_saved_node_type(preferences, mat)
            if saved_type and node_type_available(saved_type):
                builder = staging.createNode(saved_type)
                for child in builder.children():
                    child.destroy()
                apply_builder(
                    builder,
                    read_builder_sidecar(
                        handler._builder_sidecar(mat)))
            else:
                builder = make_karma_builder(staging, mat.name or "staged")
            file_name = material.payload_path(
                preferences, mat.mat_id, preferences.ext)
            problem = load_items_strict(builder, file_name)
            if problem:
                raise hou.OperationFailed(problem)
            return loader(builder)
        finally:
            staging.destroy()


def op_path_parms(nodes):
    """(parm, unexpanded text) for each parm on `nodes` and everything under them holding `op:`."""
    scan = []
    for node in nodes:
        scan.append(node)
        scan.extend(node.allSubChildren())
    for n in scan:
        for parm in n.parms():
            try:
                raw = parm.unexpandedString()
            except hou.OperationFailed:
                continue
            if "op:" in raw:
                yield parm, raw


def clear_inherited_stamps(container: hou.Node, include_self=False) -> int:
    """Strip `assetlib_id` from what a load brought in; returns the count ▸r/inherited-stamps"""
    cleared = 0
    items = list(container.allSubChildren())
    if include_self:
        items.append(container)
    for item in items:
        try:
            if item.userData("assetlib_id") is None:
                continue
            item.destroyUserData("assetlib_id")
        except (AttributeError, hou.OperationFailed, hou.ObjectWasDeleted):
            continue    # a dot or box carries no userData at all, and a vanished node has nothing left to clear
        cleared += 1
    return cleared


def empty_file_reason(file_name: str) -> str:
    """"" or why `file_name` cannot be loaded at all: empty, or unreadable. ▸r/node-items"""
    try:
        if os.path.getsize(file_name) == 0:
            return ("its material file is empty (%s) - the save that "
                    "produced it did not finish" % file_name)
    except OSError as exc:
        return "its material file could not be read (%s)" % exc
    return ""


def nothing_loaded(name: str, file_name: str) -> str:
    """The refusal for a load that raised nothing and added no node. ▸r/node-items"""
    return ('nothing could be loaded for "%s" - its .mat file looks '
            "corrupt or empty (%s)" % (name, file_name))


def load_items_strict(node: hou.Node, file_name: str) -> str:
    """Strict load: "" or the fatal reason. ▸r/node-items"""
    problem = empty_file_reason(file_name)
    if problem:
        return problem
    try:
        node.loadItemsFromFile(file_name)
    except hou.LoadWarning as warning:    # before hou.Error, its base class
        text = str(warning)
        if "Bad node type" in text:
            return text.strip().splitlines()[-1].strip()
        debug.event("import", "load warning (non-fatal)",
                    file=file_name, warning=text[:300])
    except hou.Error as failure:
        return ("its material file could not be loaded (%s) - %s"
                % (file_name, str(failure).strip()
                   or "Houdini gave no reason"))
    clear_inherited_stamps(node)    # the file's inner nodes carry stale stamps ▸r/inherited-stamps
    return ""


def copy_with_dots(nodes, parent) -> tuple:
    """`nodes` and the dots on their input wires copied into `parent`: every copy, dots too."""
    nodes = list(nodes)
    if len({node.parent().path() for node in nodes}) != 1:    # copyItems takes one network
        return hou.copyNodesTo(nodes, parent)    # a wire through a dot is lost here ▸r/node-items
    dots, seen = [], set()
    for node in nodes:
        for connection in node.inputConnections():
            item = connection.inputItem()
            while isinstance(item, hou.NetworkDot) and item.path() not in seen:
                seen.add(item.path())
                dots.append(item)
                item = item.inputItem()
    return parent.copyItems(nodes + dots,    # copyNodesTo drops a wire through a dot ▸r/node-items
                            connect_outputs_to_multi_inputs=False)    # never wires the originals' consumers


def node_type_available(type_name: str) -> bool:
    """Is this type instantiable here? EVERY category - they span."""
    if not type_name:
        return True
    try:
        for category in hou.nodeTypeCategories().values():
            if category.nodeType(type_name) is not None:
                return True
    except (AttributeError, hou.Error):
        return True
    return False


def register_in_materiallibrary(library, builder) -> bool:
    """Cover `builder` with ONE entry. True when covered. ▸r/matlib-entries"""
    from amaze.helpers import helpers
    if library is None or builder is None:
        return False
    lib_parm = library.parm("materials")
    if lib_parm is None:
        return False
    relpath = library.relativePathTo(builder)
    covered = False
    empty_index = 0
    for i in range(1, lib_parm.evalAsInt() + 1):
        en = library.parm("enable%d" % i)
        if en is not None and not en.eval():
            continue
        pat = library.parm("matnode%d" % i)
        if pat is None:
            continue
        if pat.eval() and helpers.node_pattern_match(pat.eval(), relpath):
            covered = True
            break
        mp = library.parm("matpath%d" % i)
        if not empty_index and not pat.eval() and \
                mp is not None and not mp.eval():
            empty_index = i
    if covered:
        return True
    if empty_index:
        index = empty_index
    else:
        index = lib_parm.evalAsInt() + 1
        lib_parm.set(index)
    node_parm = library.parm("matnode%d" % index)
    path_parm = library.parm("matpath%d" % index)
    if node_parm is None or path_parm is None:
        return False
    node_parm.set(relpath)
    container = library.parm("containerpath").eval().rstrip("/")
    path_parm.set(container + "/" + builder.name())
    assign_parm = library.parm("assign%d" % index)
    if assign_parm is not None:
        assign_parm.set(0)
    return True


def karma_destination(prefs):
    """The Material Library the editor is in, /mat in the OBJ world, or None."""
    handler = NodeHandler(prefs)
    try:
        world = handler._auto_world()
    except AttributeError:
        world = "mat"      # no UI (headless): /mat is always valid
    if world == "lop":
        if handler._set_lop_import_path():
            return None
    else:
        handler._import_path = hou.node("/mat")
    return handler._import_path


def hda_fallbacks_needed(saved_items) -> bool:
    """True when a saved node is an HDA from outside Houdini's install."""
    hfs = (hou.getenv("HFS") or "").rstrip("/")
    for item in saved_items:
        if not isinstance(item, hou.Node):
            continue
        for node in (item,) + tuple(item.allSubChildren()):
            try:
                definition = node.type().definition()
            except AttributeError:
                continue
            if definition is None:
                continue
            lib = definition.libraryFilePath() or ""
            if lib and hfs and not lib.startswith(hfs):
                return True
    return False


class KarmaMaterial(NamedTuple):
    """Engine output read by NAME; `wired` False means it renders black."""

    builder: object
    shader: object
    wired: bool


def set_shader_value(shader, name: str, value, area: str) -> bool:
    """One plain value onto a shader parm, a list onto its tuple; None keeps the default. ▸r/hou-errors"""
    if value is None:
        return False
    tuple_parm = shader.parmTuple(name)
    if tuple_parm is None:
        debug.event(area, "parm not on the shader", parm=name,
                    shader=shader.type().name())
        return False
    try:
        if isinstance(value, (list, tuple)):
            tuple_parm.set(tuple(float(v) for v in value)[:len(tuple_parm)])
        elif shader.parm(name) is not None:
            shader.parm(name).set(float(value))
        else:
            return False
    except (hou.Error, TypeError, ValueError) as exc:
        debug.event(area, "shader parm not set", parm=name, error=str(exc))
        return False
    return True


def build_karma_material(parent, name, produce):
    """THE Karma engine: every input is a `produce(builder)` adapter."""
    builder = make_karma_builder(parent, name)
    result = produce(builder)
    if isinstance(result, tuple):
        shader, displacement = (result + (None,))[:2]
    else:
        shader, displacement = result, None

    if shader is not None:
        wire_builder_output(builder, shader, displacement)

    activated = activate_shader_inputs(builder)
    if activated:
        debug.event("karma", "activated shader inputs",
                    material=name, count=activated)

    builder.layoutChildren()

    wired = shader is None or surface_terminal_wired(builder)
    if not wired:
        debug.event(
            "karma", "material has no wired surface terminal",
            material=name, builder=builder.path(),
            children=[c.type().name() for c in builder.children()],
        )
        debug.note("WARNING - '%s' has no wired surface terminal and "
            "will render black (see karma-material-builder.md)" % name)
    return KarmaMaterial(builder, shader, wired)


def ocio_set() -> bool:
    """Whether $OCIO names a configuration, which every material save renders through; empty is unset."""
    return bool(hou.getenv("OCIO"))


class NodeHandler:
    """Save, import and convert, against the user's live scene."""

    def save_asset_pair(self, interface_path, mat_path, interface_text,
                        write_mat, builder_node=None, asset_id="") -> None:
        """Write an asset's files as one unit, promoted once all are written ▸p/asset-write-unit"""
        builder_path = builder_text = ""
        if builder_node is not None and asset_id:
            try:
                builder_path = builder_sidecar_path(
                    self._preferences, str(asset_id))
                builder_text = capture_builder(builder_node)
            except (hou.Error, hostos.PathEscape, OSError) as exc:
                debug.event("save", "builder sidecar not written",
                            asset_id=str(asset_id), error=str(exc))
                builder_path = builder_text = ""

        tmp_interface = tmp_mat = tmp_builder = ""
        try:
            preferences = getattr(self, "_preferences", None)  # may be absent; then nothing is created
            for destination in (interface_path, mat_path, builder_path):
                if destination and preferences is not None:  # mat/ may not exist yet
                    ensure_asset_folder(preferences, destination)
            tmp_interface = hostos.unique_scratch(interface_path)
            tmp_mat = hostos.unique_scratch(mat_path)
            if builder_path:
                tmp_builder = hostos.unique_scratch(builder_path)
                with open(tmp_builder, "w", encoding="utf-8", newline="\n") as handle:    # one file's bytes whichever OS saved it: the versions compare them
                    handle.write(builder_text)
            with open(tmp_interface, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(interface_text)
            write_mat(tmp_mat)
            if not os.path.exists(tmp_mat) or os.path.getsize(tmp_mat) == 0:
                raise hou.OperationFailed(
                    "the material file was not written (%s)" % mat_path
                )
            pending = getattr(self, "_pending_cop_promote", None)
            if pending:
                hostos.promote_scratch(pending[0], pending[1])
                self._pending_cop_promote = None
            if tmp_builder:
                hostos.promote_scratch(tmp_builder, builder_path)
            hostos.promote_scratch(tmp_interface, interface_path)
            hostos.promote_scratch(tmp_mat, mat_path)
        finally:
            for leftover in (tmp_interface, tmp_mat, tmp_builder):
                hostos.discard_scratch(leftover)
            self._discard_pending_cop_promote()

    def after_save_thumbnail(self, update: bool, label: str, asset_id,
                             node_path: str, render) -> None:
        """Render a saved asset's thumbnail: True, False, or None ▸p/after-save-thumbnail"""
        if self.supplied_thumbnail and self._supply_thumbnail(asset_id):
            return
        if not update and not (self.render_after_save and self._preferences.render_on_import):
            return
        try:
            rendered = render()
        except Exception as exc:
            debug.exception("%s thumbnail" % label, exc,
                            asset_id=str(asset_id), node=node_path)
            debug.note("%s thumbnail failed (%s) - asset saved and "
                       "registered without one." % (label, exc))
            return
        if rendered is False:
            debug.event("save", "thumbnail did not render",
                        asset_id=str(asset_id), node=node_path, kind=label)
            debug.note("%s thumbnail did not render - asset saved and "
                       "registered without one." % label)

    def _supply_thumbnail(self, asset_id) -> bool:
        """The hosted picture an import brought, saved as the asset's thumbnail; False if not."""
        from PySide6 import QtGui
        from amaze.core import tile_icons
        image = QtGui.QImage(self.supplied_thumbnail)
        target = tile_icons.thumbnail_path(self._preferences, str(asset_id))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        saved = not image.isNull() and image.save(target, "PNG")
        debug.event("save", "thumbnail from the hosted picture",
                    asset_id=str(asset_id), saved=saved)
        return saved

    def __init__(self, preferences: prefs.Prefs) -> None:
        self._preferences = preferences
        self.supplied_thumbnail = ""    # a picture an import brought, saved instead of a render
        self.render_after_save = True    # False: a new save skips its render, a batch follows
        self._builder_node = None
        self._renderer = ""
        self._import_path = None
        self._hou_parent = None
        self._use_existing_node = False
        self._cop_info = {}
        # Promoted with the .mat/.interface unit ▸p/asset-write-unit
        self._pending_cop_promote = None
        self._context_override = None

    @staticmethod
    def network_editors() -> list:
        """Every Network Editor pane tab, current tabs first; empty when headless."""
        ui = getattr(hou, "ui", None)
        if ui is None:
            return []
        editors = [pt for pt in ui.paneTabs()
                   if pt.type() == hou.paneTabType.NetworkEditor]
        editors.sort(key=lambda editor: not editor.isCurrentTab())
        return editors

    def get_active_network_editor(self):
        """The visible NetworkEditor, else any, else None when headless."""
        editors = self.network_editors()
        return editors[0] if editors else None

    def get_current_network_node(self) -> None | hou.Node:
        """The displayed network: an explicit override wins, else pwd()."""
        if self._context_override is not None:
            return self._context_override
        editor = self.get_active_network_editor()
        if editor is None:
            return None
        return editor.pwd()

    @property
    def builder_node(self) -> hou.Node:
        return self._builder_node

    @property
    def renderer(self) -> str:
        return self._renderer

    def get_renderer_from_node(self, node: hou.Node) -> str:
        """The renderer a node's type implies, or the refusal answer."""
        kind = node.type().name()
        for each in renderers.ALL:    # before the MaterialX walk: a marked builder may hold MaterialX
            if ((each.classic_container and kind == each.classic_container)
                    or (each.usd_builder and each.usd_builder in kind)
                    or is_marked_builder(node, each)):
                self._renderer = each.key
                return self._renderer
        if any(surface in kind for surface in KARMA_SURFACES):
            self._renderer = renderers.KARMA.key
        elif kind == "subnet":
            for n in node.allSubChildren():  # the whole interior, subnets included
                if "mtlx" in n.type().name():
                    self._renderer = renderers.KARMA.key
                    break
        elif kind == "collect":
            self._renderer = renderers.KARMA.key
        return self._renderer

    def import_targets(self, mat: material.Material, saved_type=None) -> set:
        """Which of {"mat", "lop"} this material can be imported into; `saved_type` spares a read."""
        if renderers.is_karma(mat.renderer):
            return {"mat", "lop"}
        if saved_type is None:
            saved_type = material_files.get_saved_node_type(self._preferences, mat)
        if saved_type in material_files.LOP_CAPABLE_NODE_TYPES:
            return {"mat", "lop"}
        found = renderers.get(mat.renderer)
        if found is None:
            return {"mat"}
        if saved_as_own_builder(found, saved_type):    # lives in both, as Karma's does
            return {"mat", "lop"}
        if found.usd_builder and node_type_available(
                found.usd_builder):    # a classic container is rebuilt as it in a LOP library
            return {"mat", "lop"}
        return {"mat"}

    def _payload_or_refusal(self, mat) -> tuple:
        """(path, "") or ("", sentence) - ONE door. ▸p/material-import-door"""
        if not material.is_safe_asset_id(mat.mat_id):
            debug.event("import", "refused unsafe asset id",
                        material=mat.name, mat_id=str(mat.mat_id)[:120])
            return ("",
                    debug.Damage(
                        '"%s" cannot be imported: its id is not a usable file '
                        "name, so the files it points at cannot be trusted to "
                        "be inside your library" % mat.name))
        try:
            return (material.payload_path(
                self._preferences, mat.mat_id, self._preferences.ext), "")
        except hostos.PathEscape:
            debug.event("import", "refused escaping asset path",
                        material=mat.name, mat_id=str(mat.mat_id)[:120])
            return ("",
                    debug.Damage(
                        '"%s" cannot be imported: its files resolve to '
                        "somewhere outside your library" % mat.name))

    def import_asset_to_scene(
        self,
        mat: material.Material,
        target: str = "auto",
        context_node: hou.Node | None = None,
    ):
        """The import seam: (ok, reason, created); [] on refusal."""
        self._builder_node = None
        self._context_override = context_node    # the network the target is read from, this import only
        try:
            ok, reason = self._import_asset_to_scene_inner(mat, target)
        finally:
            self._context_override = None
        created = ([self._builder_node]
                   if ok and self._builder_node is not None else [])
        return ok, reason, created

    def _import_asset_to_scene_inner(self, mat: material.Material, target: str = "auto"):
        """Import to `auto`, `mat`, `lop` or the seam's network: (ok, why) ▸p/material-import-door"""
        from amaze.helpers import helpers
        payload, refusal = self._payload_or_refusal(mat)
        if refusal:
            return (False, refusal)
        try:
            if os.path.getsize(payload) == 0:
                return (False,
                        debug.Damage(
                            '"%s" cannot be imported: its material file is '
                            "empty, so the save that produced it did not "
                            "finish (%s)" % (mat.name, payload)))
        except OSError as exc:
            return (False,
                    debug.Damage(
                        '"%s" cannot be imported: its material file could '
                        "not be read (%s)" % (mat.name, exc)))

        saved_type = material_files.get_saved_node_type(self._preferences, mat)
        if saved_type and not node_type_available(saved_type):
            return (False,
                    '"%s" needs the "%s" node type, which is not '
                    "available in this session - is the %s plugin "
                    "installed?" % (mat.name, saved_type, mat.renderer))

        try:
            ok, reason = self.update_context(mat, target, saved_type)
        except hou.Error as exc:
            return (False, "cannot import here: %s" % exc)
        if not ok:
            return (False, reason)

        self._created_cop_net = None
        self._hou_parent = None
        completed = False
        try:
            self._created_cop_net = self.restore_cop_companion(mat, self._import_path)
            self._hou_parent = hou.node("/obj").createNode("matnet")
            if debug.is_on():
                debug.event(
                    "import", "routing by renderer",
                    material=mat.name, renderer=mat.renderer,
                    karma_family=renderers.is_karma(mat.renderer),
                    targets=sorted(self.import_targets(mat, saved_type)),
                    saved_node_type=saved_type,
                )
            rebuilt, refusal = self._load_saved(mat, saved_type)
            if not rebuilt:
                return (False, refusal)
            landed = self.companion_ref_map(mat)
            if landed and self._builder_node is not None:
                self.rewrite_cop_refs((self._builder_node,), landed)    # the token path to the companion

            loaded_ok = True
            if (
                renderers.is_karma(mat.renderer)
                and self._builder_node.parent() == self._hou_parent
            ):
                with debug.timed("import", "move builder to destination"):
                    moved = hou.moveNodesTo(
                        (self._builder_node,), self._import_path
                    )
                    if moved:
                        self._builder_node = moved[0]
                        helpers.auto_place(self._builder_node)

            if self._import_path.type().name() == "materiallibrary":
                with debug.timed("import", "amaze wiring"):
                    self._entry_covered = register_in_materiallibrary(
                        self._import_path, self._builder_node
                    )

            try:
                self._builder_node.setUserData("assetlib_id", str(mat.mat_id))
                apply_node_color(self._builder_node, mat.node_color)
            except (hou.OperationFailed, hou.ObjectWasDeleted) as e:
                debug.note("could not stamp imported node: " + str(e))
            completed = True
        except hou.Error as exc:
            if self._hou_parent is None:    # the staging failed before any load
                debug.event("import", "failed", material=mat.name,
                            phase="staging", error=str(exc))
                return (False,
                        messages.MATERIAL_FAILED_TO_IMPORT % mat.name)
            debug.event("import", "failed", material=mat.name,
                        phase="load" if not locals().get("loaded_ok")
                        else "placement", error=str(exc))
            first_line = str(exc).strip().splitlines()[0] if str(exc) else ""
            if locals().get("loaded_ok"):
                return (False,
                        '"%s" was loaded but could not be placed: %s'
                        % (mat.name, first_line or exc))
            return (False,
                    '"%s" could not be imported - a node type in it is '
                    "not available in this session (is the %s plugin "
                    "installed?). %s"
                    % (mat.name, mat.renderer, first_line))
        finally:
            if self._hou_parent is not None:
                self._hou_parent.destroy()
            if not completed:
                self._undo_cop_companion()
                self._drop_created_container()

        self._verify_import_registration(mat)
        return (True, "")

    def _drop_created_container(self) -> None:
        """Take back the library or matnet THIS import made, only while it is still empty."""
        container = self._import_path
        if container is None or self._use_existing_node:
            return
        try:
            if container.children():
                return
            container.destroy()
            self._import_path = None
        except hou.Error as exc:
            debug.event("import", "could not undo the import container",
                        error=str(exc))

    def _verify_import_registration(self, mat) -> None:
        """Will it SHOW as a material? Parms only. ▸r/matlib-entries"""
        node = self._builder_node
        if node is None or self._import_path is None:
            return
        try:
            if self._import_path.type().name() != "materiallibrary":
                return
            problem = ""
            if not node.isMaterialFlagSet():
                problem = "its Material flag is not set"
            elif not getattr(self, "_entry_covered", False):
                problem = "no enabled entry in the library covers it"
            if not problem and debug.is_on():
                import loputils

                hit = any(
                    node in loputils.getEditorNodes(self._import_path, p)
                    for p in loputils.globPrimPaths(
                        self._import_path, "%type(Material)"
                    )
                )
                if not hit:
                    problem = "USD reports no material prim for it"
            if problem:
                debug.event("import", "material may not appear",
                            material=mat.name, reason=problem,
                            library=self._import_path.path())
                hou.ui.displayMessage(  # type: ignore
                    messages.IMPORTED_MATERIAL_MAY_NOT_APPEAR
                    % (mat.name, self._import_path.path(), problem)
                )
        except Exception as exc:
            debug.event("import", "registration check failed",
                        error=str(exc))

    def cleanup(self):
        """Remove what THIS import created, its COP companion too; a context node is never ours."""
        try:
            self._remove_import_target()
        finally:
            self._undo_cop_companion()    # one already in the scene is shared by name and stays

    def _remove_import_target(self) -> None:
        """Destroy the builder, or the container this import made - never a context node."""
        if not self._import_path:
            return
        target = (self._builder_node if self._use_existing_node
                  else self._import_path)
        if target is None:
            return
        try:
            if target.parent() is None or target.parent().path() == "/":
                debug.event("import", "cleanup refused a context node",
                            node=target.path())
                return
            target.destroy()
        except hou.Error as exc:
            debug.event("import", "cleanup could not remove a node",
                        node=str(target), error=str(exc))

    def update_context(self, mat: material.Material, target: str = "auto",
                       saved_type=None):
        """Set _import_path for target auto|mat|lop; only lop can fail."""
        allowed = self.import_targets(mat, saved_type)

        if target == "mat":
            world = "mat"
        elif target == "lop":
            world = "lop"
        else:  # auto
            world = self._auto_world()

        if world == "lop" and "lop" not in allowed:
            return (
                False,
                '"'
                + mat.name
                + '" is a '
                + mat.renderer
                + " VOP material and cannot be imported into a LOP/Solaris "
                + "context. Use Copy To /mat instead.",
            )

        self._use_existing_node = False    # each branch says whether it reused, for THIS import
        if world == "lop":
            refusal = self._set_lop_import_path()
            if refusal:
                return (False, refusal)
        elif world == "sop":
            self._set_sop_import_path()
        else:  # "mat" (and any fallback)
            self._import_path = hou.node("/mat")
            self._use_existing_node = True
        return (True, "")

    def _auto_world(self) -> str:
        """The editor's context as 'lop', 'sop', or 'mat' (the default)."""
        curr = self.get_current_network_node()
        if curr is None:
            return "mat"
        typename = curr.type().name()
        try:
            child_cat = curr.childTypeCategory().name().lower()
        except Exception:
            child_cat = ""
        if (
            "stage" in typename
            or "lopnet" in typename
            or "materiallibrary" in typename
            or "lop" in child_cat
        ):
            return "lop"
        if "geo" in typename or "sop" in child_cat:
            return "sop"
        return "mat"

    def _set_lop_import_path(self) -> str:
        """The Material Library the editor is in, else a refusal and nothing made."""
        from amaze import messages
        curr = self.get_current_network_node()
        if curr is not None and "materiallibrary" in curr.type().name():
            self._import_path = curr
            self._use_existing_node = True
            return ""
        return messages.LOP_IMPORT_OUTSIDE_LIBRARY

    def _set_sop_import_path(self) -> None:
        """Reuse or create ONE matnet in the current geo/SOP network."""
        curr = self.get_current_network_node()
        if curr is not None:
            existing = next(
                (child for child in curr.children()
                 if child.type().name() == "matnet"),
                None,
            )
            if existing is not None:
                self._import_path = existing
                self._use_existing_node = True
            else:
                self._import_path = curr.createNode("matnet")
        else:
            self._import_path = hou.node("/mat")
            self._use_existing_node = True

    def _builder_sidecar(self, mat: material.Material) -> str:
        """The sidecar path, or "" if the id escapes containment."""
        try:
            return builder_sidecar_path(self._preferences, mat.mat_id)
        except (hostos.PathEscape, TypeError) as exc:
            debug.event("import", "builder sidecar path refused",
                        material=mat.name, error=str(exc))
            return ""

    def _load_saved(self, mat: material.Material, saved_type=None) -> tuple:
        """Rebuild the saved builder under `_hou_parent` by its renderer's record: (ok, refusal)."""
        found = renderers.get(mat.renderer)
        if found is None:
            return (False, debug.Damage(
                '"%s" has an unrecognised renderer (%r), so there is '
                "no way to rebuild it. Re-save it from a material "
                "builder, or set its renderer in Info."
                % (mat.name, mat.renderer)))
        if found is renderers.KARMA:
            self.load_interface_mtlx(mat)
            self.load_items_file_mtlx(mat)
            return (True, "")
        if found.builder_mark and saved_type is None:    # only a renderer with its own builder asks
            saved_type = material_files.get_saved_node_type(self._preferences, mat)
        if saved_as_own_builder(found, saved_type):
            self.load_own_builder(mat)
        else:
            self.load_interface_other(mat, found.classic_container, saved_type)
            self.load_items_file(mat)
        return (True, "")

    def rebuild_saved(self, mat: material.Material, scratch: hou.Node) -> hou.Node:
        """A saved asset rebuilt inside `scratch` for reading, never placed; answers its builder."""
        self._hou_parent = scratch
        self._import_path = scratch
        self._use_existing_node = True
        ok, refusal = self._load_saved(mat)
        if not ok:
            raise hou.OperationFailed(refusal)
        return self._builder_node

    def load_interface_mtlx(self, mat: material.Material) -> None:
        """Rebuild the mtlx builder, no exec. ▸p/material-import-door"""
        self._builder_node = make_karma_builder(
            self._hou_parent, mat.name
        )
        apply_builder(
            self._builder_node,
            read_builder_sidecar(self._builder_sidecar(mat)),
        )

    def load_interface_other(self, mat: material.Material, builder_name: str,
                             saved_type=None) -> None:
        """Rebuild the saved container bare, no exec; a type this session lacks gets `builder_name`."""
        if saved_type is None:
            saved_type = material_files.get_saved_node_type(self._preferences, mat)
        saved_type = saved_type or builder_name
        known = node_type_available(saved_type)
        builder = self._hou_parent.createNode(saved_type if known else builder_name)
        for node in builder.children():
            node.destroy()
        if known:
            apply_builder(
                builder, read_builder_sidecar(self._builder_sidecar(mat)))

        builder.setName(      # `setName` takes node names only, so a display name is sanitized
            wording.sanitize_usd_path(mat.name), unique_name=True)
        builder.setGenericFlag(hou.nodeFlag.Material, True)

        self._builder_node = builder

    def load_items_file(self, mat: material.Material) -> None:
        """Load the .mat into the builder and move the builder, never its children, into place."""
        file_name = material.payload_path(
            self._preferences, mat.mat_id, self._preferences.ext
        )

        problem = load_items_strict(self._builder_node, file_name)  # names an unreadable file; it raises no OSError
        from amaze.helpers import helpers
        if problem:
            raise hou.OperationFailed(problem)

        texstore.resolve_parms(    # the whole container, before it moves
            self._builder_node, self._preferences, helpers.houdini_path)

        if self._import_path.type().name() == "materiallibrary":    # a classic container is rebuilt
            from amaze.render.material_conversion import engine    # late: its APIs import this module
            self._builder_node = engine.ready_for_solaris(self._builder_node, mat.renderer)
        new_mat = hou.moveNodesTo((self._builder_node,), self._import_path)  # type: ignore
        if not new_mat:
            raise hou.OperationFailed(
                'nothing could be moved into place for "%s" - its '
                "saved files look corrupt" % mat.name
            )
        self._builder_node = new_mat[0]
        helpers.auto_place(self._builder_node)

    def _load_into_holder(self, mat: material.Material) -> list:
        """Load the .mat into the holder `_builder_node`: the nodes it added, textures resolved."""
        file_name = material.payload_path(
            self._preferences, mat.mat_id, self._preferences.ext
        )
        pre_existing = set(self._builder_node.children())
        problem = load_items_strict(self._builder_node, file_name)
        if problem:
            raise hou.OperationFailed(problem)
        loaded = [
            c for c in self._builder_node.children() if c not in pre_existing
        ]
        if not loaded:
            raise hou.OperationFailed(nothing_loaded(mat.name, file_name))
        from amaze.helpers import helpers
        texstore.resolve_parms(    # before any move, spelled as Write Paths As says
            self._builder_node, self._preferences, helpers.houdini_path)
        return loaded

    def _place_whole_builder(self, mat: material.Material, inner) -> None:
        """The .mat held the builder itself: move it out of its holder into place, drop the holder."""
        from amaze.helpers import helpers
        moved = hou.moveNodesTo((inner,), self._import_path)[0]  # type: ignore
        holder = self._builder_node
        self._builder_node = moved
        holder.destroy()
        moved.setName(wording.sanitize_usd_path(mat.name), unique_name=True)
        moved.setGenericFlag(hou.nodeFlag.Material, True)
        helpers.auto_place(moved)
        if not surface_terminal_wired(moved):
            debug.note('Amaze: "%s" imported, but nothing is wired to its '
                "surface output - it will render black."
                % mat.name)
            debug.event("import", "surface terminal not wired",
                        material=mat.name, node=moved.path())

    def load_own_builder(self, mat: material.Material) -> None:
        """A renderer's own builder is saved whole, so one loaded subnet IS the material. ▸r/octane-builder"""
        from amaze.helpers import helpers
        self._builder_node = self._hou_parent.createNode("subnet")    # the holder
        loaded = self._load_into_holder(mat)
        if len(loaded) == 1 and loaded[0].type().name() == "subnet":
            self._place_whole_builder(mat, loaded[0])
            return
        holder = self._builder_node    # loose nodes: the holder is their container, as before
        holder.setName(wording.sanitize_usd_path(mat.name), unique_name=True)
        holder.setGenericFlag(hou.nodeFlag.Material, True)
        self._builder_node = hou.moveNodesTo((holder,), self._import_path)[0]  # type: ignore
        helpers.auto_place(self._builder_node)

    def load_items_file_mtlx(self, mat: material.Material) -> None:
        """Karma's load: the wrap is kept and the terminal picked by output data type ▸r/node-items"""
        loaded = self._load_into_holder(mat)
        from amaze.helpers import helpers
        if len(loaded) == 1 and loaded[0].type().name() == "subnet":
            self._place_whole_builder(mat, loaded[0])
            return
        replace_stock_plumbing(self._builder_node, loaded)    # one wired set, not two ▸r/save-shape

        shader_node = None
        displacement_node = None
        collect_nodes = []
        for child in loaded:
            tname = child.type().name()
            if tname == "collect":
                collect_nodes.append(child)
            elif tname == "mtlxdisplacement" and displacement_node is None:
                displacement_node = child
            elif tname in CONNECTORS:
                continue
            elif shader_node is None and (
                "surface" in child.outputDataTypes()
                or tname == "subnet"
            ):
                shader_node = child
                child.setGenericFlag(hou.nodeFlag.Material, True)
        wire_builder_output(self._builder_node, shader_node, displacement_node)
        if shader_node is not None and not surface_terminal_wired(
            self._builder_node
        ):
            debug.event(
                "karma", "loaded material has no wired surface terminal",
                material=mat.name, builder=self._builder_node.path(),
            )
            debug.note("WARNING - loaded '%s' has no wired surface "
                "terminal and will render black" % mat.name)
        for collect in collect_nodes:
            collect.destroy()
        self._builder_node.layoutChildren()
        helpers.auto_place(self._builder_node)

    COP_LIB_ROOT = "/obj/Amaze"    # the token saved files carry; the import maps it to the companion

    @property
    def cop_info(self) -> dict:
        """COP companion info from the last save ({} if none)"""
        return self._cop_info

    def _sanitize_net_name(self, name: str) -> str:
        return re.sub(r"[^\w]", "_", name)

    def _find_cop_container(self, cop_node):
        """Walk up from a COP node to the network node containing it"""
        n = cop_node
        while n is not None:
            try:
                cat = n.type().category().name().lower()
            except AttributeError:
                return None
            if cat not in ("cop2", "cop"):
                return n
            n = n.parent()
        return None

    def _collect_cop_refs(self, nodes) -> list:
        """op: parms referencing COPs, as (parm, cop_node, container)."""
        refs = []
        for parm, raw in op_path_parms(nodes):
            for p in re.findall(r"op:(/[\w/\.\-]+)", raw):
                target = hou.node(p)
                if target is None:
                    continue
                try:
                    cat = target.type().category().name().lower()
                except AttributeError:
                    continue
                if cat not in ("cop2", "cop"):
                    continue
                container = self._find_cop_container(target)
                if container is None:
                    continue
                refs.append((parm, target, container))
        return refs

    def _discard_pending_cop_promote(self) -> None:
        """Drop a staged companion that will never be promoted."""
        pending = getattr(self, "_pending_cop_promote", None)
        self._pending_cop_promote = None
        if pending:
            hostos.discard_scratch(pending[0])

    def prepare_cop_companion(self, nodes, asset_id: str, net_name: str) -> dict:
        """Save referenced op: COP networks as a companion file: the rewrite map ▸p/asset-write-unit"""
        self._cop_info = {}
        self._discard_pending_cop_promote()
        refs = self._collect_cop_refs(nodes)
        if not refs:
            return {}

        net_name = self._sanitize_net_name(net_name)
        containers = []
        for _parm, _target, container in refs:
            if container not in containers:
                containers.append(container)

        file_name = material.payload_path(
            self._preferences, asset_id, "_cop" + self._preferences.ext
        )

        with hou.undos.disabler():
            staging_parent = hou.node("/obj").createNode("subnet")
        rename_map = {}
        net_type = containers[0].type().name()
        try:
            try:
                staging = staging_parent.createNode(net_type)
            except hou.Error:
                category = ""
                try:
                    category = containers[0].childTypeCategory().name()
                except (AttributeError, hou.OperationFailed):
                    pass
                net_type = cop_nodes.CONTAINER_FOR.get(
                    category, "copnet")
                staging = staging_parent.createNode(net_type)
            for container in containers:
                items = container.allItems()
                try:
                    copies = staging.copyItems(items)
                except (AttributeError, hou.OperationFailed):
                    items = container.children()
                    copies = hou.copyNodesTo(items, staging)
                for orig, copy in zip(items, copies):
                    if isinstance(orig, hou.Node):
                        rename_map[orig.path()] = copy.name()
            ensure_asset_folder(self._preferences, file_name)  # staged before save_asset_pair runs ▸p/asset-write-unit
            scratch = hostos.unique_scratch(file_name)
            self._pending_cop_promote = (scratch, file_name)
            try:
                staging.saveItemsToFile(
                    staging.allItems(), scratch,
                    save_hda_fallbacks=hda_fallbacks_needed(
                        staging.allItems())
                )
                if not os.path.exists(scratch) or \
                        os.path.getsize(scratch) == 0:
                    raise hou.OperationFailed(
                        "the companion network file was not written (%s)"
                        % file_name)
            except Exception:
                self._discard_pending_cop_promote()
                raise
        finally:
            with hou.undos.disabler():
                staging_parent.destroy()

        path_map = {}
        for _parm, target, container in refs:
            rel = target.path()[len(container.path()) + 1 :]
            parts = rel.split("/")
            top_orig = container.path() + "/" + parts[0]
            parts[0] = rename_map.get(top_orig, parts[0])
            path_map["op:" + target.path()] = (
                "op:" + self.COP_LIB_ROOT + "/" + net_name + "/" + "/".join(parts)
            )

        self._cop_info = {"name": net_name, "type": net_type}
        debug.event("save", "cop networks saved",
                    count=len(containers),
                    root=self.COP_LIB_ROOT, name=net_name)
        return path_map

    def rewrite_cop_refs(self, nodes, path_map: dict) -> None:
        """Rewrite op: refs on Amaze's own copies, never on the artist's nodes."""
        if not path_map:
            return
        keys = sorted(path_map.keys(), key=len, reverse=True)
        for parm, raw in list(op_path_parms(nodes)):
            new = raw
            for key in keys:
                new = new.replace(key, path_map[key])
            if new != raw:
                try:
                    parm.set(new)
                except (hou.OperationFailed, hou.PermissionError):
                    pass

    def _undo_cop_companion(self) -> None:
        """Remove a companion THIS import created; a reused one is left."""
        created = getattr(self, "_created_cop_net", None)
        self._created_cop_net = None
        if created is not None:
            try:
                created.destroy()
            except hou.Error as exc:
                debug.event("import", "could not undo the COP companion",
                            error=str(exc))

    @staticmethod
    def _companion_home(beside):
        """The companion's network: /stage beside a library, /obj for /mat, the geo for a matnet."""
        obj = hou.node("/obj")
        if beside is None:
            return obj
        type_name = beside.type().name()
        parent = beside.parent()
        if "materiallibrary" in type_name and parent is not None:
            return parent
        if type_name == "matnet" and parent is not None and parent.type().name() == "geo":
            return parent
        return obj

    def companion_ref_map(self, mat) -> dict:
        """The token path saved files carry, mapped to where this import put the COP network."""
        info = getattr(mat, "cop_net", {}) or {}
        landed = getattr(self, "_cop_companion_path", None)
        if not info.get("name") or not landed:
            return {}
        return {"op:" + self.COP_LIB_ROOT + "/" + info["name"]: "op:" + landed}

    def restore_cop_companion(self, mat: material.Material, beside):
        """Restore the saved COP network beside `beside`; returns only what THIS call made."""
        from amaze.helpers import helpers
        self._cop_companion_path = None
        info = getattr(mat, "cop_net", {}) or {}
        if not info or not info.get("name"):
            return
        file_name = material.payload_path(      # the writer's own call
            self._preferences, mat.mat_id, "_cop" + self._preferences.ext
        )
        if not os.path.exists(file_name):
            debug.note("COP companion file missing for " + mat.name + " - skipped")
            return
        home = self._companion_home(beside)
        if home is None:
            debug.note("no network for the COP companion of " + mat.name + " - skipped")
            return
        existing = home.node(info["name"])
        if existing is not None and existing.childTypeCategory() is not None \
                and existing.childTypeCategory().name() in ("Cop", "Cop2"):
            self._cop_companion_path = existing.path()
            debug.event("import", "cop restored",
                        name=info["name"], reused=True)
            return
        try:
            copnet = home.createNode(info.get("type", "copnet"))
        except hou.Error:
            copnet = home.createNode("copnet")
        try:
            copnet.setName(info["name"], unique_name=True)
        except hou.OperationFailed:
            pass
        try:
            copnet.loadItemsFromFile(file_name)
        except hou.LoadWarning as warning:    # a load that SUCCEEDED: destroying it would dangle the refs
            debug.event("import", "cop companion load warning (non-fatal)",
                        material=mat.name, node=copnet.path(),
                        warning=str(warning)[:300])
        except (OSError, hou.Error) as exc:
            debug.event("import", "cop companion load failed",
                        material=mat.name, error=str(exc))
            copnet.destroy()
            return
        clear_inherited_stamps(copnet)    # ▸r/inherited-stamps
        helpers.auto_place(copnet)
        self._cop_companion_path = copnet.path()
        debug.event("import", "cop restored",
                    name=info["name"], reused=False)
        return copnet

    def save_node_cop(
        self,
        node: hou.Node,
        asset_id: str,
        update: bool = False,
        items: list | None = None,
    ) -> bool:
        """Save a COP network, or a selection inside one. ▸r/node-items"""
        from amaze.helpers import helpers
        from amaze.render import thumbs
        ui = getattr(hou, "ui", None)  # ▸r/status-bar
        if items is not None:
            net = node.parent()
            selection_nodes = [i for i in items if isinstance(i, hou.Node)]
            if not selection_nodes:
                if ui is not None:
                    ui.displayMessage(messages.NO_NODES_SELECTED_TO_SAVE)
                return False
        else:
            net = node
            selection_nodes = None
            if not node.children():
                if ui is not None:
                    ui.displayMessage(messages.NETWORK_EMPTY_NOTHING_TO_SAVE)
                return False
        file_name = material.payload_path(
            self._preferences, str(asset_id), self._preferences.ext
        )
        parms_file_name = material.payload_path(
            self._preferences, str(asset_id), ".interface"
        )
        saved_items = items if items is not None else net.allItems()
        self.save_asset_pair(
            parms_file_name, file_name, net.asCode(),
            lambda path: net.saveItemsToFile(
                saved_items, path,
                save_hda_fallbacks=hda_fallbacks_needed(saved_items),
            ),
            builder_node=net, asset_id=str(asset_id),
        )

        self._cop_info = {}
        source = helpers.pick_cop_display_child(      # by NAME, read LIVE
            net, children=selection_nodes)
        if source is not None:
            self._cop_info = {"thumb_node": source.name()}
            debug.event("save", "cop thumb source", source=source.name())
        else:
            debug.event("save", "cop thumb source", source=None)

        self.after_save_thumbnail(
            update, "Network", asset_id, node.path(),
            lambda: thumbs.ThumbNailRenderer(
                self._preferences).render_network_thumbnail(
                    cop_nodes.context_of(node, items),
                    asset_id, self._cop_info.get("thumb_node", "")))
        return True

    def import_cop_asset(
        self,
        mat: material.Material,
        context_node: hou.Node | None = None,
    ):
        """The COP import seam: (ok, reason, created), the nodes then the notes, boxes and dots; [] on refusal."""
        self._imported_cop_nodes = []
        self._imported_cop_riders = []    # notes, boxes and dots, after the nodes
        ok, reason = self._import_cop_asset_inner(
            mat, context_node=context_node)
        created = (list(self._imported_cop_nodes)
                   + list(self._imported_cop_riders)) if ok else []
        return ok, reason, created

    def _import_cop_asset_inner(
        self,
        mat: material.Material,
        context_node: hou.Node | None = None,
    ):
        """Rebuild a COP asset: direct into a matching context, else boxed."""
        from amaze.helpers import helpers
        file_name, refusal = self._payload_or_refusal(mat)
        if refusal:
            return (False, refusal)
        if not os.path.exists(file_name):
            return (False, debug.Damage(
                '"%s": asset file is missing on disk.' % mat.name))
        problem = empty_file_reason(file_name)
        if problem:
            return (False, debug.Damage('"%s": %s.' % (mat.name, problem)))
        context = str(getattr(mat, "renderer", "") or "").strip().title() \
            or "Cop"
        net_type = material_files.get_saved_node_type(self._preferences, mat) or \
            cop_nodes.CONTAINER_FOR.get(context, "copnet")

        dest = context_node
        if dest is None:
            editor = self.get_active_network_editor()
            dest = editor.pwd() if editor is not None else None

        dest_context = ""
        if dest is not None:
            try:
                dest_context = dest.childTypeCategory().name()
            except (AttributeError, hou.OperationFailed):
                dest_context = ""

        if dest is not None:
            if dest_context == context:
                before = set(dest.children())
                held = {item.path() for item in dest.allItems()}    # notes, boxes and dots too
                try:
                    dest.loadItemsFromFile(file_name)
                except hou.LoadWarning as warning:    # before hou.Error: loaded, with warnings ▸r/node-items
                    debug.event("import", "network load warning (non-fatal)",
                                file=file_name, node=dest.path(),
                                warning=str(warning)[:300])
                except (OSError, hou.Error) as exc:
                    return (
                        False,
                        debug.Damage(
                            '"%s": failed to load into %s (%s).'
                            % (mat.name, dest.path(), exc)),
                    )
                new_children = [
                    c for c in dest.children() if c not in before
                ]
                if not new_children:    # the load added no node, whatever it said ▸r/node-items
                    for item in dest.allItems():
                        if item.path() not in held:
                            try:
                                item.destroy()    # the refusal leaves the artist's network as it was
                            except hou.ObjectWasDeleted:
                                pass
                    return (False, debug.Damage(nothing_loaded(mat.name, file_name)))
                for loaded in new_children:    # only what this load added ▸r/inherited-stamps
                    clear_inherited_stamps(loaded, include_self=True)
                if new_children:
                    try:
                        dest.layoutChildren(items=new_children)
                    except (TypeError, hou.OperationFailed):
                        pass
                self._imported_cop_nodes = list(new_children)
                self._imported_cop_riders = [    # moved with the nodes, as a paste moves them
                    item for item in dest.allItems()
                    if item.path() not in held and not isinstance(item, hou.Node)]
                return (True, "")

        container = None
        if dest is not None:
            build_type = cop_nodes.container_type_in(
                dest, context, net_type
            )
            if build_type is None:
                return (
                    False,
                    '"%s" holds %s nodes and a %s network cannot hold '
                    "them - open a matching context first."
                    % (mat.name, context.upper(),
                       (dest_context or "that").upper()),
                )
            try:
                container = dest.createNode(build_type)
            except hou.Error:
                container = None
        if container is None:
            home = hou.node("/obj")
            fallback = cop_nodes.container_type_in(
                home, context, net_type) or net_type
            try:
                container = home.createNode(fallback)
            except hou.Error:
                return (
                    False,
                    '"%s": could not create a %s node in the current '
                    "network or /obj." % (mat.name, fallback),
                )
        try:
            try:
                container.setName(
                    wording.sanitize_usd_path(mat.name), unique_name=True
                )
            except hou.OperationFailed:
                pass
            target = cop_nodes.load_target_in(container, context)    # ▸r/hda-wrappers
            held = set(target.children())
            target.loadItemsFromFile(file_name)
        except hou.LoadWarning as warning:    # before hou.Error: the load succeeded
            debug.event("import", "network load warning (non-fatal)",
                        file=file_name, node=container.path(),
                        warning=str(warning)[:300])
        except (OSError, hou.Error) as exc:
            container.destroy()
            return (
                False,
                debug.Damage(
                    '"%s": failed to load the saved network (%s).'
                    % (mat.name, exc)),
            )
        if not [child for child in target.children() if child not in held]:
            container.destroy()    # ours, and empty: never left stamped in the scene
            return (False, debug.Damage(nothing_loaded(mat.name, file_name)))
        clear_inherited_stamps(container)    # before the container's own stamp below ▸r/inherited-stamps
        helpers.auto_place(container)
        try:
            container.setUserData("assetlib_id", str(mat.mat_id))
        except hou.OperationFailed:
            pass
        apply_node_color(container, mat.node_color)
        container.setCurrent(True, True)    # current and selected, as a node from the Tab menu is
        self._imported_cop_nodes = [container]
        return (True, "")

    def save_node(self, node: hou.Node, asset_id: str, update: bool) -> bool:
        """Save a material node's files and its thumbnail; the library is not touched."""
        from amaze.helpers import helpers
        self.texture_inventory = []    # filled by the save; add_asset/update copy it onto the row
        ui = getattr(hou, "ui", None)  # without a UI the refusals below still return False ▸r/status-bar
        if not ocio_set():
            if ui is not None:
                ui.displayMessage(messages.OCIO_NOT_SET)
            return False
        renderer = renderers.get(self._renderer)
        if renderer is None:
            if ui is not None:
                ui.displayMessage(messages.NODE_IS_NOT_A_MATERIAL_BUILDER)
            return False
        try:
            with helpers.preserving_selection_and_current(), \
                    hou.undos.disabler(), \
                    hou.InterruptableOperation(    # the staging copies select themselves
                        "Rendering", "Performing Tasks",
                        open_interrupt_dialog=True):
                return self._save_copy(node, asset_id, update, renderer)    # all scratch work ▸r/undo-groups
        finally:
            self._discard_pending_cop_promote()    # a save that never reached the pair keeps no companion

    def _save_copy(self, node: hou.Node, asset_id: str, update: bool, renderer) -> bool:
        """Every material save: a scratch copy, its textures adopted, the pair written, a render."""
        from amaze.helpers import helpers
        from amaze.render import thumbs
        asset_id = str(asset_id)
        kind = node.type().name()
        loose = renderer is renderers.KARMA and (
            kind == "collect" or any(surface in kind for surface in KARMA_SURFACES))
        whole = not loose and (renderer is renderers.KARMA or is_marked_builder(node, renderer))
        sources = ([n for n in helpers.get_connected_nodes(node) if n.type().name() not in CONNECTORS]
                   if loose else [node])    # a list stays a list: the thumbnail stage reads it so
        file_name = material.payload_path(self._preferences, asset_id, self._preferences.ext)
        parms_file_name = material.payload_path(self._preferences, asset_id, ".interface")
        path_map = self.prepare_cop_companion(tuple(sources), asset_id, node.name())
        with hou.undos.disabler():
            staging = hou.node("/obj").createNode("matnet")
        try:    # all after the create, so the copy is always removed
            root = (copy_network(sources, staging) if loose
                    else hou.copyNodesTo((node,), staging)[0])  # type: ignore
            if path_map:
                self.rewrite_cop_refs((root,), path_map)
            self.texture_inventory = texstore.adopt(    # on the copy: the scene node stays untouched
                root, self._preferences, texstore.asset_folder(node.name(), asset_id))
            holder, items = ((staging, (root,)) if whole    # a builder subnet keeps its own data
                             else (root, root.allItems()))    # NOT children(): a dot is no child ▸r/node-items
            self.save_asset_pair(
                parms_file_name, file_name, root.asCode(),
                lambda path: holder.saveItemsToFile(
                    items, path, save_hda_fallbacks=hda_fallbacks_needed(items)),
                builder_node=root, asset_id=asset_id)
        finally:
            with hou.undos.disabler():
                staging.destroy()
        self.after_save_thumbnail(
            update, renderer.key, asset_id, node.path(),
            lambda: thumbs.ThumbNailRenderer(self._preferences).create_thumb(
                renderer.key, sources if loose else node, asset_id))
        return True
