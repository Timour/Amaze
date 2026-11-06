"""LOP material assignment for a viewport drop: find, rebind and remove bindings; no Qt here."""

import hou

from amaze.core import debug, dragengine
from amaze.helpers import helpers, wording


def name_new_assign(lopnet, before, assign_path) -> None:
    """Name the one assignmaterial not in `before` after the path it assigns; others keep theirs."""
    new = [
        n for n in lopnet.children()
        if n.type().name() == "assignmaterial" and n not in before
    ]
    if len(new) != 1:
        return
    parts = [p for p in str(assign_path).split("/") if p]
    if not parts:
        return
    name = "_".join(parts[-2:]) if len(parts) > 1 else parts[0]
    try:
        new[0].setName(
            wording.sanitize_usd_path(name), unique_name=True
        )
    except hou.OperationFailed:
        pass


def bound_materials_under(stage, primpath):
    """`[(material, [prims])]`: the nearest inherited direct binding plus every one below."""
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
        """Materials bound on this prim, plain or collection binding; a failure keeps what it found."""
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
                material = targets[-1]   # last target under either style
                if material not in found:
                    found.append(material)
        except Exception as exc:                         # noqa: BLE001
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
    """Rebind `targets` to `vop`'s material, drop unreferenced old ones; None, or a reason string."""
    try:
        matpath = str(stock.getMaterialPrimPathForNode(liblop, vop))
    except Exception as exc:
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


def _assigns_geometry(liblop, index: int) -> bool:
    """Whether material entry `index` binds its material itself: Assign on, a geometry path set."""
    assign, geopath = liblop.parm("assign%d" % index), liblop.parm("geopath%d" % index)
    return bool(assign is not None and assign.eval()
                and geopath is not None and geopath.eval().strip())


def _bound_on_stage(node, matprimpath) -> bool:
    """Whether any prim on `node`'s cooked stage resolves to `matprimpath`; True when it cannot tell."""
    try:
        from pxr import UsdShade
        prims = list(node.stage().Traverse())
    except Exception as exc:                         # noqa: BLE001
        debug.event("lop", "stage unreadable - material kept",
                    error="%s: %s" % (type(exc).__name__, exc), material=matprimpath)
        return True
    api = UsdShade.MaterialBindingAPI
    for purpose in api.GetMaterialPurposes():
        _materials, rels = api.ComputeBoundMaterials(prims, purpose)
        if any(rel and str(api.GetResolvedTargetPathFromBindingRel(rel)) == matprimpath
               for rel in rels):
            return True
    return False


def remove_unreferenced_material(lopnet, liblop,
                                  matprimpath) -> bool:
    """Delete a material's explicit entries and VOP when nothing still uses it; whether it went."""
    matsparm = liblop.parm("materials")
    if matsparm is None:
        return False
    container = liblop.parm("containerpath").eval().rstrip("/")
    name = matprimpath.rsplit("/", 1)[-1]
    vop = None
    explicit = []
    covering = []
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
                covering.append(i)
                if vop is None:
                    vop = cand
    if not explicit and not covering:
        return False
    if any(_assigns_geometry(liblop, i) for i in explicit + covering):
        return False    # the entry's own Assign to Geometry still binds it
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
    if _bound_on_stage(lopnet.displayNode() or liblop, matprimpath):
        debug.event("lop", "material kept - the stage still binds it", material=matprimpath)
        return False    # a file the network loads binds it: no node shows that, the stage does
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
    """A drop's menu as `(kind, label, payload)`: swaps first, then assigns up the ancestors."""
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
