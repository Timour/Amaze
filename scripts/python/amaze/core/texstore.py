"""The texture store: referenced files adopted into `matX/` as `$AMAZELIB/...`. ▸r/texture-refs"""

import filecmp
import os
import shutil

from amaze.core import debug
from amaze.helpers import hostos


TOKEN_VAR = "AMAZELIB"
TOKEN_PREFIX = "$" + TOKEN_VAR + "/"
STORE_DIR_NAME = "matX"    # shared with matx_import's online packages


def publish_env(prefs) -> None:
    """Set $AMAZELIB to the library directory, so Houdini resolves store references."""
    import hou
    directory = str(getattr(prefs, "dir", "") or "")
    if directory:
        hou.putenv(TOKEN_VAR, os.path.normpath(directory))


def store_dir(prefs) -> str:
    return os.path.join(str(prefs.dir), STORE_DIR_NAME)


def asset_folder(name: str, asset_id: str) -> str:
    """The store folder a save adopts into: `<name>__<id prefix>`."""
    return "%s__%s" % (hostos.safe_filename(str(name) or "asset"),
                       str(asset_id)[:12])


def tokenize(path: str, prefs) -> str:
    """The `$AMAZELIB/...` spelling of a path under the library; any other comes back unchanged."""
    library = os.path.normpath(str(getattr(prefs, "dir", "") or ""))
    if not path or not library or path.startswith("$"):
        return path
    normal = os.path.normpath(path)
    if normal == library or not normal.startswith(library + os.sep):
        return path
    rest = os.path.relpath(normal, library).replace(os.sep, "/")
    return TOKEN_PREFIX + rest


def resolve(path: str, prefs) -> str:
    """The absolute spelling of a `$AMAZELIB/...` path in this library; any other is unchanged."""
    if not str(path or "").startswith(TOKEN_PREFIX):
        return path
    return os.path.join(os.path.normpath(str(prefs.dir)),
                        *path[len(TOKEN_PREFIX):].split("/"))


def file_parms(node) -> list:
    """Every FileReference string parm on the node and everything under it. ▸r/texture-refs"""
    import hou
    parms = []
    for owner in [node] + list(node.allSubChildren()):
        for parm in owner.parms():
            template = parm.parmTemplate()
            if (template.type() == hou.parmTemplateType.String
                    and template.stringType()
                    == hou.stringParmType.FileReference):
                parms.append(parm)
    return parms


def references(node) -> list:
    """(parm, raw unexpanded value) for every non-empty file reference under the node."""
    import hou
    refs = []
    for parm in file_parms(node):
        try:
            raw = parm.unexpandedString()
        except (hou.OperationFailed, hou.PermissionError):    # PermissionError is a SIBLING, not a subclass ▸r/hou-errors
            raw = parm.evalAsString()
        if raw:
            refs.append((parm, raw))
    return refs


def adopt_file(source: str, prefs, folder: str) -> str:
    """Copy one file into `matX/<folder>/textures/`; its token, or "" for a missing file."""
    token = tokenize(source, prefs)
    if token.startswith(TOKEN_PREFIX):
        return token
    if not os.path.isfile(source):
        return ""
    destination = os.path.join(store_dir(prefs), folder, "textures")
    target = _landing(destination, source)
    if not os.path.exists(target):
        hostos.check_sandbox(target)
        os.makedirs(destination, exist_ok=True)
        with hostos.scratch_beside(target) as scratch:
            shutil.copyfile(source, scratch)
    return tokenize(target, prefs)


def adopt(node, prefs, folder: str) -> list:
    """Adopt every outside file the node references, rewrite its parms; the token list."""
    import hou
    inventory = []
    for parm, raw in references(node):
        if raw.startswith(TOKEN_PREFIX):
            _remember(inventory, raw)
            continue
        token = adopt_file(hou.text.expandString(raw), prefs, folder)
        if not token:
            debug.event("texstore", "referenced file missing",
                        parm=parm.path(), raw=raw)
            continue
        if _set(parm, token, node):    # a refused rewrite stays out of the inventory
            _remember(inventory, token)
    return inventory


def resolve_parms(node, prefs, write_path=None) -> int:
    """Every `$AMAZELIB/...` reference under the node made a path `write_path` spells; the count."""
    style = getattr(prefs, "path_style", "home")    # Write Paths As, which needs Houdini to apply
    changed = 0
    for parm, raw in references(node):
        if raw.startswith(TOKEN_PREFIX):
            path = resolve(raw, prefs)
            _set(parm, write_path(path, style) if write_path is not None else path, node)
            changed += 1
    return changed


def _landing(destination: str, source: str) -> str:
    """Where `source` lands: its basename, bumped when a different file holds the name."""
    name = hostos.safe_filename(os.path.basename(source))
    target = os.path.join(destination, name)
    stem, ext = os.path.splitext(name)
    bump = 0
    while os.path.exists(target) and not filecmp.cmp(source, target,
                                                     shallow=False):
        bump += 1
        target = os.path.join(destination, "%s_%d%s" % (stem, bump, ext))
    return target


def _set(parm, value: str, root) -> bool:
    """Write `value`; follow a reference only to a parm under `root`. ▸r/texture-refs"""
    import hou
    try:
        parm.set(value, follow_parm_reference=_lands_under(parm, root))
        return True
    except (hou.OperationFailed, hou.PermissionError) as exc:    # locked or keyframed: the reference stands ▸r/hou-errors
        debug.event("texstore", "parm not rewritten", parm=parm.path(),
                    error=str(exc))
        return False


def _lands_under(parm, root) -> bool:
    """Does the end of `parm`'s reference chain sit on `root` or a node under it?"""
    seen = {parm.path()}
    target = parm.getReferencedParm()
    while target.path() not in seen:    # a chain, as `set()` follows it; a cycle ends it
        seen.add(target.path())
        target = target.getReferencedParm()
    owner = target.node().path()
    return owner == root.path() or owner.startswith(root.path().rstrip("/") + "/")


def _remember(inventory: list, token: str) -> None:
    if token not in inventory:
        inventory.append(token)
