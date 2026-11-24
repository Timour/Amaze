"""A material's textures: its own copies in its folder, saved as `$AMAZEASSET/...`. ▸r/texture-refs"""

import filecmp
import os
import shutil

from amaze.core import asset_record, debug, library_files
from amaze.helpers import hostos


TOKEN_VAR = "AMAZELIB"
TOKEN_PREFIX = "$" + TOKEN_VAR + "/"    # a path anywhere in the library
OWN_PREFIX = "$AMAZEASSET/"    # a path in the material's own folder, written out when it loads
OLD_STORE = "matX"    # the 2.0 texture store: a path into it is read in the material's own folder


def publish_env(prefs) -> None:
    """Set $AMAZELIB to the library directory, so Houdini resolves store references."""
    import hou
    directory = str(getattr(prefs, "dir", "") or "")
    if directory:
        hou.putenv(TOKEN_VAR, os.path.normpath(directory))


def _inside(path: str, folder: str) -> str:
    """`path` relative to `folder` with `/`, or "" when it is not inside it."""
    folder = os.path.normpath(str(folder or ""))
    normal = os.path.normpath(str(path or ""))
    if not folder or normal == folder or not normal.startswith(folder + os.sep):
        return ""
    return os.path.relpath(normal, folder).replace(os.sep, "/")


def tokenize(path: str, prefs, own_dir: str = "") -> str:
    """`$AMAZEASSET/...` in `own_dir`, `$AMAZELIB/...` elsewhere in the library, else unchanged."""
    if not path or path.startswith("$"):
        return path
    rest = _inside(path, own_dir)
    if rest:
        return OWN_PREFIX + rest
    rest = _inside(path, getattr(prefs, "dir", ""))
    return TOKEN_PREFIX + rest if rest else path


def resolve(path: str, prefs, own_dir: str = "") -> str:
    """The absolute path of an own, an old store or a library path; any other is unchanged."""
    path = str(path or "")
    if path.startswith(OWN_PREFIX) and own_dir:
        return os.path.join(own_dir, *path[len(OWN_PREFIX):].split("/"))
    if not path.startswith(TOKEN_PREFIX):
        return path
    old = old_store_parts(path)
    if own_dir and old:
        return old_store_place(own_dir, old[0], old[1:])
    return os.path.join(os.path.normpath(str(prefs.dir)), *path[len(TOKEN_PREFIX):].split("/"))


def old_store_target(own_dir: str, folder: str, rest: list, first: bool) -> str:
    """Where a file of the 2.0 store's `folder` goes in a material: in place for its first, else apart."""
    if first:
        return os.path.join(own_dir, *rest)
    return os.path.join(own_dir, library_files.TEXTURES, folder, *rest)    # two folders, one name


def old_store_place(own_dir: str, folder: str, rest: list) -> str:
    """Where a file of the old store's `folder` is in a converted material: apart, or in place."""
    apart = old_store_target(own_dir, folder, rest, False)
    return apart if os.path.exists(apart) else old_store_target(own_dir, folder, rest, True)


def old_store_parts(token: str) -> list:
    """[folder, *rest] of a `$AMAZELIB/matX/<folder>/<rest>` path; [] for any other."""
    parts = str(token)[len(TOKEN_PREFIX):].split("/") if str(token).startswith(TOKEN_PREFIX) else []
    return parts[1:] if len(parts) > 2 and parts[0] == OLD_STORE else []


def _read_in_own_folder(path: str, prefs, own_dir: str) -> str:
    """A full path into the 2.0 store, as a 2.0 load wrote it, read the way `resolve` reads one."""
    rest = _inside(path, getattr(prefs, "dir", "")).split("/")
    if own_dir and len(rest) > 2 and rest[0] == OLD_STORE and not os.path.exists(path):
        return old_store_place(own_dir, rest[1], rest[2:])
    return path


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


def raw_path(parm) -> str:
    """The parm's raw spelling, or its evaluated path where it has keyframes. ▸r/texture-refs"""
    import hou
    try:
        return parm.unexpandedString()
    except (hou.OperationFailed, hou.PermissionError):    # keyframes: a reference or an expression; PermissionError is a SIBLING ▸r/hou-errors
        return parm.evalAsString()


def references(node) -> list:
    """(parm, raw unexpanded value) for every non-empty file reference under the node."""
    refs = []
    for parm in file_parms(node):
        raw = raw_path(parm)
        if raw:
            refs.append((parm, raw))
    return refs


def copy_file_into_library(source: str, prefs, own_dir: str, staged=None) -> str:
    """One file into `own_dir/textures/`, in `staged`'s save or its own; its own path, or ""."""
    rest = _inside(source, own_dir)
    if rest:
        return OWN_PREFIX + rest
    if not os.path.isfile(source):
        return ""
    waiting = {target: written for _kind, target, written in (staged or ())}
    target = _target_path(os.path.join(own_dir, library_files.TEXTURES), source, waiting)
    if not os.path.exists(target) and target not in waiting:
        entry = asset_record.staged_write(target, lambda scratch: shutil.copyfile(source, scratch))
        if staged is None:
            asset_record.commit_staged_files(prefs, [entry])
        else:
            staged.append(entry)
    return OWN_PREFIX + _inside(target, own_dir)


def copy_into_library(node, prefs, own_dir: str, staged=None) -> list:
    """Every file the node references, own copies in `own_dir`, its parms rewritten; the paths."""
    import hou
    inventory = []
    for parm, raw in references(node):
        if raw.startswith(OWN_PREFIX):
            _remember(inventory, raw)
            continue
        source = (resolve(raw, prefs, own_dir) if raw.startswith(TOKEN_PREFIX)
                  else _read_in_own_folder(hou.text.expandString(raw), prefs, own_dir))
        token = copy_file_into_library(source, prefs, own_dir, staged)
        if not token:
            debug.event("texstore", "referenced file missing",
                        parm=parm.path(), raw=raw)
            continue
        if _set(parm, token, node):    # a parm that was not rewritten is not added to the inventory
            _remember(inventory, token)
    return inventory


def resolve_parms(node, prefs, write_path=None, own_dir: str = "") -> int:
    """Each own or library path under the node set to the `write_path` result; the count."""
    style = getattr(prefs, "path_style", "home")    # Write Paths As, which needs Houdini to apply
    changed = 0
    for parm, raw in references(node):
        if raw.startswith((OWN_PREFIX, TOKEN_PREFIX)):
            path = resolve(raw, prefs, own_dir)
            _set(parm, write_path(path, style) if write_path is not None else path, node)
            changed += 1
    return changed


def _target_path(destination: str, source: str, waiting=None) -> str:
    """`source`'s basename, numbered while a different file has it, on disk or `waiting` to go."""
    def taken(target):
        there = (waiting or {}).get(target) or (target if os.path.exists(target) else "")
        return bool(there) and not filecmp.cmp(source, there, shallow=False)
    return hostos.free_name(destination, hostos.safe_filename(os.path.basename(source)), taken)


def _set(parm, value: str, root) -> bool:
    """Write `value`; follow a reference only to a parm under `root`. ▸r/texture-refs"""
    import hou
    try:
        parm.set(value, follow_parm_reference=_reference_ends_under(parm, root))
        return True
    except (hou.OperationFailed, hou.PermissionError) as exc:    # locked or keyframed: the reference stands ▸r/hou-errors
        debug.event("texstore", "parm not rewritten", parm=parm.path(),
                    error=str(exc))
        return False


def _reference_ends_under(parm, root) -> bool:
    """Whether the end of `parm`'s reference chain is `root` or a node under it."""
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
