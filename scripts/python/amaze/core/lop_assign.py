"""LOP material assignment - the USD half of a viewport drop: find what is bound under a prim, rebind it, name the assign after the geometry it drives, remove a material nothing references. NOTHING HERE IMPORTS Qt OR TOUCHES THE PANEL, which is what makes it testable headlessly. ▸archive/lop_assign.py
"""

import hou

from amaze.core import debug, dragengine
from amaze.helpers import helpers


def name_new_assign(lopnet, before, assign_path) -> None:
    """Names a freshly created assignmaterial after WHAT IT ASSIGNS, so a stack of them reads as the geometry rather than assignmaterial1/2/3. ONLY the node just created is renamed - a reused assign keeps the name it earned."""
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
            helpers.sanitize_usd_path(name), unique_name=True
        )
    except hou.OperationFailed:
        pass


def bound_materials_under(stage, primpath):
    """`[(material_prim_path, [bound_prim_paths])]` governing the picked prim - the nearest self-or-ancestor direct binding it inherits, plus every direct binding in the subtree below."""
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
        """Materials bound ON this prim by EITHER binding style - a plain `material:binding`, or a collection binding whose targets are `[collection, material]`. Reading only the first leaves a collection-bound material with no Swap entry. A partial failure KEEPS what it found, or it reads as a prim with nothing bound."""
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
    """Rebinds every prim in `targets` to `vop`'s material, then drops each old material that nothing references any more. Answers None on success, or a REASON STRING - no dialogs here, the panel owns the UI."""
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


def remove_unreferenced_material(lopnet, liblop,
                                  matprimpath) -> bool:
    """Deletes a material's definition IF no assignmaterial entry still uses it - never one still assigned elsewhere, and an empty primpattern is not a use. EXPLICIT entries are removed; PATTERN entries are never touched, and never RESOLVED to check, because a wildcard resolves to a real child and reads as a sharer. Failures here land part way through a scene edit, so they say why."""
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
    """What a viewport drop can offer, as `(kind, label, payload)` data for the panel to build a menu from. SWAP entries come first - rebinding what is already on the prim beats stacking a new assignment and leaving dead materials. Assign entries walk self-then-ancestors."""
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
