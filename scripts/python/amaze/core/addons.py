"""Add-ons: Houdini packages shipped as `.amazepkg`, installed inside Amaze, one folder each."""

import json
import os
import re
import shutil
import zipfile
import zlib

from amaze import branding
from amaze.core import packages
from amaze.helpers import hostos

KIND = "houdini-package"
ROOT = "addons"    #: the add-ons' folder, in Amaze's install and in the package store alike
FOLDERS = ("shapes",)    #: the folders Amaze.json puts on Houdini's path; any other is refused
REQUIRED = ("name", "folder", "version", "author", "houdini", "houdini_min", "changelog")
NODE_KEYS = ("label", "type", "file", "addon_icon", "short_description", "description")
SHOWN = ("addon_icon", "short_description")    #: what a group's row shows; its nodes must agree
PICTURES = (".svg", ".png")    #: what the Add-On tab draws; a node's Houdini icon stays in its .hda
_VERSION = re.compile(r"\d+\.\d+\.\d+$")
_MAJOR_MINOR = re.compile(r"\d+\.\d+$")


def _relative(member) -> bool:
    """Whether `member` is a plain relative path that stays inside its add-on folder."""
    if not isinstance(member, str) or not member or member == packages.MANIFEST:
        return False
    if member.startswith(("/", "\\")) or ":" in member or "\\" in member:
        return False
    return all(part not in ("", ".", "..") for part in member.split("/"))


def problems(manifest) -> list:
    """What keeps `manifest` from being an installable add-on, one sentence each; [] when it is one."""
    found = [] if manifest.get("kind") == KIND else ["not an add-on package"]
    found += ["no %s" % key for key in REQUIRED if not str(manifest.get(key) or "").strip()]
    if manifest.get("version") and not _VERSION.match(str(manifest["version"])):
        found.append("version %r is not X.Y.Z" % manifest["version"])
    if manifest.get("houdini_min") and not _MAJOR_MINOR.match(str(manifest["houdini_min"])):
        found.append("houdini_min %r is not MAJOR.MINOR" % manifest["houdini_min"])
    if manifest.get("folder") not in FOLDERS:
        found.append("Amaze has no add-on folder %r" % manifest.get("folder"))
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        return found + ["no files"]
    found += ["%r is not a plain relative path" % member for member in files
              if not _relative(member)]
    return found + _node_problems(manifest.get("nodes"), set(files))


def _node_problems(nodes, files) -> list:
    """What is wrong with the node list, against the package's own files, and its groups."""
    if not isinstance(nodes, list) or not nodes:
        return ["no nodes"]
    found = []
    for node in nodes:
        missing = [key for key in NODE_KEYS if not isinstance(node, dict) or key not in node]
        if missing:
            found.append("a node lacks %s" % ", ".join(missing))
            continue
        label = node["label"]
        found += ["%s: %s %r is not in files" % (label, key, node[key])
                  for key in ("file", "addon_icon") if node[key] not in files]
        if not str(node["addon_icon"]).lower().endswith(PICTURES):
            found.append("%s: addon_icon %r is not an .svg or .png" % (label, node["addon_icon"]))
        found += ["%s: %s is not text" % (label, key) for key in ("short_description", "description")
                  if not isinstance(node[key], str)]
        if not isinstance(node.get("group", ""), str):
            found.append("%s: group is not text" % label)
    return found + _group_problems(nodes)


def _group(node) -> str:
    """The group `node` is in, or "" when it is in none and is a row of its own."""
    group = node.get("group") if isinstance(node, dict) else ""
    return group.strip() if isinstance(group, str) else ""


def _group_problems(nodes) -> list:
    """A group is one row showing one icon and one short description, so its nodes must agree."""
    first, found = {}, []
    for node in nodes:
        if not _group(node):
            continue
        shown = tuple(node.get(key) for key in SHOWN)
        label, seen = first.setdefault(_group(node), (node.get("label"), shown))
        differ = [key for key, mine, theirs in zip(SHOWN, shown, seen) if mine != theirs]
        if differ:
            found.append("%s and %s share group %r but differ in %s"
                         % (label, node.get("label"), _group(node), " and ".join(differ)))
    return found


def rows(manifest) -> list:
    """The Add-On tab's rows in package order: a group is listed once under its name, others alone."""
    found, index = [], {}
    for node in manifest["nodes"]:
        key = ("group", _group(node)) if _group(node) else ("node", node["type"])
        if key not in index:
            index[key] = len(found)
            found.append(dict({k: node[k] for k in SHOWN},
                              name=_group(node) or node["label"], nodes=[]))
        found[index[key]]["nodes"].append(node)
    return found


def file_name(manifest) -> str:
    """`<name>-<X.Y.Z>.amazepkg`, the name the store finds the newest version by."""
    return "%s-%s%s" % (manifest["name"], manifest["version"], packages.SUFFIX)


