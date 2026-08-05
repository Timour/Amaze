"""LOP material assignment: the USD half of a viewport drop.

Dropping a material on a Solaris viewport is two jobs. The PANEL owns
the menu - which prim, swap or assign - because that is UI. Everything
after the click is USD work with no widget in it: find what is already
bound under a prim, rebind it, name the assign after the geometry it
drives, and remove a material nothing references any more.

That half lives here. It was 192 lines inside a 5,600-line panel
class, in the app's most-used workflow (the debug log counts drag as
its single busiest activity) and the hardest part to check by
clicking. As plain functions over hou/USD objects it can be tested
headlessly - which tests/test_lop_assign.py now does.

Nothing here imports Qt or touches the panel.
"""

import hou

from amaze.core import debug, dragengine
from amaze.helpers import helpers


def name_new_assign(lopnet, before, assign_path) -> None:
    """Name a freshly created assignmaterial after WHAT IT ASSIGNS -
    "box_object1" for an object prim, "sphere_object1_mesh_0" for a
    mesh inside one - so a stack of assigns reads as the geometry
    it drives instead of assignmaterial1/2/3. Only the node the
    stock helper just created is renamed; a reused assign keeps the
    name it already earned."""
    new = [
        n for n in lopnet.children()
        if n.type().name() == "assignmaterial" and n not in before
    ]
    if len(new) != 1:
        return
    parts = [p for p in str(assign_path).split("/") if p]
    if not parts:
        return
    # Object prim -> its own name; a mesh (or any child) -> parent
    # plus child, the "geometry_mesh" form.
    name = "_".join(parts[-2:]) if len(parts) > 1 else parts[0]
    try:
        new[0].setName(
            helpers.sanitize_usd_path(name), unique_name=True
        )
    except hou.OperationFailed:
        pass


def bound_materials_under(stage, primpath):
    """[(material_prim_path, [bound_prim_paths])] governing the
    picked prim: the nearest self-or-ancestor DIRECT binding (the
    one the prim inherits) plus every direct binding in the
    subtree below - the swap menu's source."""
    try:
        from pxr import Usd
    except Exception:
        return []
    root = stage.GetPrimAtPath(primpath) if stage else None
    if root is None or not root.IsValid():
        return []
    order, prims_of = [], {}

    def add(mat, path):
        if mat not in prims_of:
            prims_of[mat] = []
            order.append(mat)
        if path not in prims_of[mat]:
            prims_of[mat].append(path)

    def direct(prim):
        """Materials bound ON this prim, by EITHER binding style.

        Houdini's assignmaterial writes one of two things depending on
        its Bind Method: a plain `material:binding` relationship, or a
        collection binding - `material:binding:collection:<name>`,
        whose targets are [collection, material]. Reading only the
        first meant a material assigned the collection way offered no
        Swap entry at all: the drop menu simply had nothing to show,
        which reads as the feature being gone for that object while
        working for its neighbour.
        """
        found = []
        try:
            for rel in prim.GetRelationships():
                name = rel.GetName()
                if name != "material:binding" and \
                        not name.startswith("material:binding:collection:"):
                    continue
                targets = [str(t) for t in rel.GetTargets()]
                if not targets:
                    continue
                # Direct: [material]. Collection: [collection, material]
                # - the material is the last target either way.
                material = targets[-1]
                if material not in found:
                    found.append(material)
        except Exception as exc:                         # noqa: BLE001
            # SAY WHY, and keep what was already found. Returning []
            # here threw away every binding collected so far and made a
            # PARTIAL failure indistinguishable from "this prim has no
            # bound materials" - so the swap menu simply showed nothing,
            # with no way to tell that it had given up halfway.
            debug.event("lop", "binding scan stopped early",
                        error="%s: %s" % (type(exc).__name__, exc),
                        prim=str(getattr(prim, "GetPath", lambda: "?")()),
                        found=len(found))
        return found

    prim = root
    while prim and prim.IsValid() and prim != stage.GetPseudoRoot():
        mats = direct(prim)
        if mats:
            for m in mats:
                add(m, str(prim.GetPath()))
            break
        prim = prim.GetParent()
    for prim in Usd.PrimRange(root):
        if prim == root:
            continue
        for m in direct(prim):
            add(m, str(prim.GetPath()))
    return [(m, prims_of[m]) for m in order]


def swap_assignments(stock, lopnet, liblop, anchor, targets, vop):
    """Rebind every prim in targets ([(old_matpath, [primpaths])])
    to vop's material via the stock helper - later ops win over
    the old binding, and assignMat itself prunes the moved prims
    from other entries - then drop each old material from liblop
    if nothing references it anymore (the anti-dead-material
    cleanup the swap exists for).

    Returns None on success, or a reason string the caller can show."""
    try:
        matpath = str(stock.getMaterialPrimPathForNode(liblop, vop))
    except Exception as exc:
        # No dialogs in here: the panel owns the UI, this owns the USD.
        # A caller with a screen shows the returned reason; headless
        # callers (and the tests) just read it.
        debug.event("drag", "swap failed", error=str(exc))
        return "imported, but the swap failed: %s" % exc
    for old, prims in targets:
        for p in prims:
            try:
                stock.assignMat(p, matpath, anchor)
            except Exception as exc:
                debug.event("drag", "swap assign failed",
                            prim=p, error=str(exc))
                continue
            if anchor is None or \
                    anchor.type().name() != "assignmaterial":
                anchor = dragengine.find_assignmaterial(lopnet) \
                    or anchor
    removed = [old for old, _ in targets
               if remove_unreferenced_material(
                   lopnet, liblop, old)]
    debug.event("drag", "swap", new=matpath,
                old=[o for o, _ in targets], removed=removed)


