"""The texture store: every file a saved material references is adopted into `<library>/matX/` and referenced as `$AMAZELIB/...`, so the library is self-contained; the panel publishes the variable, Copy To resolves it back to plain absolute paths for scenes. ▸r/texture-refs"""

import filecmp
import os
import shutil

from amaze.core import debug
from amaze.helpers import hostos

# `hou` is imported inside the node-walking functions only: the path half
# (tokenize/resolve/asset_folder) serves packages.py, which stays hou-free.

TOKEN_VAR = "AMAZELIB"
TOKEN_PREFIX = "$" + TOKEN_VAR + "/"
STORE_DIR_NAME = "matX"    # the same folder matx_import extracts online packages into - one store, however a texture arrived


def publish_env(prefs) -> None:
    """Set $AMAZELIB to the library directory, so Houdini itself resolves store references in thumbnails and previews."""
    import hou
    directory = str(getattr(prefs, "dir", "") or "")
    if directory:
        hou.putenv(TOKEN_VAR, os.path.normpath(directory))


def store_dir(prefs) -> str:
    return os.path.join(str(prefs.dir), STORE_DIR_NAME)


def asset_folder(name: str, asset_id: str) -> str:
    """The store folder a save adopts into - readable name first, identity after, the package_dirname convention."""
    return "%s__%s" % (hostos.safe_filename(str(name) or "asset"),
                       str(asset_id)[:12])


def tokenize(path: str, prefs) -> str:
    """The `$AMAZELIB/...` spelling of a path under the library - any other path comes back unchanged."""
    library = os.path.normpath(str(getattr(prefs, "dir", "") or ""))
    if not path or not library or path.startswith("$"):
        return path
    normal = os.path.normpath(path)
    if normal == library or not normal.startswith(library + os.sep):
        return path
    rest = os.path.relpath(normal, library).replace(os.sep, "/")
    return TOKEN_PREFIX + rest


def resolve(path: str, prefs) -> str:
    """The absolute spelling of a `$AMAZELIB/...` path in THIS library - any other path comes back unchanged."""
    if not str(path or "").startswith(TOKEN_PREFIX):
        return path
    return os.path.join(os.path.normpath(str(prefs.dir)),
                        *path[len(TOKEN_PREFIX):].split("/"))


def file_parms(node) -> list:
    """Every FileReference string parm on the node and everything under it - Redshift's tex0 and mtlximage's file both declare the type (▸r/texture-refs)."""
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
    """One file into `matX/<folder>/textures/` - already-inside paths respell without copying - answering the `$AMAZELIB/...` token, or "" for a file that does not exist."""
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
    """Copy every outside file the node references into `matX/<folder>/textures/` and rewrite the parms to `$AMAZELIB/...` - answering the token inventory; a reference to a file that does not exist is logged and left standing, so the breakage stays visible."""
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
        if _set(parm, token):    # a refused rewrite (locked parm) stays OUT of the inventory - the row must not promise a token the network does not carry
            _remember(inventory, token)
    return inventory


def resolve_parms(node, prefs) -> int:
    """Rewrite every `$AMAZELIB/...` reference under the node to this library's absolute path - the scene-side door, so scenes carry no Amaze dependency - answering how many changed."""
    changed = 0
    for parm, raw in references(node):
        if raw.startswith(TOKEN_PREFIX):
            _set(parm, resolve(raw, prefs))
            changed += 1
    return changed


def _landing(destination: str, source: str) -> str:
    """Where `source` lands in the store: its basename, bumped only when a DIFFERENT file already holds the name."""
    name = hostos.safe_filename(os.path.basename(source))
    target = os.path.join(destination, name)
    stem, ext = os.path.splitext(name)
    bump = 0
    while os.path.exists(target) and not filecmp.cmp(source, target,
                                                     shallow=False):
        bump += 1
        target = os.path.join(destination, "%s_%d%s" % (stem, bump, ext))
    return target


def _set(parm, value: str) -> bool:
    import hou
    try:
        parm.set(value)
        return True
    except (hou.OperationFailed, hou.PermissionError) as exc:    # locked or keyframed - the reference stands as it was; PermissionError is a SIBLING ▸r/hou-errors
        debug.event("texstore", "parm not rewritten", parm=parm.path(),
                    error=str(exc))
        return False


def _remember(inventory: list, token: str) -> None:
    if token not in inventory:
        inventory.append(token)
