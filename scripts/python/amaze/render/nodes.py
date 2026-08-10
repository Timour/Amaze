"""
Handles all Node Interaction with Houdini
"""

import json
import os
import re
from typing import NamedTuple
import hou
import voptoolutils

import importlib

from amaze.render import thumbs
from amaze.core import material
from amaze.prefs import prefs
from amaze.core import debug
from amaze.helpers import helpers
from amaze.helpers import hostos

# (module reloads consolidated into panel.py's single chain)


def make_karma_builder(parent: hou.Node, name: str) -> hou.Node:
    """Create a MaterialX Material Builder subnet matching the
    KARMA_REF reference material EXACTLY.

    A plain "subnet" is NOT a MaterialX builder: its Tab menu doesn't
    offer mtlx* nodes and its network isn't picked up as a material.
    This calls voptoolutils._setupMtlXBuilderSubnet - the same function
    Houdini's own shelf tools use.

    **Two flavours exist, and this uses the one KARMA_REF uses** (read
    from the saved reference, 2026-07-20):

    | | render_context | output nodes |
    |---|---|---|
    | Karma Material Builder | `kma` | one `suboutput` + `kma_material_properties` |
    | **MaterialX Material Builder** (KARMA_REF, this) | `mtlx` | two `subnetconnector`s: `surface_output` / `displacement_output` |

    The mtlx flavour is not just a style choice - it's also more
    ROBUST. Its output terminals are separate `subnetconnector` nodes
    each carrying its own `parmname` ("surface" / "displacement"), so
    destroying the starter shader can't wipe the terminal names the way
    it wipes a `suboutput`'s `name1`/`name2` parms (the pitch-black bug).
    `kma_rampconst` and other `kma_*` nodes still create fine here via
    createNode - the tab-menu mask only limits the interactive Tab menu,
    not programmatic creation (verified).

    Starter `mtlxstandard_surface`/`mtlxdisplacement` are removed (real
    content is built/loaded right after); the `subnetconnector` output
    nodes are KEPT. Wire the shader in with `wire_builder_output()`.

    Shared by the import path AND the Redshift->Karma converter, so a
    converted material is structurally identical to a hand-built one."""
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
    """Wire a shader (and optional displacement) into a builder's output
    terminals, for EITHER builder flavour.

    - MaterialX flavour (KARMA_REF, what make_karma_builder now makes):
      two `subnetconnector` nodes, matched by `parmname` surface /
      displacement; the shader goes into the connector's input 0.
    - Karma flavour (`suboutput`): surface = input 0, displacement =
      input 1. Kept so SAVED materials of the older flavour still wire
      correctly on load.

    Returns True if a surface terminal was found and wired."""
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
    except hou.Error as exc:
        # hou.Error, not just OperationFailed: a wrong-type source (e.g. a
        # collect node into the surface terminal) raises hou.InvalidInput,
        # a sibling - which crashed the whole conversion instead of being
        # reported. The material engine's surface_terminal_wired() check
        # then flags the unwired result.
        debug.event("karma", "could not wire builder output", error=str(exc))
        debug.note("could not wire builder output: %s" % exc)
    return False


def custom_node_color(node) -> list:
    """The node's network-editor color (the C-key palette) as
    [r, g, b], or [] when it wears the default grey - only a color the
    user actually chose is worth carrying into the library."""
    try:
        rgb = [float(c) for c in node.color().rgb()]
    except (AttributeError, TypeError, ValueError, hou.Error):
        return []
    if all(abs(c - 0.8) < 0.001 for c in rgb):
        return []
    return [round(c, 4) for c in rgb]


def apply_node_color(node, color) -> None:
    """Restore a captured node color on an imported node. Best-effort:
    a bad triple must never fail an import."""
    if not color or node is None:
        return
    try:
        node.setColor(hou.Color((color[0], color[1], color[2])))
    except (IndexError, TypeError, hou.Error):
        pass


#: Redshift's terminal node types, measured 2026-08-09 on 21.0.729 with
#: the plugin loaded: a `redshift_vopnet` ships a `redshift_material`
#: and an `rs_usd_material_builder` a `redshift_usd_material`. Neither
#: names its inputs - they are `Input 1`..`Input 8` - so there is no
#: `surface` connector to look for, and the whole node IS the terminal.
REDSHIFT_TERMINALS = ("redshift_material", "redshift_usd_material")


def surface_terminal_wired(builder) -> bool:
    """Does the builder have a surface terminal with something wired
    into it? The single invariant a material must hold - one without it
    renders pitch black, and the whole network can otherwise look
    perfect (see karma-material-builder.md).

    Three shapes, each measured rather than assumed. Karma names a
    `surface` subnetconnector or ends in a `suboutput`. Redshift ends in
    a terminal NODE (REDSHIFT_TERMINALS), which this did not know: the
    220 `rs_usd_material_builder` assets in the real library already
    passed through the `suboutput` branch, and the 180 legacy
    `redshift_vopnet` answered False by construction - a wrong answer on
    healthy materials, not a missing one."""
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
    """Turn ON every editmaterial `__activate__*` input toggle in the
    builder, RECURSIVELY.

    editmaterial (the online-import path) gives every node input an
    `__activate__<input>` toggle that defaults to **0 = off**, and a
    deactivated input is DROPPED from the USD export. So an image node
    whose `__activate__file` is 0 exports with no `inputs:file` at all -
    it reads nothing and the material renders **pitch black on
    everything**, even though the file parm holds a perfectly valid path
    at the VOP level.

    This was the real cause of the black online-imported materials. The
    thumbnail path tried to patch it but only looped over TOP-LEVEL
    nodes, so the images nested inside the `NG_` nodegraph were never
    reached. This does the whole tree, once, at build time, so the SAVED
    material is correct everywhere - thumbnail and a real object in LOP
    alike.

    Harmless where there are no such parms (the Redshift converter and
    the values path build fresh mtlx nodes that have none). Returns the
    count activated, for logging."""
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


def _first_child(parent, mat):
    """parent.children()[0], but a MISSING child is reported as the
    corruption it is.

    IndexError is not a hou.Error, so it bypassed
    import_asset_to_scene's handler entirely - verified with a 0-byte
    .interface: "IndexError: tuple index out of range" straight out of
    the import. The double-click path catches Exception, but the
    thumbnail path (create_thumbnail -> render_thumbnail ->
    grid_update_preview) does not, and there it fires BETWEEN
    layoutAboutToBeChanged and layoutChanged - leaving the Qt model
    with an unbalanced layout-change signal."""
    kids = parent.children()
    if not kids:
        raise hou.OperationFailed(
            '"%s" could not be rebuilt - its saved files look corrupt '
            "(the interface produced no nodes)" % getattr(mat, "name", "?")
        )
    return kids[0]


#: The builder sidecar: a container's OWN parameter interface and
#: values, in a form that is READ rather than executed.
#:
#: `.interface` is `asCode()` output - Python whose contract is that it
#: RUNS. Importing a material therefore executed whatever was in that
#: file, chosen by an id read verbatim out of library.json. Measured on
#: the real 548-asset library (research.md), the executed file was
#: redundant for 327 of them: Karma and legacy redshift_vopnet builders
#: come back identical from the per-renderer maker plus the .mat. The
#: one thing only it carried was rs_usd_material_builder's OpenGL
#: viewport-preview block, and that is what this file records instead.
BUILDER_SUFFIX = ".builder.json"
BUILDER_FORMAT = 1


def builder_sidecar_path(preferences, mat_id: str) -> str:
    """Where an asset's builder sidecar lives, contained."""
    return material.payload_path(preferences, mat_id, BUILDER_SUFFIX)


def capture_builder(node) -> str:
    """The builder's type, parameter interface and values, as JSON text.

    Expressions are kept AS EXPRESSIONS, never evaluated. Redshift's
    OpenGL preview parms are frequently channel references into the
    builder's own children (`iron/refl_colorr`); evaluating one would
    freeze a number where a live link belongs, and the link is the
    thing that keeps the viewport following the shader.

    Only parms that carry an expression or sit off their default are
    recorded. A default is not information - it is what the node type
    already gives - and writing them all would make every sidecar
    change whenever a node type's defaults do.
    """
    values = {}
    for parm in node.parms():
        expression = None
        try:
            expression = parm.expression()
        except hou.Error:
            # No expression on this parm. hou raises rather than
            # returning None, and the family matters: catching
            # OperationFailed alone misses PermissionError, which is a
            # SIBLING of it, not a subclass (#278).
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
                # SERIALISABLE AT CAPTURE, not at the dump below. That
                # `json.dumps` sits outside this loop, so a value it
                # refuses raises TypeError past save_asset_pair's
                # (hou.Error, PathEscape, OSError) - costing the WHOLE
                # asset, three lines under a comment promising a sidecar
                # that cannot be built will not.
                #
                # Nothing shipped reaches it. Measured 2026-08-10: a
                # promoted RAMP looks like the case and is not, because
                # its container parm reports isAtDefault() True even
                # once dialled and the components walked here are
                # Floats. This makes the promise true for whatever parm
                # type eventually does, at the cost of one dump per
                # non-default parm on one container.
                json.dumps(value)
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
    """The sidecar as a dict, or {} when it is absent or unusable.

    Absent is ordinary: every asset saved before this format existed has
    no sidecar, and the loader degrades rather than refusing. Unusable
    is reported - a sidecar that will not parse is a damaged asset, and
    silence there is how a library rots quietly.
    """
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
    if data.get("format", 1) > BUILDER_FORMAT:
        # A newer Amaze wrote it. Read what is understood rather than
        # refusing: the dialog script and values are the whole payload,
        # and a future field this build ignores costs nothing.
        debug.event("import", "builder sidecar from a newer format",
                    path=path, format=data.get("format"))
    return data


