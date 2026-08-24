"""Node interaction with Houdini: save, import, convert. ▸r/node-items"""

import json
import os
import re
from typing import NamedTuple
import hou
import voptoolutils


from amaze.render import thumbs
from amaze.core import material
from amaze.core import texstore
from amaze.prefs import prefs
from amaze.core import debug
from amaze.helpers import helpers
from amaze.helpers import hostos


def make_karma_builder(parent: hou.Node, name: str) -> hou.Node:
    """The mtlx builder, starters gone, connectors KEPT for wiring."""
    builder = parent.createNode("subnet")
    builder.setName(helpers.sanitize_usd_path(name), unique_name=True)
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


REDSHIFT_TERMINALS = material.REDSHIFT_TERMINALS      # re-export; owned there


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
        elif tname in REDSHIFT_TERMINALS:
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




BUILDER_SUFFIX = ".builder.json"      # read, never exec'd ▸r/interface-contents
BUILDER_FORMAT = 1


def builder_sidecar_path(preferences, mat_id: str) -> str:
    """Where an asset's builder sidecar lives, contained."""
    return material.payload_path(preferences, mat_id, BUILDER_SUFFIX)


def ensure_asset_folder(preferences, path: str) -> None:
    """Make `path`'s folder if it is inside the library; refuse if it is not. ▸p/library-creation-doors"""
    folder = os.path.dirname(path)
    if not folder:
        return
    root = preferences.dir
    try:
        inside = os.path.relpath(folder, root)
    except ValueError:  # a different drive, a UNC share, or an empty path - every case relpath refuses is one that could not be inside the root anyway ▸r/relpath-valueerror
        raise hostos.PathEscape("%r does not stay inside %r" % (folder, root))
    hostos.contained_join(root, inside)  # realpath-based and tolerant of a missing base, so it answers for a library folder that is not there yet
    os.makedirs(folder, exist_ok=True)


def capture_builder(node) -> str:
    """Type, interface, non-default values as JSON. ▸p/structure-signature"""
    values = {}
    for parm in node.parms():
        expression = None
        try:
            expression = parm.expression()
        except hou.Error:      # no expression; family matters ▸r/hou-errors
            expression = None
        if expression is not None:
            values[parm.name()] = {"expr": expression}
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
            if "expr" in spec:
                parm.setExpression(spec["expr"])
            elif "str" in spec:
                parm.set(spec["str"])
            else:
                parm.set(spec["val"])
        except hou.Error as exc:
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
            handler._hou_parent = staging
            saved_type = handler.get_saved_node_type(mat)
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


def load_items_strict(node: hou.Node, file_name: str) -> str:
    """Strict load: "" or the fatal reason. ▸r/node-items"""
    try:
        if os.path.getsize(file_name) == 0:
            return ("its material file is empty (%s) - the save that "
                    "produced it did not finish" % file_name)
    except OSError as exc:
        return "its material file could not be read (%s)" % exc
    try:
        node.loadItemsFromFile(file_name)
    except hou.LoadWarning as warning:    # BEFORE hou.Error below - it is a subclass, and the broad handler would swallow the recoverable case
        text = str(warning)
        if "Bad node type" in text:
            return text.strip().splitlines()[-1].strip()
        debug.event("import", "load warning (non-fatal)",
                    file=file_name, warning=text[:300])
    except hou.Error as failure:
        return ("its material file could not be loaded (%s) - %s"
                % (file_name, str(failure).strip()
                   or "Houdini gave no reason"))
    return ""


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


def karma_destination(prefs) -> hou.Node:
    """Where a newly built material belongs: the LOP matlib, else /mat."""
    handler = NodeHandler(prefs)
    try:
        world = handler._auto_world()
    except AttributeError:
        world = "mat"      # no UI (headless): /mat is always valid
    if world == "lop":
        handler._set_lop_import_path()
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