def remove_unreferenced_material(lopnet, liblop,
                                  matprimpath) -> bool:
    """Delete matprimpath's definition from liblop IF no
    assignmaterial entry in the network still uses it - a swap
    must not leave dead materials behind, but must never take one
    that is still assigned elsewhere. Entries whose primpattern is
    empty do not count as uses (assignMat empties patterns when it
    moves prims away).

    A material can be defined two ways, and both are handled: by
    EXPLICIT entries (matpath equals the prim path - every one of
    them is removed, imports once double-entered) and by a PATTERN
    entry (the stock wildcard "*" that exposes every VOP; its
    matpath is empty and the prim path is containerpath + node
    name). Pattern entries are never touched - destroying the VOP
    alone takes the material out of their match set."""
    matsparm = liblop.parm("materials")
    if matsparm is None:
        return False
    container = liblop.parm("containerpath").eval().rstrip("/")
    name = matprimpath.rsplit("/", 1)[-1]
    vop = None
    explicit = []
    pattern_covered = False
    for i in range(1, matsparm.eval() + 1):
        mp = liblop.parm("matpath%d" % i)
        np = liblop.parm("matnode%d" % i)
        if mp is None or np is None:
            continue
        if mp.eval() == matprimpath:
            explicit.append(i)
            if vop is None and np.eval():
                vop = liblop.node(np.eval())
        elif not mp.eval() and container + "/" + name == matprimpath:
            cand = liblop.node(name)
            if cand is not None and np.eval() and \
                    helpers.node_pattern_match(
                        np.eval(), liblop.relativePathTo(cand)):
                pattern_covered = True
                if vop is None:
                    vop = cand
    if not explicit and not pattern_covered:
        return False
    for node in lopnet.children():
        if node.type().name() != "assignmaterial":
            continue
        num = node.parm("nummaterials")
        for j in range(1, (num.eval() if num else 0) + 1):
            spec = node.parm("matspecpath%d" % j)
            pat = node.parm("primpattern%d" % j)
            if spec is not None and spec.eval() == matprimpath \
                    and pat is not None and pat.eval().strip():
                return False
    # Exactness guards on the VOP itself: it dies only if it lives
    # INSIDE this library and no entry with a DIFFERENT explicit
    # matpath (any materiallibrary in the network) points at the
    # same node. Pattern entries do not hold it - once destroyed
    # it simply leaves their match set. (Resolving a pattern entry
    # with liblop.node("*") once returned a real child and made the
    # wildcard read as a sharer - the VOP survived every removal.)
    if vop is not None and not vop.path().startswith(
            liblop.path() + "/"):
        vop = None
    if vop is not None:
        for node in lopnet.children():
            if node.type().name() != "materiallibrary":
                continue
            num = node.parm("materials")
            for j in range(1, (num.eval() if num else 0) + 1):
                if node == liblop and j in explicit:
                    continue
                mp2 = node.parm("matpath%d" % j)
                rp = node.parm("matnode%d" % j)
                if mp2 is None or rp is None:
                    continue
                if mp2.eval() and mp2.eval() != matprimpath and \
                        rp.eval() and node.node(rp.eval()) == vop:
                    vop = None
                    break
            if vop is None:
                break
    # SAY WHY on both of these. They fail PART WAY THROUGH a scene edit
    # - some multiparm entries already removed, or the entries gone and
    # the VOP still there - and a bare False told the caller nothing
    # about a half-completed change it now has to reason about.
    for i in sorted(explicit, reverse=True):
        try:
            matsparm.removeMultiParmInstance(i - 1)
        except (hou.OperationFailed, TypeError) as exc:
            debug.event("lop", "could not remove a material entry",
                        error="%s: %s" % (type(exc).__name__, exc),
                        instance=i, node=matsparm.node().path(),
                        removed_so_far=sorted(explicit, reverse=True).index(i))
            return False
    if vop is not None:
        try:
            vop.destroy()
        except hou.OperationFailed as exc:
            debug.event("lop", "entries removed but the VOP survived",
                        error=str(exc), vop=vop.path())
            return False
    return True


def drop_choices(stage, primpath):
    """What a LOP viewport drop can offer, as data.

    Returns a list of (kind, label, payload):

      ("swap",   "Swap Bronze",             [(matpath, [prims]), ...])
      ("swap",   "Swap All Materials",      [...every bound material])
      ("assign", "Set as Material on mesh", "/path/to/prim")

    Deciding WHAT to offer is USD reasoning - which materials are bound
    under the picked prim, which ancestors can take an assignment - and
    it is the part worth testing. Building a QMenu out of the result is
    three lines in the panel, and needs a human to click it.

    Swap entries come first: rebinding what is already on the prim
    beats piling a new assignment on top and leaving dead materials
    behind. Assign entries walk self-then-ancestors, so a drop can
    target the mesh or the object that contains it.
    """
    choices = []
    if not primpath or stage is None:
        return choices

    bound = bound_materials_under(stage, primpath)
    for mpath, prims in bound:
        choices.append(
            ("swap", "Swap %s" % mpath.rsplit("/", 1)[-1], [(mpath, prims)])
        )
    if len(bound) > 1:
        choices.append(("swap", "Swap All Materials", list(bound)))

    prim = stage.GetPrimAtPath(primpath)
    first = True
    while prim is not None and prim.IsValid() \
            and prim != stage.GetPseudoRoot():
        label = "Set as Material on "
        if not first:
            label += "../"
        label += prim.GetName()
        kind = prim.GetMetadata("kind")
        if kind:
            label += " (%s)" % kind
        choices.append(("assign", label, str(prim.GetPath())))
        prim = prim.GetParent()
        first = False
    return choices