def write(out_dir: str, fields: dict, root: str, files) -> str:
    """The ONE add-on package writer: `files`, relative to `root`, into `out_dir`; answers the path."""
    manifest = dict(fields, format=packages.FORMAT, kind=KIND, app=branding.APP_VERSION,
                    files=sorted(set(files)))
    found = problems(manifest)
    found += ["no file %s under %s" % (member, root) for member in manifest["files"]
              if _relative(member) and not os.path.isfile(os.path.join(root, *member.split("/")))]
    if found:
        raise packages.PackageError("not an add-on Amaze can install: %s" % "; ".join(found))
    out_path = os.path.join(out_dir, file_name(manifest))
    hostos.check_sandbox(out_path)
    with hostos.scratch_beside(out_path) as scratch:
        with zipfile.ZipFile(scratch, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr(packages.MANIFEST, json.dumps(manifest, indent=2))
            for member in manifest["files"]:
                bundle.write(os.path.join(root, *member.split("/")), member)
    return out_path


def _checked(bundle, path) -> dict:
    """The manifest of an OPEN package, refused whole unless it is a whole, installable add-on."""
    manifest = packages.manifest_from(bundle, path)
    found = problems(manifest)
    files = manifest.get("files")
    listed = set(files) if isinstance(files, list) else set()
    members = {name for name in bundle.namelist()
               if not name.endswith("/") and name != packages.MANIFEST}
    found += ["missing member %s" % member for member in sorted(listed - members)]
    found += ["member %s is not listed" % member for member in sorted(members - listed)]
    if found:
        raise packages.PackageError("%s is not an add-on Amaze can install: %s"
                                    % (os.path.basename(path), "; ".join(found)))
    return manifest


def read(path: str) -> dict:
    """An add-on package's manifest, through one open of the file, refused whole unless it is one."""
    try:
        with zipfile.ZipFile(path) as bundle:
            return _checked(bundle, path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise packages.PackageError("cannot read %s: %s" % (path, exc)) from None


def install(path: str, amaze_root: str, running=None) -> dict:
    """Install `path` as `<amaze_root>/addons/<folder>`, replacing that folder whole; answers it."""
    from amaze.helpers import hostver
    try:
        bundle = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise packages.PackageError("cannot read %s: %s" % (path, exc)) from None
    with bundle:
        manifest = _checked(bundle, path)
        needed = tuple(int(part) for part in manifest["houdini_min"].split("."))
        if not hostver.houdini_at_least(needed, running):
            raise packages.PackageError("%s %s needs Houdini %s or newer" % (
                manifest["name"], manifest["version"], manifest["houdini_min"]))
        target = os.path.join(amaze_root, ROOT, manifest["folder"])
        staging = target + ".installing"
        hostos.check_sandbox(staging)
        shutil.rmtree(staging, ignore_errors=True)
        try:
            for member in manifest["files"]:
                dest = os.path.join(staging, *member.split("/"))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "wb") as handle:
                    handle.write(bundle.read(member))
            with open(os.path.join(staging, packages.MANIFEST), "w", encoding="utf-8") as handle:
                json.dump(manifest, handle, indent=2)
        except (OSError, zipfile.BadZipFile, zlib.error) as exc:
            shutil.rmtree(staging, ignore_errors=True)
            raise packages.PackageError("%s did not install: %s" % (manifest["name"], exc)) from None
    _swap(staging, target)
    return manifest


def _swap(staging: str, target: str) -> None:
    """Put `staging` where `target` is; the old folder stands aside only for the swap, then goes."""
    aside = target + ".replacing"
    shutil.rmtree(aside, ignore_errors=True)
    if os.path.isdir(target):
        os.rename(target, aside)
    try:
        os.rename(staging, target)
    except OSError as exc:
        if os.path.isdir(aside):
            os.rename(aside, target)
        shutil.rmtree(staging, ignore_errors=True)
        raise packages.PackageError("the add-on did not replace %s: %s" % (target, exc)) from None
    shutil.rmtree(aside, ignore_errors=True)


def installed(amaze_root: str, folder: str):
    """The manifest of the add-on installed as `<amaze_root>/addons/<folder>`, or None."""
    try:
        with open(os.path.join(amaze_root, ROOT, folder, packages.MANIFEST),
                  encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, ValueError):
        return None
    return manifest if isinstance(manifest, dict) else None


def carry(old_root: str, new_root: str) -> bool:
    """Move the installed add-ons out of an install being replaced into its replacement."""
    source, dest = os.path.join(old_root, ROOT), os.path.join(new_root, ROOT)
    if not os.path.isdir(source) or os.path.exists(dest):
        return False
    shutil.move(source, dest)
    return True