def apply_builder(node, data: dict) -> None:
    """Put a captured interface and its values back onto a builder.

    The dialog script is applied FIRST: the values that follow may name
    spare parms that only exist once it has been set. Failures are
    reported per parm rather than aborting - a material with one parm
    missing is still a material, while a refusal here would lose the
    whole asset over a single renamed parameter.
    """
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
    """A digest of a network's SHAPE: nodes, types and wiring - no
    parameter values.

    The Versions decision rule needs exactly this question answered:
    "same nodes, same wiring, only values differ" is a new version;
    anything else is the structural path (Update Existing). A textual
    diff of the saved files cannot answer it - research.md records that
    the .interface carries container-only data with no child parameter
    values - so the old network has to be INSTANTIATED and both walked.

    Walked by relative path, type and connections, sorted, so node
    creation order and layout positions cannot leak in: two networks
    that differ only in where the nodes sit on the canvas are the same
    structure.
    """
    # A LONE WRAPPING CONTAINER IS TRANSPARENT. The two save branches
    # store the same material differently - children flat in the .mat,
    # or the builder node itself - and the import unwraps either, so a
    # save/re-save cycle can add or drop one packaging layer with zero
    # user intent behind it. Measured: the same 12-node material staged
    # flat before a re-save and nested one level after, every node
    # identical. Descend through solitary containers so the signature
    # reads the material, not the app's own wrapping.
    while True:
        children = node.children()
        if len(children) == 1 and children[0].children():
            node = children[0]
            continue
        break

    # BUILDER PLUMBING IS TRANSPARENT TOO. subinput / subnetconnector /
    # suboutput are the container's contract, created by
    # make_karma_builder and wired by the importer - one save branch
    # stores them, another does not, with zero user intent in the
    # difference (measured: the same material re-saved grew exactly the
    # connector set and their two wires). A rewire of the plumbing alone
    # therefore reads as parameter-only and becomes a VERSION - a
    # version capturing the change loses nothing, while reading the
    # app's own scaffolding as structure made every save structural.
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
    """Instantiate a saved asset in a throwaway /obj staging network and
    hand it to `loader(staged_node)`; the staging is destroyed on the
    way out whatever happens.

    The proven staging shape save_node_collect and the importer already
    use, factored so the Versions decision rule (load the OLD version,
    signature both, compare) does not grow its own copy. Undo-disabled:
    createNode/destroy on the live stack is resurrection-by-undo (#278).
    """
    with hou.undos.disabler():
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
    """loadItemsFromFile in STRICT mode, where a missing node type is
    reported instead of silently substituted with an 'add' node.

    Returns "" on success, or the fatal reason. Strict mode raises
    hou.LoadWarning for ANY warning, so only the missing-type
    signature is treated as fatal - every other warning is logged and
    the load stands, exactly as it did before strict mode."""
    # A missing or empty file is UNAMBIGUOUS, and Houdini's own parser
    # reports it as "Bad node type" - which sends the user hunting for
    # an uninstalled plugin instead of a corrupt save. (A partially
    # truncated file genuinely cannot be told apart from a missing type,
    # so that one keeps Houdini's wording.)
    try:
        if os.path.getsize(file_name) == 0:
            return ("its material file is empty (%s) - the save that "
                    "produced it did not finish" % file_name)
    except OSError as exc:
        return "its material file could not be read (%s)" % exc
    try:
        node.loadItemsFromFile(file_name)
    except hou.LoadWarning as warning:
        text = str(warning)
        if "Bad node type" in text:
            return text.strip().splitlines()[-1].strip()
        debug.event("import", "load warning (non-fatal)",
                    file=file_name, warning=text[:300])
    return ""


def node_type_available(type_name: str) -> bool:
    """Is a saved builder's node type instantiable in this session?

    Checked across EVERY node-type category, not just VOP: the saved
    types span categories (a Karma builder is a Vop subnet, but
    redshift_vopnet/octane_vopnet are vopnet container types living
    elsewhere), so a single-category lookup answers None for types
    that are perfectly available and would refuse valid imports."""
    if not type_name:
        return True
    try:
        for category in hou.nodeTypeCategories().values():
            if category.nodeType(type_name) is not None:
                return True
    except (AttributeError, hou.Error):
        # Unknown-shaped API: never block an import on the check.
        return True
    return False


def register_in_materiallibrary(library, builder) -> bool:
    """Make `builder` a material OF `library` - the one registration
    every producer shares (library import, the Generator Engine, and
    any future converter or bulk migration).

    ONE entry per material, and only when needed: a fresh
    materiallibrary ships a WILDCARD entry (matnode "*", flag-filtered)
    that already exposes every material-flagged VOP inside it. Per VOP
    the FIRST matching entry wins, so an appended covered entry would
    be a DEAD entry - inert now, but it springs to life and can
    retarget the prim path if the wildcard is later narrowed (wiki,
    corrected #232). Only ENABLED entries count as coverage: a
    disabled matching entry would otherwise make the material silently
    never appear. When appending: reuse an all-default instance first
    (SideFX's own drop behavior), and never rebuild the multiparm - the
    old reset+fillmaterials dirtied every material per drop (measured:
    stage cook growing 14ms->76ms over twelve imports).

    Returns True when the builder ends up covered by an entry (found or
    appended) - the caller's verification reads that instead of
    scanning the entries again.
    """
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
    """Where a NEWLY BUILT material belongs for the context the user is
    working in: the current LOP material library (reused per the drop
    placement law, created there if the network has none) when the
    active editor is a LOP context, else /mat. The Generator Engine's
    destination resolver - the same routing imports use, without
    needing a library material to ask about."""
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
    """True when any saved node (recursively) is an HDA defined
    OUTSIDE Houdini's own install - embedding definitions for those
    materials (and only those) keeps the .mat loadable on machines
    without the third-party asset; shipped HDAs (every mtlx VOP)
    never need it, and compiled plugin types (Redshift) cannot be
    embedded at all."""
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
    """What the Material Engine hands back, read by NAME.

    `wired` is the engine's own verdict on its own output - False means
    the material has a shader and no wired surface terminal, so it
    renders black. It was computed, logged and dropped, which left
    every caller holding a non-None shader and no way to tell.

    Unpacks as three; the two-value form it replaced is why the callers
    below all had to be visited when this became a named value.
    """

    builder: object
    shader: object
    wired: bool


def build_karma_material(parent, name, produce):
    """THE Karma material engine - one funnel every input goes through.

    Redshift conversion, online MaterialX import and re-import of a saved
    material are ADAPTERS: each only knows how to produce a shader network
    inside a builder. Everything universal - the KARMA_REF container, the
    output wiring, the layout, and the one invariant check - lives here,
    so a new input type is a new `produce` callback and nothing else, and
    a structural bug is fixed once for every input.

    `produce(builder)` builds the shading network inside `builder` and
    returns the surface shader node, or a `(shader, displacement)` tuple.
    Returns `(builder, shader)`; `shader` is None if the adapter produced
    nothing (the caller decides how to report that)."""
    builder = make_karma_builder(parent, name)
    result = produce(builder)
    if isinstance(result, tuple):
        shader, displacement = (result + (None,))[:2]
    else:
        shader, displacement = result, None

    if shader is not None:
        wire_builder_output(builder, shader, displacement)

    # Activate every input toggle, recursively - without this,
    # editmaterial-derived materials export with their texture `file`
    # inputs stripped and render pitch black (see activate_shader_inputs).
    activated = activate_shader_inputs(builder)
    if activated:
        debug.event("karma", "activated shader inputs",
                    material=name, count=activated)

    builder.layoutChildren()

    wired = shader is None or surface_terminal_wired(builder)
    if not wired:
        # The check that would have caught the pitch-black bug on day one.
        debug.event(
            "karma", "material has no wired surface terminal",
            material=name, builder=builder.path(),
            children=[c.type().name() for c in builder.children()],
        )
        debug.note("WARNING - '%s' has no wired surface terminal and "
            "will render black (see karma-material-builder.md)" % name)
    # THE VERDICT TRAVELS WITH THE MATERIAL, and it is why this is a
    # named value rather than a bare pair (overview.md ▸ A VALUE
    # CARRIES ITS OWN NAME). The engine computed `wired` and then threw
    # it away, so every caller had a non-None shader and no way to
    # learn the material renders black: the Redshift conversion stored
    # the asset and reported it fully converted, and the online import
    # said the same.
    return KarmaMaterial(builder, shader, wired)