class NodeHandler:
    """Save, import and convert, against the user's live scene."""

    def save_asset_pair(self, interface_path, mat_path, interface_text,
                        write_mat, builder_node=None, asset_id="") -> None:
        """Write an asset's files as ONE unit - unique scratches, promoted only once every one of them is written, because mat/ has no .bak tier to come back from. ▸p/asset-write-unit"""
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
            preferences = getattr(self, "_preferences", None)  # getattr, because a NodeHandler built through __new__ is a SANCTIONED fixture shape at six sites in test_atomic_write; with no library root there is no containment to prove, so nothing is created
            for destination in (interface_path, mat_path, builder_path):
                if destination and preferences is not None:  # a creation door that never reached ensure_library_dirs leaves no mat/, and mkstemp then raises FileNotFoundError with nothing on screen
                    ensure_asset_folder(preferences, destination)
            tmp_interface = hostos.unique_scratch(interface_path)
            tmp_mat = hostos.unique_scratch(mat_path)
            if builder_path:
                tmp_builder = hostos.unique_scratch(builder_path)
                with open(tmp_builder, "w", encoding="utf-8") as handle:
                    handle.write(builder_text)
            with open(tmp_interface, "w", encoding="utf-8") as handle:
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
        """Render a saved asset's thumbnail. A failure costs the thumbnail, never the asset; `render()` answers True, False, or None where this context has no picture to draw. ▸p/after-save-thumbnail"""
        if not update and not self._preferences.render_on_import:
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

    def __init__(self, preferences: prefs.Prefs) -> None:
        self._preferences = preferences
        self._builder_node = hou.node("/stage")
        self._renderer = ""
        self._import_path = None
        self._hou_parent = None
        self._use_existing_node = False
        self._cop_info = {}
        # Promoted with the .mat/.interface unit ▸p/asset-write-unit
        self._pending_cop_promote = None
        self._context_override = None

    def get_active_network_editor(self):
        """The visible NetworkEditor, else any, else None when headless."""
        try:
            editors = [
                pt
                for pt in hou.ui.paneTabs()  # type: ignore
                if pt.type() == hou.paneTabType.NetworkEditor
            ]
        except AttributeError:
            return None          # no hou.ui: headless session
        if not editors:
            return None
        visible = [e for e in editors if e.isCurrentTab()]
        return (visible or editors)[0]

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
        if node.type().name() == "redshift_vopnet":
            self._renderer = "Redshift"
        elif "rs_usd_material_builder" in node.type().name():
            self._renderer = "Redshift"
        elif node.type().name() == "octane_vopnet":
            self._renderer = "Octane"
        elif "octane_solaris_material_builder" in node.type().name():
            self._renderer = "Octane"
        elif "mtlxopen_pbr_surface" in node.type().name():
            self._renderer = "Karma"
        elif "mtlxstandard_surface" in node.type().name():
            self._renderer = "Karma"
        elif node.type().name() == "subnet":
            for n in node.children():
                if "mtlx" in n.type().name():
                    self._renderer = "Karma"
        elif node.type().name() == "collect":
            self._renderer = "Karma"
        return self._renderer

    LOP_CAPABLE_NODE_TYPES = (
        "rs_usd_material_builder",  # Redshift USD material builder
        "octane_solaris_material_builder",  # Octane Solaris material builder
    )

    def get_saved_node_type(self, mat: material.Material) -> str:
        """The builder type in the .interface's first createNode, or ""."""
        iface = material.payload_path(
            self._preferences, mat.mat_id, ".interface"
        )
        try:
            with open(iface, "r", encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            return ""
        match = re.search(r'createNode\(\s*[\'"]([^\'"]+)[\'"]', text)
        return match.group(1) if match else ""

    SHADER_TYPE_LABELS = (
        ("redshift::ToonMaterial", "Toon"),
        ("redshift::OpenPBRMaterial", "PBR"),
        ("redshift::StandardMaterial", "Standard"),
        ("redshift::MaterialBlender", "Blend"),
        ("redshift::Hair", "Hair"),
        ("redshift::Volume", "Volume"),
        ("redshift::rsOSL", "OSL"),
    )

    def get_shader_type_label(self, mat: material.Material) -> str:
        """Shader-type label by text search of the .mat. ▸r/save-shape"""
        mat_path = material.payload_path(
            self._preferences, mat.mat_id, self._preferences.ext
        )
        try:
            with open(mat_path, "rb") as fh:
                data = fh.read()
        except OSError:
            return ""
        text = data.decode("latin-1")
        for needle, label in self.SHADER_TYPE_LABELS:
            if ("type = " + needle) in text:
                return label
        return ""

    def import_targets(self, mat: material.Material) -> set:
        """Which of {"mat", "lop"} this material can be imported into."""
        if material.is_karma_renderer(mat.renderer):
            return {"mat", "lop"}
        if self.get_saved_node_type(mat) in self.LOP_CAPABLE_NODE_TYPES:
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
        ok, reason = self._import_asset_to_scene_inner(
            mat, target, context_node=context_node)
        created = ([self._builder_node]
                   if ok and self._builder_node is not None else [])
        return ok, reason, created

    def _import_asset_to_scene_inner(
        self,
        mat: material.Material,
        target: str = "auto",
        context_node: hou.Node | None = None,
    ):
        """Import a material - target "auto" reads the active editor, "mat"/"lop" force one, context_node overrides both; answers (ok, reason) and the ORDER of the refusals below is load-bearing. ▸p/material-import-door"""
        payload, refusal = self._payload_or_refusal(mat)
        if refusal:
            self._context_override = None
            return (False, refusal)
        try:
            if os.path.getsize(payload) == 0:
                self._context_override = None
                return (False,
                        debug.Damage(
                            '"%s" cannot be imported: its material file is '
                            "empty, so the save that produced it did not "
                            "finish (%s)" % (mat.name, payload)))
        except OSError as exc:
            self._context_override = None
            return (False,
                    debug.Damage(
                        '"%s" cannot be imported: its material file could '
                        "not be read (%s)" % (mat.name, exc)))

        saved_type = self.get_saved_node_type(mat)
        if saved_type and not node_type_available(saved_type):
            self._context_override = None
            return (False,
                    '"%s" needs the "%s" node type, which is not '
                    "available in this session - is the %s plugin "
                    "installed?" % (mat.name, saved_type, mat.renderer))

        self._context_override = context_node
        try:
            ok, reason = self.update_context(mat, target)
        except hou.Error as exc:
            self._context_override = None
            return (False, "cannot import here: %s" % exc)
        if not ok:
            self._context_override = None
            return (False, reason)

        parms_file_name = material.payload_path(
            self._preferences, mat.mat_id, ".interface"
        )

        self._created_cop_net = self.restore_cop_companion(mat)
        self._hou_parent = hou.node("/obj").createNode("matnet")
        completed = False
        try:
            debug.event(
                "import", "routing by renderer",
                material=mat.name, renderer=mat.renderer,
                karma_family=material.is_karma_renderer(mat.renderer),
                targets=sorted(self.import_targets(mat)),
                saved_node_type=saved_type,
            )
            if material.is_karma_renderer(mat.renderer):
                self.load_interface_mtlx(parms_file_name, mat)
                self.load_items_file_mtlx(mat)
            elif "Redshift" in mat.renderer:
                self.load_interface_other(parms_file_name, mat, "redshift_vopnet")
                self.load_items_file(mat, move_builder=True)
            elif "Octane" in mat.renderer:
                self.load_interface_other(parms_file_name, mat, "octane_vopnet")
                self.load_items_file(mat, move_builder=True)
            else:
                return (
                    False,
                    debug.Damage(
                        '"%s" has an unrecognised renderer (%r), so there is '
                        "no way to rebuild it. Re-save it from a material "
                        "builder, or set its renderer in Info."
                        % (mat.name, mat.renderer)),
                )

            loaded_ok = True
            if (
                material.is_karma_renderer(mat.renderer)
                and self._builder_node is not None
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
                if (
                    self._builder_node is not None
                    and self._builder_node.path() != "/stage"
                ):
                    self._builder_node.setUserData(
                        "assetlib_id", str(mat.mat_id)
                    )
                    apply_node_color(self._builder_node, mat.node_color)
            except (hou.OperationFailed, hou.ObjectWasDeleted) as e:
                debug.note("could not stamp imported node: " + str(e))
            completed = True
        except hou.Error as exc:
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
            self._context_override = None
            self._hou_parent.destroy()
            if not completed:
                self._undo_cop_companion()

        self._verify_import_registration(mat)
        return (True, "")

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
                    '"%s" was imported into %s but may not appear as a '
                    "material: %s."
                    % (mat.name, self._import_path.path(), problem)
                )
        except Exception as exc:
            debug.event("import", "registration check failed",
                        error=str(exc))

    def cleanup(self):
        """Remove what THIS import created; a context node is never ours."""
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

    def update_context(self, mat: material.Material, target: str = "auto"):
        """Set _import_path for target auto|mat|lop; only lop can fail."""
        allowed = self.import_targets(mat)

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

        if world == "lop":
            self._set_lop_import_path()
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

    def _set_lop_import_path(self) -> None:
        """Point at a LOP materiallibrary: reuse, else create. ▸r/matlib-entries"""
        curr = self.get_current_network_node()
        if curr is not None and "materiallibrary" in curr.type().name():
            self._import_path = curr
            self._use_existing_node = True
            return
        from amaze.core import dragengine

        if curr is not None and (
            "stage" in curr.type().name() or "lopnet" in curr.type().name()
        ):
            network = curr
        else:
            network = hou.node("/stage")
        existing = dragengine.first_materiallibrary(network)
        if existing is not None:
            self._import_path = existing
            self._use_existing_node = True
            return
        self._import_path = network.createNode("materiallibrary")

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

    def load_interface_mtlx(self, parms_file_name, mat: material.Material) -> None:
        """Rebuild the mtlx builder, no exec. ▸p/material-import-door"""
        self._builder_node = make_karma_builder(
            self._hou_parent, mat.name
        )
        apply_builder(
            self._builder_node,
            read_builder_sidecar(self._builder_sidecar(mat)),
        )

    def load_interface_other(
        self, parms_file_name: str, mat: material.Material, builder_name: str
    ) -> None:
        """Rebuild the saved container, no exec: type read, parms from sidecar."""
        saved_type = self.get_saved_node_type(mat) or builder_name
        if node_type_available(saved_type):
            builder = self._hou_parent.createNode(saved_type)
            for node in builder.children():
                node.destroy()
            apply_builder(
                builder, read_builder_sidecar(self._builder_sidecar(mat)))
        else:
            builder = self._import_path.createNode(builder_name)

        builder.setName(mat.name, unique_name=True)
        builder.setGenericFlag(hou.nodeFlag.Material, True)

        self._builder_node = builder

    def load_items_file(self, mat: material.Material, move_builder: bool = False) -> None:
        """Load the .mat; move_builder=True moves the builder, not its kids."""
        file_name = material.payload_path(
            self._preferences, mat.mat_id, self._preferences.ext
        )

        problem = load_items_strict(self._builder_node, file_name)  # absorbs the unreadable file and NAMES it; a caller that re-catches OSError here catches nothing and loses the reason
        if problem:
            raise hou.OperationFailed(problem)

        texstore.resolve_parms(self._builder_node, self._preferences)    # BEFORE the move, on the whole container - the no-builder branch moves every child, so resolving after would cover only the first sibling

        if move_builder:
            new_mat = hou.moveNodesTo((self._builder_node,), self._import_path)  # type: ignore
            if not new_mat:
                raise hou.OperationFailed(
                    'nothing could be moved into place for "%s" - its '
                    "saved files look corrupt" % mat.name
                )
            self._builder_node = new_mat[0]
            helpers.auto_place(self._builder_node)
        else:
            new_mat = hou.moveNodesTo(self._builder_node.children(), self._import_path)  # type: ignore
            if not new_mat:
                raise hou.OperationFailed(
                    'nothing could be moved into place for "%s" - its '
                    "saved files look corrupt" % mat.name
                )
            self.builder_node.destroy()
            self._builder_node = new_mat[0]

    def load_items_file_mtlx(self, mat: material.Material) -> None:
        """Karma's load: keep the wrap so every library material has ONE container shape, and pick the terminal by output data type rather than by name. ▸r/node-items"""
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
            raise hou.OperationFailed(
                'nothing could be loaded for "%s" - its .mat file looks '
                "corrupt or empty (%s)" % (mat.name, file_name)
            )
        texstore.resolve_parms(self._builder_node, self._preferences)    # before any move, on both exits below - scenes get plain absolute paths

        if len(loaded) == 1 and loaded[0].type().name() == "subnet":
            inner = hou.moveNodesTo((loaded[0],), self._import_path)[0]  # type: ignore
            outer = self._builder_node
            self._builder_node = inner
            outer.destroy()
            inner.setName(helpers.sanitize_usd_path(mat.name), unique_name=True)
            inner.setGenericFlag(hou.nodeFlag.Material, True)
            helpers.auto_place(inner)
            if not surface_terminal_wired(inner):
                debug.note('Amaze: "%s" imported, but nothing is wired to its '
                    "surface output - it will render black."
                    % mat.name)
                debug.event("import", "surface terminal not wired",
                            material=mat.name, node=inner.path())
            return

        shader_node = None
        displacement_node = None
        collect_nodes = []
        for child in loaded:
            tname = child.type().name()
            if tname == "collect":
                collect_nodes.append(child)
            elif tname == "mtlxdisplacement" and displacement_node is None:
                displacement_node = child
            elif tname in ("subnetconnector", "suboutput"):
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

    COP_LIB_ROOT = "/obj/Amaze"

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
                if "op:" not in raw:
                    continue
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
        """Save any COP networks the material references via op: paths as a companion file and answer the rewrite map; the file is written here and PROMOTED with the pair, never before it. ▸p/asset-write-unit"""
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
                from amaze.core import cop_library
                category = ""
                try:
                    category = containers[0].childTypeCategory().name()
                except (AttributeError, hou.OperationFailed):
                    pass
                net_type = cop_library.CopLibrary.CONTAINER_FOR.get(
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
            ensure_asset_folder(self._preferences, file_name)  # the companion is staged BEFORE save_asset_pair runs, so it reaches mkstemp first ▸p/asset-write-unit
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
        """Rewrite op: refs - on SAVE COPIES only, never on scene nodes."""
        if not path_map:
            return
        keys = sorted(path_map.keys(), key=len, reverse=True)
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
                if "op:" not in raw:
                    continue
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
        self._drop_created_cop_root()

    def _drop_created_cop_root(self) -> None:
        """Take back a COP root THIS import made, only while childless."""
        root = getattr(self, "_created_cop_root", None)
        self._created_cop_root = None
        if root is None:
            return
        try:
            if root.children():
                return
            root.destroy()
        except hou.Error as exc:
            debug.event("import", "could not undo the COP root",
                        error=str(exc))

    def restore_cop_companion(self, mat: material.Material):
        """Restore the saved COP network; returns only what THIS call made."""
        info = getattr(mat, "cop_net", {}) or {}
        if not info or not info.get("name"):
            return
        file_name = material.payload_path(      # the writer's own call
            self._preferences, mat.mat_id, "_cop" + self._preferences.ext
        )
        if not os.path.exists(file_name):
            debug.note("COP companion file missing for " + mat.name + " - skipped")
            return
        root = hou.node(self.COP_LIB_ROOT)
        self._created_cop_root = None
        if root is None:
            root = hou.node("/obj").createNode("subnet")
            try:
                root.setName("Amaze")
            except hou.OperationFailed:
                debug.note("could not create /obj/Amaze - COP restore skipped")
                root.destroy()
                return
            self._created_cop_root = root
        if root.node(info["name"]) is not None:
            debug.event("import", "cop restored",
                        name=info["name"], reused=True)
            return
        try:
            copnet = root.createNode(info.get("type", "copnet"))
        except hou.Error:
            copnet = root.createNode("copnet")
        try:
            copnet.setName(info["name"])
        except hou.OperationFailed:
            pass
        try:
            copnet.loadItemsFromFile(file_name)
        except (OSError, hou.Error) as exc:
            debug.event("import", "cop companion load failed",
                        material=mat.name, error=str(exc))
            copnet.destroy()
            self._drop_created_cop_root()
            return
        helpers.auto_place(copnet)
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
        ui = getattr(hou, "ui", None)  # ▸r/status-bar
        if items is not None:
            net = node.parent()
            selection_nodes = [i for i in items if isinstance(i, hou.Node)]
            if not selection_nodes:
                if ui is not None:
                    ui.displayMessage("No nodes selected - nothing to save.")
                return False
        else:
            net = node
            selection_nodes = None
            if not node.children():
                if ui is not None:
                    ui.displayMessage("The network is empty - nothing to save.")
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

        from amaze.core import cop_library
        self.after_save_thumbnail(
            update, "Network", asset_id, node.path(),
            lambda: thumbs.ThumbNailRenderer(
                self._preferences).render_network_thumbnail(
                    cop_library.CopLibrary.context_of(node, items),
                    asset_id, self._cop_info.get("thumb_node", "")))
        return True

    def import_cop_asset(
        self,
        mat: material.Material,
        context_node: hou.Node | None = None,
    ):
        """The COP import seam: (ok, reason, created); [] on refusal."""
        self._imported_cop_nodes = []
        ok, reason = self._import_cop_asset_inner(
            mat, context_node=context_node)
        created = list(self._imported_cop_nodes) if ok else []
        return ok, reason, created

    def _import_cop_asset_inner(
        self,
        mat: material.Material,
        context_node: hou.Node | None = None,
    ):
        """Rebuild a COP asset: direct into a matching context, else boxed."""
        file_name, refusal = self._payload_or_refusal(mat)
        if refusal:
            return (False, refusal)
        if not os.path.exists(file_name):
            return (False, debug.Damage(
                '"%s": asset file is missing on disk.' % mat.name))
        from amaze.core import cop_library
        context = str(getattr(mat, "renderer", "") or "").strip().title() \
            or "Cop"
        net_type = self.get_saved_node_type(mat) or \
            cop_library.CopLibrary.CONTAINER_FOR.get(context, "copnet")

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
                try:
                    dest.loadItemsFromFile(file_name)
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
                if new_children:
                    try:
                        dest.layoutChildren(items=new_children)
                    except (TypeError, hou.OperationFailed):
                        pass
                self._imported_cop_nodes = list(new_children)
                return (True, "")

        container = None
        if dest is not None:
            build_type = cop_library.CopLibrary.container_type_in(
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
            fallback = cop_library.CopLibrary.container_type_in(
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
                    helpers.sanitize_usd_path(mat.name), unique_name=True
                )
            except hou.OperationFailed:
                pass
            cop_library.CopLibrary.load_target_in(      # ▸r/hda-wrappers
                container, context).loadItemsFromFile(file_name)
        except (OSError, hou.Error) as exc:
            container.destroy()
            return (
                False,
                debug.Damage(
                    '"%s": failed to load the saved network (%s).'
                    % (mat.name, exc)),
            )
        helpers.auto_place(container)
        try:
            container.setUserData("assetlib_id", str(mat.mat_id))
        except hou.OperationFailed:
            pass
        apply_node_color(container, mat.node_color)
        self._imported_cop_nodes = [container]
        return (True, "")

    def save_node(self, node: hou.Node, asset_id: str, update: bool) -> bool:
        """Save Node wrapper for different Material Types"""
        self.texture_inventory = []    # filled by the staged save paths; add_asset/update copy it onto the row
        ui = getattr(hou, "ui", None)  # both refusals below return False on their own, so a missing screen costs the SENTENCE and never the refusal ▸r/status-bar
        if hou.getenv("OCIO") is None:
            if ui is not None:
                ui.displayMessage("Please set $OCIO first")
            return False
        val = False

        if "Redshift" in self._renderer:
            with hou.InterruptableOperation(
                "Rendering", "Performing Tasks", open_interrupt_dialog=True
            ):
                val = self.save_node_redshift(node, asset_id, update)
        elif "Octane" in self._renderer:
            with hou.InterruptableOperation(
                "Rendering", "Performing Tasks", open_interrupt_dialog=True
            ):
                val = self.save_node_octane(node, asset_id, update)
        elif material.is_karma_renderer(self._renderer):
            if (
                node.type().name() == "collect"
                or "mtlxopen_pbr_surface" in node.type().name()
                or "mtlxstandard_surface" in node.type().name()
            ):
                with hou.InterruptableOperation(
                    "Rendering", "Performing Tasks", open_interrupt_dialog=True
                ):
                    val = self.save_node_collect(node, asset_id, update)
            else:
                with hou.InterruptableOperation(
                    "Rendering", "Performing Tasks", open_interrupt_dialog=True
                ):
                    val = self.save_node_mtlx(node, asset_id, update)
        elif ui is not None:
            ui.displayMessage("Selected Node is not a Material Builder")
        return val

    def save_node_collect(self, node: hou.Node, asset_id: str, update: bool) -> bool:
        """Save a collect node's network to disk; the library is not touched."""
        file_name = material.payload_path(
            self._preferences, str(asset_id), self._preferences.ext
        )
        parms_file_name = material.payload_path(
            self._preferences, str(asset_id), ".interface"
        )

        nodetree = [      # a connector belongs to the container, not the material
            n for n in helpers.get_connected_nodes(node)
            if n.type().name() not in ("subnetconnector", "suboutput")
        ]

        with hou.undos.disabler():
            staging_parent = hou.node("/obj").createNode("matnet")
            sub_tmp = staging_parent.createNode("subnet")
        try:
            children = sub_tmp.children()
            for n in children:
                n.destroy()
            hou.copyNodesTo((nodetree), sub_tmp)  # type: ignore
            children = sub_tmp.children()

            path_map = self.prepare_cop_companion(
                tuple(nodetree), str(asset_id), node.name()
            )
            if path_map:
                self.rewrite_cop_refs((sub_tmp,), path_map)

            self.texture_inventory = texstore.adopt(
                sub_tmp, self._preferences,
                texstore.asset_folder(node.name(), asset_id))

            self.save_asset_pair(
                parms_file_name, file_name, sub_tmp.asCode(),
                lambda path: sub_tmp.saveItemsToFile(
                    children, path,
                    save_hda_fallbacks=hda_fallbacks_needed(children),
                ),
                builder_node=sub_tmp, asset_id=str(asset_id),
            )
        finally:
            with hou.undos.disabler():
                staging_parent.destroy()

        self.after_save_thumbnail(
            update, "Karma", asset_id, node.path(),
            lambda: thumbs.ThumbNailRenderer(
                self._preferences).create_thumb_mtlx(nodetree, asset_id))
        return True

    def save_node_mtlx(self, node: hou.Node, asset_id: str, update: bool) -> bool:
        """Save the MtlX node to disk; the library is not touched."""
        file_name = material.payload_path(
            self._preferences, asset_id, self._preferences.ext
        )

        parms_file_name = material.payload_path(
            self._preferences, asset_id, ".interface"
        )

        with hou.undos.disabler():
            builder = hou.node("/obj").createNode("matnet")
        try:
            copied = hou.copyNodesTo((node,), builder)  # type: ignore

            path_map = self.prepare_cop_companion((node,), str(asset_id), node.name())
            if path_map:
                self.rewrite_cop_refs((copied[0],), path_map)

            self.texture_inventory = texstore.adopt(    # on the COPY, before asCode - the scene node stays untouched and .interface agrees with .mat
                copied[0], self._preferences,
                texstore.asset_folder(node.name(), asset_id))

            self.save_asset_pair(      # EVERY part from the staging COPY
                parms_file_name, file_name, copied[0].asCode(),
                lambda path: builder.saveItemsToFile(
                    copied, path,
                    save_hda_fallbacks=hda_fallbacks_needed(copied),
                ),
                builder_node=copied[0], asset_id=str(asset_id),
            )
        finally:
            with hou.undos.disabler():
                builder.destroy()

        self.after_save_thumbnail(
            update, "Karma", asset_id, node.path(),
            lambda: thumbs.ThumbNailRenderer(
                self._preferences).create_thumb_mtlx(node, asset_id))
        return True

    def save_node_redshift(self, node: hou.Node, asset_id: str, update: bool) -> bool:
        """Saves the Redshift node to disk - does not add to library"""
        return self._save_staged_with_cop_companion(
            node, asset_id, update, "Redshift", "create_thumb_redshift")

    def save_node_octane(self, node: hou.Node, asset_id: str, update: bool) -> bool:
        """Saves the Octane node to disk - does not add to library"""
        return self._save_staged_with_cop_companion(
            node, asset_id, update, "Octane", "create_thumb_octane")

    def _save_staged_with_cop_companion(
        self, node: hou.Node, asset_id: str, update: bool,
        renderer: str, thumb_method: str,
    ) -> bool:
        """The Redshift and Octane save, which is ONE save."""
        file_name = material.payload_path(
            self._preferences, str(asset_id), self._preferences.ext
        )
        parms_file_name = material.payload_path(
            self._preferences, str(asset_id), ".interface"
        )
        path_map = self.prepare_cop_companion((node,), str(asset_id), node.name())
        with hou.undos.disabler():    # ALWAYS staged now: adoption rewrites parms, and that must land on a copy, never the scene node
            tmp_parent = hou.node("/obj").createNode("matnet")
        try:    # everything after the create is inside the try, or an adoption OSError leaves an un-undoable copy of the network in /obj, saved into the hip
            save_node = hou.copyNodesTo((node,), tmp_parent)[0]
            if path_map:
                self.rewrite_cop_refs((save_node,), path_map)
            self.texture_inventory = texstore.adopt(
                save_node, self._preferences,
                texstore.asset_folder(node.name(), asset_id))

            children = save_node.children()

            self.save_asset_pair(
                parms_file_name, file_name, save_node.asCode(),
                lambda path: save_node.saveItemsToFile(
                    children, path,
                    save_hda_fallbacks=hda_fallbacks_needed(children),
                ),
                builder_node=save_node, asset_id=str(asset_id),
            )
        finally:
            with hou.undos.disabler():
                tmp_parent.destroy()

        self.after_save_thumbnail(
            update, renderer, asset_id, node.path(),
            lambda: getattr(thumbs.ThumbNailRenderer(self._preferences),
                            thumb_method)(node, asset_id))
        return True