class NodeHandler:
    """
    Handles all Node Interaction with Houdini
    """

    def save_asset_pair(self, interface_path, mat_path, interface_text,
                        write_mat, builder_node=None, asset_id="") -> None:
        """Write an asset's .interface and .mat as ONE unit.

        The two files ARE one asset - the .interface holds the promoted
        parameters, the .mat the nodes - and every save wrote the
        .interface FIRST, with a plain open(..., "w") that truncates,
        then attempted the .mat. So a .mat write that failed (disk full,
        permissions, a cloud-sync hiccup - and this library lives in a
        synced folder) left the new .interface on disk beside a stale or
        missing .mat, with the library row still pointing at the pair.

        Verified by forcing saveItemsToFile to fail on an Overwrite: the
        .interface had already been rewritten (57177 bytes against the
        old 57023) and the previous good asset was unrecoverable.

        Both files are written to siblings and promoted only after BOTH
        succeed. The two replaces are not one atomic operation - nothing
        portable is - but they are two renames of fully-written files,
        microseconds apart, instead of a truncation followed by work
        that can fail.

        write_mat(path) does the .mat write; it is a callback because
        every caller saves a different node with different arguments.

        THE SCRATCH NAMES MUST BE UNIQUE. They were FIXED - `<dest> +
        ".writing"` for both files - which is one shared buffer per
        destination, the same defect class already measured and fixed for
        the JSON writers: two processes x 600 saves through a fixed name
        produced 790 unparseable reads and 794 that PARSED while holding
        records from BOTH writers, with the destination left larger than
        either document.

        This is the worst place in the package to carry that defect, on
        two counts. The `.mat`/`.interface` pair IS the asset rather than
        an index of assets, so a mixture of two writers is not a
        recoverable inconsistency - it is a material that no longer
        exists. And `mat/` has no `.bak-*` tier at all: the databases get
        snapshot_before_write, asset content gets nothing, so there is
        nothing to restore from.

        MEASURED HERE, and the null result that came first is the
        interesting part. A review pass could not reproduce mixed content
        at 20KB payloads in ~7000 samples - because a payload handed to
        one write() call is close enough to atomic to hide the
        interleaving entirely. Real writers do not write that way:
        json.dump emits many small writes, and so does Houdini's own
        saveItemsToFile. Re-run at 512-byte granularity, two processes x
        400 saves of a 20KB pair:

            fixed name   344 of 4800 reads held BOTH writers' bytes
                         417 of 800 saves RAISED, because one writer's
                         cleanup removes the scratch the other is about
                         to rename
            unique name  0 mixed, 0 raised, 0 scratch files left

        The raising half is its own defect and it lands exactly where this
        function is least able to absorb it: the .interface promote can
        succeed and the .mat promote then fail on a scratch the other
        writer deleted, which is the half-written asset this whole
        function exists to prevent.
        """
        # BOTH created INSIDE the try, so the cleanup covers both. With the
        # first call outside it, a failure of the SECOND - the directory is
        # full, the process is out of descriptors - left the first scratch
        # in mat/ with nothing to remove it, which is the unowned file in
        # the library directory that discard_scratch exists to prevent. The
        # window is small (both calls hit the same directory microseconds
        # apart) and closing it costs one line.
        # Composed HERE rather than at each of the six call sites: the
        # sidecar must describe the same node whose asCode() is being
        # written, and six chances to pass the wrong one is six chances
        # to write a sidecar that belongs to another material.
        builder_path = builder_text = ""
        if builder_node is not None and asset_id:
            try:
                builder_path = builder_sidecar_path(
                    self._preferences, str(asset_id))
                builder_text = capture_builder(builder_node)
            except (hou.Error, hostos.PathEscape, OSError) as exc:
                # A sidecar that cannot be built must not cost the asset.
                # The other two files still describe a loadable material;
                # what is lost is the container's spare parms, which the
                # loader already degrades for gracefully.
                debug.event("save", "builder sidecar not written",
                            asset_id=str(asset_id), error=str(exc))
                builder_path = builder_text = ""

        tmp_interface = tmp_mat = tmp_builder = ""
        try:
            tmp_interface = hostos.unique_scratch(interface_path)
            tmp_mat = hostos.unique_scratch(mat_path)
            # THREE files now, still one unit. The builder sidecar
            # records the container's own parameter interface in a form
            # that is read rather than executed; it is written under the
            # same all-or-nothing rule as the other two, because an
            # asset whose sidecar promoted and whose .mat did not is the
            # same half-written asset this function exists to prevent.
            if builder_path:
                tmp_builder = hostos.unique_scratch(builder_path)
                with open(tmp_builder, "w", encoding="utf-8") as handle:
                    handle.write(builder_text)
            with open(tmp_interface, "w", encoding="utf-8") as handle:
                handle.write(interface_text)
            write_mat(tmp_mat)
            # SIZE, not existence. unique_scratch has already created the
            # file (that is what makes the name safe to hold), so the old
            # `os.path.exists` check can no longer tell "written" from
            # "not written" - and a 0-byte .mat is exactly what a failed
            # saveItemsToFile leaves. A saved network is never empty.
            if not os.path.exists(tmp_mat) or os.path.getsize(tmp_mat) == 0:
                raise hou.OperationFailed(
                    "the material file was not written (%s)" % mat_path
                )
            # Both fsynced and promoted only after BOTH are fully written.
            # Two renames microseconds apart are not one atomic operation
            # - nothing portable is - but they are two renames of complete
            # files instead of a truncation followed by work that can fail.
            # FOUR files when the asset has a COP companion. It is a
            # file of this same asset, staged by prepare_cop_companion
            # before the .mat was written (the rewrite map comes from
            # it) and promoted here so the set lands together. It went
            # over its destination at staging time, so a .mat failure
            # left the NEW companion beside the OLD material.
            pending = getattr(self, "_pending_cop_promote", None)
            if pending:
                hostos.promote_scratch(pending[0], pending[1])
                self._pending_cop_promote = None
            if tmp_builder:
                hostos.promote_scratch(tmp_builder, builder_path)
            hostos.promote_scratch(tmp_interface, interface_path)
            hostos.promote_scratch(tmp_mat, mat_path)
        finally:
            # A scratch left in mat/ is not merely untidy: Clean Library
            # scans that directory, and an unowned file there is the kind
            # of thing that gets classified as an orphan.
            for leftover in (tmp_interface, tmp_mat, tmp_builder):
                hostos.discard_scratch(leftover)
            # The companion too, on the failure path: promoting it left
            # _pending_cop_promote None, so this only fires when the
            # unit did not land - which is exactly when the previous
            # companion must be left where it is.
            self._discard_pending_cop_promote()

    def __init__(self, preferences: prefs.Prefs) -> None:
        self._preferences = preferences
        self._builder_node = hou.node("/stage")
        self._builder = 0
        self._renderer = ""
        self._import_path = None
        self._hou_parent = None
        self._use_existing_node = False
        self._cop_info = {}
        #: (scratch, destination) for a COP companion written but not
        #: yet promoted - it lands with the .mat/.interface unit in
        #: save_asset_pair, never before it.
        self._pending_cop_promote = None
        # Optional explicit network context (a materiallibrary node or
        # an editor's pwd) that overrides the active-editor lookup -
        # set per-import by import_asset_to_scene(context_node=...),
        # used by the material drag where the destination is the editor
        # under the RELEASE POINT, not the active one.
        self._context_override = None

    def get_active_network_editor(self):
        """Return the NetworkEditor pane the user is most likely looking
        at, or None when there is no UI at all (headless hython: the
        thumbnail and report harnesses run there, and an AttributeError
        from hou.ui would take the whole render down).

        Prefers a pane that is the visible (current) tab in its split,
        falling back to any open NetworkEditor. Returns None if none exist.
        Replaces the old "first NetworkEditor in paneTabs()" behaviour, which
        picked an arbitrary editor when several were open and made
        context-aware import land in the wrong network."""
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
        """Return the network node currently displayed in the active editor.

        Uses the editor's pwd() (the network whose children are shown)
        instead of currentNode().parent(), which crashed when nothing was
        current in the picked pane. An explicit per-import context
        (self._context_override, e.g. the release point of a drag) wins
        over the active-editor lookup."""
        if self._context_override is not None:
            return self._context_override
        editor = self.get_active_network_editor()
        if editor is None:
            return None
        return editor.pwd()

    @property
    def builder_node(self) -> hou.Node:
        """
        Docstring for builder_node

        :param self: Description
        :return: Description
        :rtype: Node
        """
        return self._builder_node

    @property
    def builder(self) -> int:
        """
        Docstring for builder

        :param self: Description
        :return: Description
        :rtype: int
        """
        return self._builder

    @property
    def renderer(self) -> str:
        """
        Docstring for renderer

        :param self: Description
        :return: Description
        :rtype: str
        """
        return self._renderer

    def get_renderer_from_node(self, node: hou.Node) -> str:
        """
        Get the renderer based on the node type of the given node

        :param self: Description
        :param node: Description
        :type node: hou.Node
        :return: Description
        :rtype: str
        """
        if node.type().name() == "redshift_vopnet":
            self._renderer = "Redshift"
            self._builder = 1
        elif "rs_usd_material_builder" in node.type().name():
            self._renderer = "Redshift"
            self._builder = 1
        elif node.type().name() == "materialbuilder":
            self._renderer = "Mantra"
            self._builder = 1
        elif node.type().name() == "principledshader::2.0":
            self._renderer = "Mantra"
            self._builder = 0
        elif node.type().name() == "octane_vopnet":
            self._renderer = "Octane"
            self._builder = 1
        elif "octane_solaris_material_builder" in node.type().name():
            self._renderer = "Octane"
            self._builder = 1
        elif "mtlxopen_pbr_surface" in node.type().name():
            self._renderer = "Karma"
            self._builder = 0
        elif "mtlxstandard_surface" in node.type().name():
            self._renderer = "Karma"
            self._builder = 0
        elif node.type().name() == "subnet":
            self._builder = 1
            for n in node.children():
                if "mtlx" in n.type().name():
                    self._renderer = "Karma"
        elif node.type().name() == "collect":
            self._renderer = "Karma"
            self._builder = 0
        return self._renderer

    # --- Import target capability ------------------------------------------
    # Node types that CAN live in a LOP/Solaris context (in addition to
    # Karma/MaterialX, which are recognised by renderer, not by type name).
    LOP_CAPABLE_NODE_TYPES = (
        "rs_usd_material_builder",  # Redshift USD material builder
        "octane_solaris_material_builder",  # Octane Solaris material builder
    )

    def get_saved_node_type(self, mat: material.Material) -> str:
        """Return the true builder node type recorded in a material's
        .interface file. asCode() writes a createNode("<type>", ...) call, so
        the first such type is the builder that was saved. Returns "" if the
        file is missing or unreadable."""
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

    # Redshift shader/material node type -> short display label, checked
    # in this order (most specific first) against the .mat file's raw
    # text. Not a rigorous graph walk - the same "good enough for a
    # label" text-search approach get_saved_node_type() already uses for
    # the outer builder type, just applied to the inner shader.
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
        """Best-effort label for the material's actual shader type
        (Standard/PBR/Toon/...) - the .mat file (saveItemsToFile format)
        is a Houdini "item file": mostly binary framing with real ASCII
        text segments in between, including literal "type = redshift::X"
        node-type declarations, so a plain text search works without
        needing to parse the format properly. Returns "" if the file is
        missing/unreadable or no known shader type is found."""
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
        """Return the contexts a material can be imported into: a subset of
        {"mat", "lop"}.

        - Karma/MaterialX mix freely -> both.
        - Redshift USD builder (and any LOP_CAPABLE_NODE_TYPES) -> both.
        - Classic redshift_vopnet / octane_vopnet / Mantra -> "mat"
          only; importing them into a LOP context is impossible.
        """
        if material.is_karma_renderer(mat.renderer):
            return {"mat", "lop"}
        if self.get_saved_node_type(mat) in self.LOP_CAPABLE_NODE_TYPES:
            return {"mat", "lop"}
        return {"mat"}

    def _payload_or_refusal(self, mat) -> tuple:
        """`(path, "")` when this asset's payload path may be built, or
        `("", sentence)` naming why it may not.

        ONE ANSWER FOR EVERY IMPORT DOOR. The Material door asked both
        questions and the Node door asked neither, so a hand-edited row
        produced a sentence in one section and an uncaught `PathEscape`
        out of a double-click in the other. Nothing was ever written
        outside the library - `payload_path` contains it - but a
        traceback is not a refusal: `PathEscape` is a `ValueError`, and
        nothing on that route catches one.

        `is_safe_asset_id` is the door at the record and the
        containment is the door at the path; this pairs them so a third
        door cannot open with only one.
        """
        if not material.is_safe_asset_id(mat.mat_id):
            debug.event("import", "refused unsafe asset id",
                        material=mat.name, mat_id=str(mat.mat_id)[:120])
            return ("",
                    '"%s" cannot be imported: its id is not a usable file '
                    "name, so the files it points at cannot be trusted to "
                    "be inside your library" % mat.name)
        try:
            return (material.payload_path(
                self._preferences, mat.mat_id, self._preferences.ext), "")
        except hostos.PathEscape:
            # Belt and braces. is_safe_asset_id already excludes
            # separators, so reaching here means the composition escaped
            # some other way - a symlink planted in mat/, or an
            # asset_dir out of a tampered settings file.
            debug.event("import", "refused escaping asset path",
                        material=mat.name, mat_id=str(mat.mat_id)[:120])
            return ("",
                    '"%s" cannot be imported: its files resolve to '
                    "somewhere outside your library" % mat.name)

    def import_asset_to_scene(
        self,
        mat: material.Material,
        target: str = "auto",
        context_node: hou.Node | None = None,
    ):
        """The import seam: (ok, reason, created), where created is
        the list of top-level nodes this import added to the scene -
        what every placement rule builds on, so no caller has to
        guess by diffing children. Empty on refusal. The body with
        its refusals is the inner method, untouched."""
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
        """Import a Material to the Network Editor/Scene.

        target: "auto" derives the destination from the active network editor
        (double-click behaviour); "mat" forces /mat; "lop" forces a LOP
        materiallibrary. context_node optionally overrides the active-editor
        lookup with an explicit destination context (the material drag's
        release point). Returns (ok, reason): if the material cannot live in
        the requested context, ok is False, reason explains why, and nothing
        is imported."""
        # Missing-plugin pre-check FIRST: update_context() below is not
        # side-effect free (it creates a materiallibrary/matnet when the
        # context has none), so refusing after it would leave an
        # unwired orphan library behind - and the drop policy then
        # picks that orphan for every later import in the network.
        # A corrupt payload BEFORE the plugin question, or the answer
        # is misleading: a zero-byte .mat made this report "a node type
        # is not available - is the plugin installed?", sending the user
        # to hunt for a plugin instead of a save that never finished.
        # The id BEFORE it becomes a path. It is read verbatim out of
        # library.json, so it is not the app's own word - with the id
        # "../../.ssh/authorized_keys" the ordinary composition below
        # resolves outside the library entirely, and a tampered index
        # then chooses which file every step after this one opens.
        #
        # Refused here rather than at each composition site: this is the
        # single door into the import, and the checks downstream would
        # each have to remember. The row itself is left alone - an index
        # row is user data, and this is a refusal to ACT on it, not a
        # reason to drop it.
        payload, refusal = self._payload_or_refusal(mat)
        if refusal:
            self._context_override = None
            return (False, refusal)
        try:
            if os.path.getsize(payload) == 0:
                self._context_override = None
                return (False,
                        '"%s" cannot be imported: its material file is '
                        "empty, so the save that produced it did not "
                        "finish (%s)" % (mat.name, payload))
        except OSError as exc:
            self._context_override = None
            return (False,
                    '"%s" cannot be imported: its material file could '
                    "not be read (%s)" % (mat.name, exc))

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
            # update_context resolves the destination and may CREATE a
            # container to reach it (_set_sop_import_path does
            # curr.createNode("matnet")). Dropping onto a network editor
            # dived into a locked asset makes that raise
            # hou.PermissionError - a SIBLING of OperationFailed, not a
            # subclass, which is the trap _import_geo_in_context already
            # documents. It escaped the release slot entirely, and via
            # the press-state leak it also armed a phantom drag.
            #
            # hou.Error is the common base, so this catches the whole
            # family rather than guessing which one.
            self._context_override = None
            return (False, "cannot import here: %s" % exc)
        if not ok:
            self._context_override = None
            return (False, reason)

        parms_file_name = material.payload_path(
            self._preferences, mat.mat_id, ".interface"
        )

        # Remembered so a FAILED import can take it back out: this runs
        # before the load (the material's op: references need it), so a
        # refusal further down used to leave /obj/Amaze/<netname> behind
        # in the scene - verified live after a corrupt-companion refusal.
        self._created_cop_net = self.restore_cop_companion(mat)
        self._hou_parent = hou.node("/obj").createNode("matnet")
        # The rollback is owned by the FINALLY, not by one exit. It was
        # wired into `except hou.Error` alone, so the unrecognised-
        # renderer refusal below - which returns from inside the try -
        # left /obj/Amaze/<netname> in the user's scene: they were told
        # the material could not be rebuilt AND got a network they never
        # asked for. Reproduced with a renderer:"" row carrying a
        # cop_net. A flag rather than a return-value check, so the next
        # early return added here cannot miss it either.
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
            # SUBSTRING, matching the save side and its two classic
            # siblings below. Import matched exact equality while
            # save_node matched containment, so Mantra was the one
            # renderer whose label could save one way and fail to
            # import - falling into the unrecognised-renderer refusal.
            elif "Mantra" in mat.renderer:
                self.load_interface_mantra(parms_file_name, mat)
                # move_builder=True: the .mat stores the builder's
                # CHILDREN, so the rebuilt builder has to be kept and
                # moved. With False it moved the children out and
                # destroyed the builder - measured: five loose VOPs
                # (surface_globals, displacement_globals, two outputs,
                # output_collect) dumped straight into /mat, no material
                # builder, material flag unset. A later "Rerender
                # Thumbnail" then called cleanup(), which destroyed one
                # of them and left the other four in the user's /mat
                # permanently.
                self.load_items_file(mat, move_builder=True)
            elif "Redshift" in mat.renderer:
                self.load_interface_other(parms_file_name, mat, "redshift_vopnet")
                self.load_items_file(mat, move_builder=True)
            elif "Octane" in mat.renderer:
                self.load_interface_other(parms_file_name, mat, "octane_vopnet")
                self.load_items_file(mat, move_builder=True)
            else:
                # NO else meant an unrecognised renderer label imported
                # NOTHING and reported success: (True, "") with an empty
                # scene and no message. Neither is_karma_renderer nor
                # "Mantra"/"Redshift"/"Octane" matches "" or the
                # Material class default "MatX", and the committed
                # fixture library already contains a row with
                # renderer: "". Worse, _builder_node was still its
                # __init__ default hou.node("/stage"), so a later
                # "Rerender Thumbnail" reached cleanup() and called
                # destroy() on /stage.
                return (
                    False,
                    '"%s" has an unrecognised renderer (%r), so there is '
                    "no way to rebuild it. Re-save it from a material "
                    "builder, or set its renderer in Edit Info."
                    % (mat.name, mat.renderer),
                )

            loaded_ok = True
            # Karma builders were assembled in the staging matnet -
            # ONE move into the destination, one preview-shader pass.
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

            # Setup MaterialLibrary if Import Context was such
            if self._import_path.type().name() == "materiallibrary":
                with debug.timed("import", "amaze wiring"):
                    self._entry_covered = register_in_materiallibrary(
                        self._import_path, self._builder_node
                    )

            # Stamp the imported builder with its library id so a later
            # "Save to Amaze" on this node can offer update-instead-
            # of-duplicate. Best-effort: a failed stamp only means the
            # save flow falls back to name matching.
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
            # LAST statement of the try body: everything below is the
            # success path, so the finally can tell an import that got
            # here from one that returned or raised on the way.
            completed = True
        except hou.Error as exc:
            # Strict loads raise hou.LoadWarning naming each missing
            # node type ("Bad node type found: ..."), and exec of an
            # .interface without its plugin raises OperationFailed -
            # both become a clean refusal instead of an uncaught
            # traceback (the old handlers caught OSError, which
            # catches neither). A failure AFTER the load is a
            # different animal and says so: the material is already in
            # the scene by then, and blaming a missing plugin would
            # send the user hunting the wrong thing.
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
            # Runs even on failure so the temporary staging matnet never
            # lingers in /obj (same class of leak as the thumbnail
            # interrupt-safety hardening, applied here to the import path).
            self._context_override = None
            self._hou_parent.destroy()
            # Any exit that is not the success path takes the COP
            # companion back out with it. Safe to reach twice: the
            # first call clears _created_cop_net.
            if not completed:
                self._undo_cop_companion()

        self._verify_import_registration(mat)
        return (True, "")

    def _verify_import_registration(self, mat) -> None:
        """Confirm the import will actually SHOW as a material, without
        paying for a cook.

        The silent-miss classes are all visible in the parms: a cleared
        material flag, or no enabled entry covering the builder. Both
        are free to check. The USD ground truth (globPrimPaths, how
        SideFX's own drop flow decides "already defined") is the
        certain answer but forces the library's full retranslation -
        measured 120ms on a 21-material library, per import - so it
        runs only with Debug Mode on, where diagnosis is the point."""
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
                # The wiring block already resolved coverage (and
                # appended an entry when there was none) - rescanning
                # here would repeat that work to reach the same answer.
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
        """Remove what THIS import created. Nothing else.

        _builder_node's __init__ default is hou.node("/stage"), so an
        import that never got as far as building one - an unrecognised
        renderer used to reach here - made this call destroy() on
        /stage. Houdini refuses, so there was no scene loss, but the
        hou.OperationFailed escaped create_thumbnail's finally as a raw
        traceback. A context node is never ours to delete."""
        if not self._import_path:
            return
        target = (self._builder_node if self._use_existing_node
                  else self._import_path)
        if target is None:
            return
        try:
            if target.parent() is None or target.parent().path() == "/":
                # /obj, /stage, /mat, /out - a root context, not
                # something an import created.
                debug.event("import", "cleanup refused a context node",
                            node=target.path())
                return
            target.destroy()
        except hou.Error as exc:
            debug.event("import", "cleanup could not remove a node",
                        node=str(target), error=str(exc))

    def update_context(self, mat: material.Material, target: str = "auto"):
        """Resolve where a material should import to and set self._import_path.

        target:
          "auto" - derive the destination from the active network editor
                   (double-click "let MatLib decide" behaviour);
          "mat"  - force /mat;
          "lop"  - force a LOP materiallibrary.

        Returns (ok, reason). If the resolved context is LOP and the material
        cannot live there (classic redshift_vopnet / octane_vopnet /
        Mantra), ok is False and nothing is created; otherwise ok is True and
        self._import_path is set. /mat and SOP contexts accept every material
        MatLib handles, so only the LOP case can fail."""
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
                + "context. Use Import to MAT.",
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
        """Classify the active network editor's context as 'lop', 'sop', or
        'mat' (the default for anything that holds VOP-style materials)."""
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
        """Point the import path at a LOP materiallibrary: reuse the one the
        editor is inside, else create one under the current stage/lopnet, else
        create one under /stage (forced LOP from a non-LOP context)."""
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
        # Drop policy: ADD to the network's first existing material
        # library instead of scattering a fresh one per import; a
        # network-created library stays UNWIRED (placement law - only
        # viewport drops wire theirs into the display chain).
        existing = dragengine.first_materiallibrary(network)
        if existing is not None:
            self._import_path = existing
            self._use_existing_node = True
            return
        self._import_path = network.createNode("materiallibrary")

    def _set_sop_import_path(self) -> None:
        """Create a matnet inside the current geo/SOP network for the import."""
        curr = self.get_current_network_node()
        if curr is not None:
            # REUSE an existing matnet, the way _set_lop_import_path
            # reuses a materiallibrary (the drop-placement law). Without
            # this, three imports into the same geo produced matnet1,
            # matnet2 and matnet3 with one material each - the exact
            # clutter the LOP side's container policy exists to prevent.
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
        """This material's builder sidecar path, or "" if it escapes.

        Containment is re-checked here even though import_asset_to_scene
        already refused an unsafe id: this is the only other place the
        id becomes a path, and a helper that quietly returns "" is
        safer than one that composes something outside the library.
        """
        try:
            return builder_sidecar_path(self._preferences, mat.mat_id)
        except (hostos.PathEscape, TypeError) as exc:
            debug.event("import", "builder sidecar path refused",
                        material=mat.name, error=str(exc))
            return ""

    def load_interface_mtlx(self, parms_file_name, mat: material.Material) -> None:
        """
        Loads the Interface File from disk

        :param self: Description
        :param parms_file_name: Description
        :param mat: Description
        """
        # NO exec. Measured on the real 548-asset library: a Karma
        # builder made by make_karma_builder is IDENTICAL to one the
        # executed file produced - same dialog script, same values - so
        # the file contributed nothing here beyond the risk of running
        # it. research.md, "What `.interface` actually carries".
        #
        # The old `else: return` is gone with it. This was the only one
        # of the four renderer paths with no fallback: a missing
        # .interface left _builder_node at its /stage sentinel and the
        # caller then loaded items into /stage.
        if True:
            # Same MaterialX Material Builder every other path uses -
            # matches the KARMA_REF reference (mtlx render context,
            # subnetconnector outputs). Was an inline duplicate of
            # make_karma_builder's setup, drifting from it; now shared,
            # so the flavour can't diverge between build and load. The
            # starter shader/displacement are removed inside it; the
            # subnetconnector outputs are kept and load_items_file_mtlx()
            # wires the loaded shader into them via wire_builder_output.
            # Built in the /obj STAGING matnet and moved into the
            # destination in ONE step afterwards (the classic renderers
            # always worked this way via move_builder=True). Building
            # directly inside a materiallibrary made every createNode
            # re-run Houdini's preview-shader translation for EVERY
            # material already in the library - O(N) per import, O(N^2)
            # per session; profiled at 76ms->515ms over nine drops.
            self._builder_node = make_karma_builder(
                self._hou_parent, mat.name
            )
            apply_builder(
                self._builder_node,
                read_builder_sidecar(self._builder_sidecar(mat)),
            )

    def load_interface_mantra(self, parms_file_name, mat: material.Material) -> None:
        """
        Loads the Interface File from disk

        :param self: Description
        :param parms_file_name: Description
        :param mat: Description
        """
        builder = None
        if os.path.exists(parms_file_name):
            # Only load parms if MatBuilder
            if mat.builder:
                # NO exec. The container is made by the same call the
                # non-builder branch below already uses, then its own
                # parameter interface is restored from the sidecar -
                # read as data, never run.
                builder = self._hou_parent.createNode("materialbuilder")
                for child in builder.children():
                    child.destroy()
                apply_builder(
                    builder, read_builder_sidecar(self._builder_sidecar(mat)))
            # Selection will be empty if not a MaterialBuilder
            else:
                builder = self._import_path.createNode("materialbuilder")
        else:
            # _import_path is already a hou.Node here (same as the branch
            # above) - wrapping it in hou.node() raised TypeError.
            builder = self._import_path.createNode("materialbuilder")

        builder.setName(mat.name, unique_name=True)
        builder.setGenericFlag(hou.nodeFlag.Material, True)
        # Delete Default children in MaterialBuilder
        for node in builder.children():
            node.destroy()

        self._builder_node = builder

    def load_interface_other(
        self, parms_file_name: str, mat: material.Material, builder_name: str
    ) -> None:
        """
        Loads the Interface File Configuration from Disk

        :param self: Description
        :param parms_file_name: Description
        :type parms_file_name: str
        :param mat: Description
        :type mat: material.Material
        :param builder_name: Description
        :type builder_name: str
        """
        # NO exec. The saved container TYPE is recovered by reading -
        # get_saved_node_type regexes the createNode call out of the
        # .interface without running a line of it - and the container is
        # then made the ordinary way. Its own parameter interface (for
        # rs_usd_material_builder, the OpenGL viewport-preview block
        # that is the one thing .interface uniquely carried) comes back
        # from the sidecar.
        saved_type = self.get_saved_node_type(mat) or builder_name
        if node_type_available(saved_type):
            builder = self._hou_parent.createNode(saved_type)
            # Delete auto-created default children (newer Redshift builds
            # create an OpenPBR material + output in a fresh vopnet) so the
            # saved items don't collide or duplicate on load.
            for node in builder.children():
                node.destroy()
            apply_builder(
                builder, read_builder_sidecar(self._builder_sidecar(mat)))
        else:
            # _import_path is already a hou.Node (every assignment sets it
            # to one), so hou.node() - which wants a STRING path - raised
            # "argument 1 of type char const *" and crashed the Redshift
            # converter whenever this fallback was reached.
            builder = self._import_path.createNode(builder_name)

        builder.setName(mat.name, unique_name=True)
        builder.setGenericFlag(hou.nodeFlag.Material, True)
        # Delete Default children in RS-VopNet
        # for node in builder.children():
        #     node.destroy()

        self._builder_node = builder

    def load_items_file(self, mat: material.Material, move_builder: bool = False) -> None:
        """
        Loads the actual Node Configuration from Disk.
        move_builder=True moves the rebuilt builder node itself to the import
        context (Redshift/Octane, whose .mat files store the builder's
        children); False moves the loaded children (MaterialX/Mantra, whose
        .mat files store the material node itself).

        :param self: Description
        :param mat: Description
        """
        file_name = material.payload_path(
            self._preferences, mat.mat_id, self._preferences.ext
        )

        try:
            problem = load_items_strict(self._builder_node, file_name)
        except OSError:
            hou.ui.displayMessage("Failure on Import. Please Check Files.")  # type: ignore
            return None
        if problem:
            raise hou.OperationFailed(problem)

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
        """MaterialX/Karma equivalent of load_items_file(move_builder=False),
        but keeps the loaded shader+texture network wrapped in the subnet
        load_interface_mtlx() already created there, instead of flattening
        it out to the destination and discarding the subnet.

        Keeping the wrap gives every library material ONE uniform
        container (builder subnet with the full SideFX contract) - the
        structure the save/color/stamp flows and users rely on. (A
        loose material-flagged shader IS technically a complete
        material to the library - wiki, materials research - so the
        wrap is a structure/UX choice, not a translation requirement.)
        Left load_items_file() and its move_builder parameter
        completely untouched, since Mantra shares that code path and
        this behavior is only verified for MaterialX/Karma."""
        file_name = material.payload_path(
            self._preferences, mat.mat_id, self._preferences.ext
        )
        pre_existing = set(self._builder_node.children())
        try:
            problem = load_items_strict(self._builder_node, file_name)
            if problem:
                raise hou.OperationFailed(problem)
        except OSError:
            hou.ui.displayMessage("Failure on Import. Please Check Files.")  # type: ignore
            return None
        loaded = [
            c for c in self._builder_node.children() if c not in pre_existing
        ]
        if not loaded:
            # NOTHING was loaded, and this used to return (True, "") with
            # a material containing only a subinput and one
            # subnetconnector - no shader, no wired terminal, no warning.
            # Reached by a truncated .mat (interrupted save, partial
            # cloud sync) and by a zero-byte one, both of which
            # loadItemsFromFile accepts without complaint.
            raise hou.OperationFailed(
                'nothing could be loaded for "%s" - its .mat file looks '
                "corrupt or empty (%s)" % (mat.name, file_name)
            )

        # Two different .mat layouts exist in one library, saved by two
        # different paths, indistinguishable from the .interface alone:
        # - save_node_collect (bare mtlxstandard_surface + connected
        #   nodes, e.g. converter output): loose shader/texture items.
        # - save_node_mtlx (a whole builder-subnet material, e.g. every
        #   hand-built Karma Material Builder): ONE subnet item carrying
        #   its own complete internal network, output connectors, and
        #   builder spare-parm config (item files preserve full node
        #   state).
        # The single-subnet case must NOT be wrapped again - that would
        # nest a complete builder inside our scaffolding builder. Unwrap
        # it instead: it already IS the material.
        if len(loaded) == 1 and loaded[0].type().name() == "subnet":
            inner = hou.moveNodesTo((loaded[0],), self._import_path)[0]  # type: ignore
            outer = self._builder_node
            self._builder_node = inner
            outer.destroy()
            inner.setName(helpers.sanitize_usd_path(mat.name), unique_name=True)
            inner.setGenericFlag(hou.nodeFlag.Material, True)
            helpers.auto_place(inner)
            # The invariant check below is guarded by `shader_node is
            # not None` and this branch returns before reaching it - so
            # an unwrapped subnet with nothing wired to its surface
            # terminal imported "successfully" and rendered black.
            if not surface_terminal_wired(inner):
                debug.note('Amaze: "%s" imported, but nothing is wired to its '
                    "surface output - it will render black."
                    % mat.name)
                debug.event("import", "surface terminal not wired",
                            material=mat.name, node=inner.path())
            return

        # Loose-items case: self._builder_node is the Karma Material
        # Builder scaffolding created in load_interface_mtlx(), sitting at
        # the real destination - find the actual shader among the loaded
        # children and wire it into the builder's own output connector
        # (kept around instead of destroyed, specifically for this) -
        # without that the material would be correctly *shaped* like a
        # Karma Material Builder but not connected to anything usable
        # from outside the subnet.
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
                # Belt and braces for libraries saved BEFORE the save
                # side stopped archiving these: a connector reports a
                # "surface" output data type, so the rule below would
                # pick it as the shader and wire it into itself.
                continue
            elif shader_node is None and (
                "surface" in child.outputDataTypes()
                or tname == "subnet"
            ):
                # The translator itself identifies terminals by OUTPUT
                # DATA TYPE (isShaderVopTypeName), never node-type name
                # - matching that rule catches every surface-typed
                # shader (mtlxsurface, kma_fur, usdpreviewsurface...)
                # the old name whitelist reloaded unwired. Scanning
                # ONLY the loaded items matters just as much: the
                # builder's own subnetconnectors report output type
                # "surface" too, and picking one wired the connector
                # into itself.
                shader_node = child
                child.setGenericFlag(hou.nodeFlag.Material, True)
        wire_builder_output(self._builder_node, shader_node, displacement_node)
        # The load path is two-phase (build the builder, load items, wire)
        # so it can't go through build_karma_material's single funnel - but
        # it holds the SAME invariant, checked the same way.
        if shader_node is not None and not surface_terminal_wired(
            self._builder_node
        ):
            debug.event(
                "karma", "loaded material has no wired surface terminal",
                material=mat.name, builder=self._builder_node.path(),
            )
            debug.note("WARNING - loaded '%s' has no wired surface "
                "terminal and will render black" % mat.name)
        # A loaded collect node is the flat save format's stand-in for
        # "surface + displacement belong together" (see the converter) -
        # inside a real builder the suboutput just wired above carries
        # that role, so the collect is redundant clutter here. Destroyed
        # after the wiring so the builder's contents match a hand-built
        # Karma Material Builder exactly.
        for collect in collect_nodes:
            collect.destroy()
        # Auto-arrange the loaded nodes - loadItemsFromFile() restores
        # each node's originally-saved position, which were relative to
        # wherever they lived at save time and can land overlapping here.
        # Same as pressing "L" in the network editor.
        self._builder_node.layoutChildren()
        helpers.auto_place(self._builder_node)

    #: Was "/obj/MatLib" until 2026-07-27. Renaming was safe because
    #: zero library materials carried a cop_net at the time (verified),
    #: and an old hip that still has /obj/MatLib is self-contained -
    #: its companion network is saved inside the hip itself.
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
        """Scan the given nodes (and their descendants) for op: string
        parms referencing COP nodes. Returns (parm, cop_node, container)."""
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
        """If the material node(s) reference COP networks via op: paths,
        save those networks as a companion file next to the material and
        return an {old op: path -> new op: path} rewrite map. Also sets
        self._cop_info for the library database. Returns {} if the
        material has no COP references."""
        self._cop_info = {}
        # Any companion staged by an earlier save that never reached
        # save_asset_pair is this handler's to clean up - one pending
        # promote at a time, by construction (each of the five save
        # paths calls this once and then save_asset_pair once).
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

        # Off the undo stack at BOTH ends: a create/destroy pair on the
        # live stack resurrects the container with its children on one
        # Ctrl+Z (#278; the pair scan in test_prefs_and_sources holds
        # every staging site to this).
        with hou.undos.disabler():
            staging_parent = hou.node("/obj").createNode("subnet")
        rename_map = {}
        net_type = containers[0].type().name()
        try:
            try:
                staging = staging_parent.createNode(net_type)
            except hou.OperationFailed:
                # The recorded type could not be created here (a
                # context-specific container in the wrong parent).
                # Fall back to a container that CAN hold these nodes,
                # chosen from their own context rather than assuming
                # Copernicus as this path did when the section was
                # COP-only.
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
                # Copy ITEMS, not just child nodes - network dots are
                # not children, and copying without them drops every
                # wire routed through one (same bug class as the
                # standalone COP save, caught live in Houdini). Falls
                # back to the old node-only copy if copyItems is
                # unavailable in this Houdini build.
                items = container.allItems()
                try:
                    copies = staging.copyItems(items)
                except (AttributeError, hou.OperationFailed):
                    items = container.children()
                    copies = hou.copyNodesTo(items, staging)
                for orig, copy in zip(items, copies):
                    # Dots/boxes/notes carry no rename-relevant name -
                    # the op: path rewrite map only ever needs real nodes.
                    if isinstance(orig, hou.Node):
                        rename_map[orig.path()] = copy.name()
            # SCRATCH, then swap. This was the one content writer in
            # the package still writing straight onto its destination -
            # every other one goes through a unique scratch, and this
            # file is asset CONTENT, which has no .bak tier to restore
            # from. A save that died partway (disk full, a sync hiccup,
            # a container type that half-copied) truncated the companion
            # network of a material that was working a second earlier,
            # with nothing to put back.
            #
            # The 0-byte check is the same one save_asset_pair makes:
            # unique_scratch has already created the file, so existence
            # can no longer tell "written" from "not written", and an
            # empty .mat is exactly what a failed saveItemsToFile leaves.
            # WRITTEN NOW, PROMOTED WITH THE PAIR. The companion is a
            # FOURTH file of the same asset, and it used to be promoted
            # here - before save_asset_pair had even been called. So a
            # .mat write that then failed left the NEW companion beside
            # the OLD material, whose op: paths were rewritten against
            # the old node names: on import those references resolve to
            # nodes that no longer exist and the textures break. For a
            # new asset the same failure left an orphan <id>_cop.mat in
            # mat/ with no library row.
            #
            # The content has to be produced here, because the rewrite
            # map below is derived from it and the .mat is written
            # against that map. Only the PROMOTE moves, which is the
            # part that has to be all-or-nothing.
            scratch = hostos.unique_scratch(file_name)
            self._pending_cop_promote = (scratch, file_name)
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
        """Rewrite op: references in all string parms of the given nodes.
        Only ever called on temporary save copies, never on scene nodes."""
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
        """Remove a COP companion network THIS import created. One it
        merely reused is left alone - it belongs to another material."""
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
        """Take the COP root back out when this import made it and
        nothing is left in it.

        The companion rollback removed the network and left the root
        standing, so a refused import told the user nothing could be
        rebuilt and still put an empty container in their scene - the
        same complaint the network rollback was written for, one level
        up. Only a root THIS call created, and only while childless: a
        network another material restored keeps it, and so does one the
        user put there.

        NOT under `hou.undos.disabler()`, deliberately. This runs on a
        failure branch, which makes it a rollback rather than staging,
        and a rollback's create stays live so the user can undo the
        result (practice.md > STAGING DESTROYS IN A FINALLY).
        """
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
        """Recreate the material's saved COP network under /obj/MatLib on
        import. An existing network with the same name is reused.

        Returns the network THIS call created, or None when it created
        nothing (nothing to restore, reused an existing one, or failed)
        - so a failed import can roll it back."""
        info = getattr(mat, "cop_net", {}) or {}
        if not info or not info.get("name"):
            return
        file_name = (
            self._preferences.dir
            + self._preferences.asset_dir
            + mat.mat_id
            + "_cop"
            + self._preferences.ext
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
            # Remembered so a refusal below, or a failed import later,
            # can take it back out when it ends up holding nothing.
            self._created_cop_root = root
        if root.node(info["name"]) is not None:
            debug.event("import", "cop restored",
                        name=info["name"], reused=True)
            return
        try:
            copnet = root.createNode(info.get("type", "copnet"))
        except hou.OperationFailed:
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
            # This arm returns None, so the caller's rollback never
            # runs and never sees the root - the one exit that has to
            # take it back out itself.
            self._drop_created_cop_root()
            return
        helpers.auto_place(copnet)
        debug.event("import", "cop restored",
                    name=info["name"], reused=False)
        # Returned so a failed import can take it back out. Every early
        # return above means "created nothing" - including the reuse
        # case, where the network belongs to another material.
        return copnet

    def save_node_cop(
        self,
        node: hou.Node,
        asset_id: str,
        update: bool = False,
        items: list | None = None,
    ) -> bool:
        """Save a COP network as a standalone library asset (the v2 Cop
        section). Two modes:
        - node is a copnet CONTAINER (items None): the whole network -
          allItems() -> <id>.mat, the container's own asCode ->
          <id>.interface (the first createNode(...) call records the
          real network type for import, same contract as materials).
        - items given: a SELECTION of nodes/dots inside a Copernicus
          network (node = the clicked child, its parent is the net) -
          only those items are saved; the interface records the PARENT
          network's type so a container can still be reconstructed
          when importing outside any COP network.
        The scene is never modified - saveItemsToFile reads in place."""
        if items is not None:
            net = node.parent()
            selection_nodes = [i for i in items if isinstance(i, hou.Node)]
            if not selection_nodes:
                hou.ui.displayMessage(  # type: ignore
                    "No nodes selected - nothing to save."
                )
                return False
        else:
            net = node
            selection_nodes = None
            if not node.children():
                hou.ui.displayMessage(  # type: ignore
                    "The network is empty - nothing to save."
                )
                return False
        file_name = material.payload_path(
            self._preferences, str(asset_id), self._preferences.ext
        )
        parms_file_name = material.payload_path(
            self._preferences, str(asset_id), ".interface"
        )
        # allItems(), NOT children(): network DOTS route one output into
        # several inputs, and children() excludes them - saving without
        # the dots silently drops every wire that runs through one
        # (caught live in Houdini: re-imported networks came back with
        # missing inputs, and thumbnails failed on those broken copies).
        # allItems() carries children + dots + network boxes + notes.
        # A selection save stores exactly the user's items instead.
        saved_items = items if items is not None else net.allItems()
        # ONE unit - see save_asset_pair.
        self.save_asset_pair(
            parms_file_name, file_name, net.asCode(),
            lambda path: net.saveItemsToFile(
                saved_items, path,
                save_hda_fallbacks=hda_fallbacks_needed(saved_items),
            ),
            builder_node=net, asset_id=str(asset_id),
        )

        # Record which child IS the picture while the LIVE network is
        # in front of us: the display flag doesn't reliably survive the
        # items-file round-trip, which is why heuristics run on the
        # loaded temp copy kept picking wrong nodes (two live misses in
        # opposite directions). Node NAMES do survive, so the name is
        # what gets persisted (via the asset's cop_net field) and looked
        # up again at render time - including rerenders long after this
        # scene is gone.
        self._cop_info = {}
        source = helpers.pick_cop_display_child(net, children=selection_nodes)
        if source is not None:
            self._cop_info = {"thumb_node": source.name()}
            debug.event("save", "cop thumb source", source=source.name())
        else:
            debug.event("save", "cop thumb source", source=None)

        if not update and not self._preferences.render_on_import:
            return True
        # Thumbnail failure never blocks registration (same rule as
        # materials). WHICH thumbnail depends on the context - decided
        # in render_network_thumbnail, the one home for the Cop-or-Sop
        # choice shared with Update Preview. A context with no picture
        # (None) is fine here: the tile falls back to the node icon,
        # which is what the grid draws when no image exists.
        context = ""
        try:
            context = net.childTypeCategory().name()
        except (AttributeError, hou.OperationFailed):
            pass
        thumber = thumbs.ThumbNailRenderer(self._preferences)
        try:
            thumber.render_network_thumbnail(
                context, asset_id, self._cop_info.get("thumb_node", ""))
        except Exception as exc:
            debug.note("thumbnail failed for "
                + node.name()
                + " (asset saved anyway): "
                + str(exc))
        return True

    def import_cop_asset(
        self,
        mat: material.Material,
        context_node: hou.Node | None = None,
    ):
        """The import seam, COP flavour: (ok, reason, created) - the
        directly-loaded nodes, or the one container built for them.
        Empty on refusal."""
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
        """Recreate a saved COP asset (Cop section import). Context-
        aware, like materials: if the destination network
        already holds Copernicus nodes - the user is inside a COP
        network, or the drag released on/into a container - the saved
        nodes load DIRECTLY into it, no new container. Anywhere else a
        container of the saved network type is created (in the
        destination if possible, else /obj) and loaded into.
        context_node overrides the active-editor lookup (drag release
        point). Returns (ok, reason) - same contract as
        import_asset_to_scene."""
        # THE SAME DOOR THE MATERIAL IMPORT USES. This composed the path
        # directly, so a row whose id cannot be a filename raised
        # PathEscape straight out of a double-click instead of saying
        # what was wrong.
        file_name, refusal = self._payload_or_refusal(mat)
        if refusal:
            return (False, refusal)
        if not os.path.exists(file_name):
            return (False, '"%s": asset file is missing on disk.' % mat.name)
        from amaze.core import cop_library
        # The asset knows which context it came from (its renderer
        # field: "SOP", "COP", "LOP"...). Everything below asks THAT
        # rather than assuming Copernicus, which is what this path did
        # when the section held nothing else.
        # "" is a pre-context asset: this section held nothing but
        # Copernicus then, so that is what it is.
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
                        '"%s": failed to load into %s (%s).'
                        % (mat.name, dest.path(), exc),
                    )
                # Saved positions came from a different network and can
                # land on top of existing nodes - lay out just the new
                # arrivals (best-effort; the L key fixes any residue).
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

        # Not the destination's own context, so the nodes need a
        # container built for them. A geo full of SOPs dropped at
        # object level is the everyday case - that is what /obj is FOR.
        # Only when the destination could hold no such container at all
        # (SOPs into a Copernicus network) is there nothing to do but
        # say so, since half-creating one is worse than refusing.
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
                # hou.Error, not OperationFailed: a locked HDA raises
                # PermissionError, which is NOT a subclass of it, and
                # went out of the drop handler as a bare traceback.
                container = None
        if container is None:
            # Vet the fallback the same way: the SAVED type need not
            # exist at object level (a sopnet does not), while the
            # generic container for that context does.
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
            # Not always the container itself: a SOP Create keeps its
            # SOPs in an inner sopnet.
            # Not always the container itself: a SOP Create keeps its
            # SOPs in the editable subnet its HDA declares.
            #
            # No display-flag handling here on purpose. A fallback that
            # flagged the terminal was written for the empty-stage
            # symptom and proved DEAD: Houdini flags the last node
            # loaded into a SOP network itself, and sabotaging the
            # fallback changed nothing. The empty stage had ONE cause -
            # loading a level too high, beside the subnet OUT reads.
            cop_library.CopLibrary.load_target_in(
                container, context).loadItemsFromFile(file_name)
        except (OSError, hou.Error) as exc:
            container.destroy()
            return (
                False,
                '"%s": failed to load the saved network (%s).' % (mat.name, exc),
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
        if hou.getenv("OCIO") is None:
            hou.ui.displayMessage("Please set $OCIO first")  # type: ignore
            return False
        val = False

        if "Redshift" in self._renderer:
            with hou.InterruptableOperation(
                "Rendering", "Performing Tasks", open_interrupt_dialog=True
            ):
                val = self.save_node_redshift(node, asset_id, update)
        elif "Mantra" in self._renderer:
            with hou.InterruptableOperation(
                "Rendering", "Performing Tasks", open_interrupt_dialog=True
            ):
                val = self.save_node_mantra(node, asset_id, update)
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
        else:
            hou.ui.displayMessage("Selected Node is not a Material Builder")  # type: ignore
        return val

    def save_node_collect(self, node: hou.Node, asset_id: str, update: bool) -> bool:
        """Saves the attached network from a collect node to disk - does not add to library"""
        # Filepath where to save stuff
        file_name = material.payload_path(
            self._preferences, str(asset_id), self._preferences.ext
        )
        parms_file_name = material.payload_path(
            self._preferences, str(asset_id), ".interface"
        )

        # get_connected_nodes walks OUTPUTS as well as inputs, so from a
        # bare shader inside a Karma builder it also collects the
        # builder's own subnetconnector - measured:
        # ['mtlxstandard_surface', 'mtlximage', 'subnetconnector'].
        # Archiving that connector meant the import found TWO nodes
        # answering "surface" and wired the loaded connector into
        # itself, leaving the real one unwired: the material rendered
        # pitch black while the import reported success.
        #
        # A connector belongs to the container, never to the material.
        nodetree = [
            n for n in helpers.get_connected_nodes(node)
            if n.type().name() not in ("subnetconnector", "suboutput")
        ]

        # Staging OUTSIDE the source network: creating the temp subnet
        # inside a LOP materiallibrary fires an eager full-library
        # retranslation per created node (wiki: amaze retranslation
        # model) - /obj staging is free, exactly like save_node_mtlx.
        # Off the stack at BOTH ends, like staged_asset above (#278).
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


            # ONE unit - see save_asset_pair.
            self.save_asset_pair(
                parms_file_name, file_name, sub_tmp.asCode(),
                lambda path: sub_tmp.saveItemsToFile(
                    children, path,
                    save_hda_fallbacks=hda_fallbacks_needed(children),
                ),
                builder_node=sub_tmp, asset_id=str(asset_id),
            )
        finally:
            # Runs even on failure so the temporary save copy never
            # lingers in the scene.
            with hou.undos.disabler():
                staging_parent.destroy()

        # If this is not a manual update and render_on_import is off, finish here
        if not update:
            if not self._preferences.render_on_import:
                return True

        try:
            thumber = thumbs.ThumbNailRenderer(self._preferences)
            ok = thumber.create_thumb_mtlx(nodetree, asset_id)
        except Exception as exc:
            debug.exception("Karma thumbnail", exc, asset_id=asset_id,
                            node=node.path())
            debug.note("Karma thumbnail failed ("
                + str(exc)
                + ") - material saved and registered without thumbnail.")
            return True
        if not ok:
            # A thumbnail that merely RETURNS False must not lose the
            # material either: save_node()'s result is what add_asset()
            # gates registration on, so returning it directly meant a
            # failed render silently discarded the whole asset.
            debug.event("save", "Karma thumbnail returned False",
                        asset_id=asset_id, node=node.path())
            debug.note("Karma thumbnail did not render - material "
                "saved and registered without one.")
        return True

    def save_node_mtlx(self, node: hou.Node, asset_id: str, update: bool) -> bool:
        """Saves the MtlX node to disk - does not add to library"""
        # Filepath where to save stuff
        file_name = material.payload_path(
            self._preferences, asset_id, self._preferences.ext
        )

        parms_file_name = material.payload_path(
            self._preferences, asset_id, ".interface"
        )

        # Off the stack at BOTH ends, like staged_asset above (#278).
        with hou.undos.disabler():
            builder = hou.node("/obj").createNode("matnet")
        try:
            copied = hou.copyNodesTo((node,), builder)  # type: ignore

            path_map = self.prepare_cop_companion((node,), str(asset_id), node.name())
            if path_map:
                self.rewrite_cop_refs((copied[0],), path_map)


            # ONE unit - see save_asset_pair - and EVERY part of it from
            # the staging copy, like the three sibling save paths.
            #
            # The interface and the builder sidecar used to come from
            # the LIVE node while the items came from the copy, so the
            # `op:` references on the CONTAINER's own promoted
            # parameters were archived pointing at the save-time scene:
            # `rewrite_cop_refs` fixes the copy, and the live node is
            # deliberately never touched. A texture promoted to the
            # builder's interface therefore came back on import
            # pointing at a copnet that does not exist there, while the
            # child-level ones resolved.
            self.save_asset_pair(
                parms_file_name, file_name, copied[0].asCode(),
                lambda path: builder.saveItemsToFile(
                    copied, path,
                    save_hda_fallbacks=hda_fallbacks_needed(copied),
                ),
                builder_node=copied[0], asset_id=str(asset_id),
            )
        finally:
            # Runs even on failure so the temporary save copy never
            # lingers in the scene.
            with hou.undos.disabler():
                builder.destroy()

        # If this is not a manual update and render_on_import is off, finish here
        if not update:
            if not self._preferences.render_on_import:
                return True

        try:
            thumber = thumbs.ThumbNailRenderer(self._preferences)
            ok = thumber.create_thumb_mtlx(node, asset_id)
        except Exception as exc:
            debug.exception("Karma thumbnail", exc, asset_id=asset_id,
                            node=node.path())
            debug.note("Karma thumbnail failed ("
                + str(exc)
                + ") - material saved and registered without thumbnail.")
            return True
        if not ok:
            # A thumbnail that merely RETURNS False must not lose the
            # material either: save_node()'s result is what add_asset()
            # gates registration on, so returning it directly meant a
            # failed render silently discarded the whole asset.
            debug.event("save", "Karma thumbnail returned False",
                        asset_id=asset_id, node=node.path())
            debug.note("Karma thumbnail did not render - material "
                "saved and registered without one.")
        return True

    def save_node_mantra(self, node: hou.Node, asset_id: str, update: bool) -> bool:
        """Saves the Mantra node to disk - does not add to library"""
        # Filepath where to save stuff
        file_name = material.payload_path(
            self._preferences, str(asset_id), self._preferences.ext
        )

        # COP companion: same pattern as save_node_redshift - compute on
        # the real scene node before any copying, then rewrite the paths
        # only on a temporary copy (forcing one even if node is already
        # a materialbuilder) so the scene material is never touched.
        path_map = self.prepare_cop_companion((node,), str(asset_id), node.name())

        orig_node = node
        builder = None
        if node.type().name() != "materialbuilder" or path_map:
            # Off the stack at BOTH ends, like staged_asset (#278) -
            # /mat staging, same rule as /obj.
            with hou.undos.disabler():
                builder = hou.node("/mat").createNode("materialbuilder")
                for c in builder.children():
                    c.destroy()
            hou.copyNodesTo((node,), builder)  # type: ignore
            node = builder
            if path_map:
                self.rewrite_cop_refs((node,), path_map)

        try:
            # interface-stuff
            parms_file_name = material.payload_path(
            self._preferences, str(asset_id), ".interface"
        )
            children = node.children()

            # ONE unit - see save_asset_pair.
            self.save_asset_pair(
                parms_file_name, file_name, node.asCode(),
                lambda path: node.saveItemsToFile(
                    children, path,
                    save_hda_fallbacks=hda_fallbacks_needed(children),
                ),
                builder_node=node, asset_id=str(asset_id),
            )
        finally:
            # Runs even on failure so the temporary save copy never
            # lingers in the scene.
            node = orig_node
            if builder is not None:
                with hou.undos.disabler():
                    builder.destroy()

        # If this is not a manual update and render_on_import is off, finish here
        if not update:
            if not self._preferences.render_on_import:
                return True

        try:
            thumber = thumbs.ThumbNailRenderer(self._preferences)
            ok = thumber.create_thumb_mantra(node, asset_id)
        except Exception as exc:
            debug.exception("Mantra thumbnail", exc, asset_id=asset_id,
                            node=node.path())
            debug.note("Mantra thumbnail failed ("
                + str(exc)
                + ") - material saved and registered without thumbnail.")
            return True
        if not ok:
            # A thumbnail that merely RETURNS False must not lose the
            # material either: save_node()'s result is what add_asset()
            # gates registration on, so returning it directly meant a
            # failed render silently discarded the whole asset.
            debug.event("save", "Mantra thumbnail returned False",
                        asset_id=asset_id, node=node.path())
            debug.note("Mantra thumbnail did not render - material "
                "saved and registered without one.")
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
        """The Redshift and Octane save, which is ONE save.

        They were two functions of eighty lines that differed in two
        log strings and the name of the thumbnail call - the same two
        paths, the same COP companion, the same `/obj` staging, the
        same try/finally, the same early return. They had already
        drifted once and been re-synced by hand: both carried a comment
        explaining that this path used to log `str(e)` alone where
        Karma and Mantra logged the traceback.

        `renderer` is the word the log uses; `thumb_method` names the
        ThumbNailRenderer call, the way the menu tables name a Section
        method rather than holding a callable.
        """
        file_name = material.payload_path(
            self._preferences, str(asset_id), self._preferences.ext
        )
        parms_file_name = material.payload_path(
            self._preferences, str(asset_id), ".interface"
        )
        # COP companion: if the material references COP networks via op:
        # paths, save them alongside and rewrite the paths on a temporary
        # copy so the scene material is never touched.
        path_map = self.prepare_cop_companion((node,), str(asset_id), node.name())
        tmp_parent = None
        save_node = node
        if path_map:
            # Off the stack at BOTH ends, like staged_asset (#278).
            with hou.undos.disabler():
                tmp_parent = hou.node("/obj").createNode("matnet")
            save_node = hou.copyNodesTo((node,), tmp_parent)[0]
            self.rewrite_cop_refs((save_node,), path_map)

        try:
            children = save_node.children()

            # ONE unit - see save_asset_pair.
            self.save_asset_pair(
                parms_file_name, file_name, save_node.asCode(),
                lambda path: save_node.saveItemsToFile(
                    children, path,
                    save_hda_fallbacks=hda_fallbacks_needed(children),
                ),
                builder_node=save_node, asset_id=str(asset_id),
            )
        finally:
            # Runs even on failure so the temporary COP-rewrite copy never
            # lingers in the scene.
            if tmp_parent is not None:
                with hou.undos.disabler():
                    tmp_parent.destroy()

        # If this is not a manual update and render_on_import is off, finish here
        if not update:
            if not self._preferences.render_on_import:
                return True

        try:
            thumber = thumbs.ThumbNailRenderer(self._preferences)
            if not getattr(thumber, thumb_method)(node, asset_id):
                debug.note("%s thumbnail reported failure - "
                    "material saved and registered without thumbnail."
                    % renderer)
        except Exception as e:
            # The traceback and the structured fields, like the Karma
            # and Mantra paths - this one recorded only the exception's
            # str(), so the log the WORKFLOW says to read before
            # reasoning about a cause held one sentence and no asset
            # id, no node path and no traceback.
            debug.exception("%s thumbnail" % renderer, e, asset_id=asset_id,
                            node=node.path())
            debug.note("%s thumbnail failed (" % renderer
                + str(e)
                + ") - material saved and registered without thumbnail.")
        return True
