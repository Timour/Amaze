"""Gallery Import: .gal entries into the library, each through the normal save. ▸r/gallery-entries"""

import os

import hou

from amaze.core import debug

_MATERIAL_CATEGORIES = ("Vop", "Lop")    # anything else is skipped ▸r/gallery-entries


def default_gallery_dir() -> str:
    """Where Houdini keeps the user's own galleries, for a file dialog to open at."""
    pref_dir = hou.getenv("HOUDINI_USER_PREF_DIR") or ""
    if pref_dir:
        candidate = os.path.join(pref_dir, "gallery")
        if os.path.isdir(candidate):
            return candidate
        return pref_dir
    return os.path.expanduser("~")


def entries_from_file(gallery_path: str) -> list:
    """(entry, type_name, category) per material in one .gal, its registration kept. ▸r/gallery-entries"""
    gallery_path = os.path.abspath(os.path.expanduser(gallery_path))
    was_installed = bool(hou.galleries.removeGallery(gallery_path))    # False: not registered; neither call raises ▸r/gallery-entries
    gallery = hou.galleries.installGallery(gallery_path)    # the file's own gallery, or None
    if gallery is None:
        debug.event("gallery", "install failed", file=gallery_path,
                    error="not a gallery, or missing")
        if was_installed and hou.galleries.installGallery(gallery_path) is None:    # put the user's gallery back ▸r/gallery-entries
            debug.event("gallery", "could NOT put the user's gallery "
                        "back", file=gallery_path)
        return []
    try:
        entries = gallery.galleryEntries()
        found = [
            (entry, node_type.name(), _category_of(entry))
            for entry, node_type in (
                (e, _best_type(e)) for e in entries
            )
            if node_type is not None
            and node_type.category().name() in _MATERIAL_CATEGORIES
        ]
        debug.event("gallery", "read file", file=gallery_path,
                    entries=len(entries), materials=len(found))
        return found
    finally:
        if not was_installed:    # leave the user's gallery path as it was found
            hou.galleries.removeGallery(gallery_path)


def _best_type(entry):
    try:
        return entry.bestNodeType()
    except hou.Error:
        return None


def _category_of(entry) -> str:
    """The last component of the entry's gallery category, or `Gallery` when it has none."""
    try:
        cats = entry.categories()
    except hou.Error:
        cats = ()
    for raw in cats:
        leaf = str(raw).rstrip("/").split("/")[-1].strip()
        if leaf:
            return leaf
    return "Gallery"


def import_entries(save, entries, staging_parent=None,
                   progress=None, summary=None, library=None) -> dict:
    """Each (entry, type_name, category) saved through `save`, staged and undo-free. ▸r/gallery-entries"""
    summary = summary if summary is not None else {}    # the caller's: an Esc keeps what landed
    for key in ("imported", "skipped", "failed"):
        summary.setdefault(key, 0)
    summary.setdefault("categories", {})
    asked = {} if library is None else {"render": False}    # `library`: ONE batch renders after
    landed = []
    if save is None or not entries:
        return summary
    with hou.undos.disabler():    # the container joins the disabler at BOTH ends, or one Ctrl+Z resurrects it ▸r/undo-groups
        parent = staging_parent or hou.node("/obj").createNode("matnet")
    owns_parent = staging_parent is None
    try:
        with hou.undos.disabler():
            for index, (entry, type_name, category) in enumerate(entries):
                if progress is not None:
                    progress(index, len(entries), entry.name())
                node = None
                try:
                    if not entry.canCreateChildNode(parent):
                        summary["skipped"] += 1
                        debug.event("gallery", "entry not instantiable",
                                    entry=entry.name(), type=type_name)
                        continue
                    node = entry.createChildNode(parent)    # a node, or raises ▸r/gallery-entries
                    node.setGenericFlag(hou.nodeFlag.Material, True)
                    if not save(node, category, "gallery", False, **asked):
                        summary["failed"] += 1    # a refused save counts as failed ▸r/gallery-entries
                        debug.event("gallery", "entry was not saved",
                                    entry=entry.name(), type=type_name)
                        continue
                    summary["imported"] += 1
                    summary["categories"][category] = summary[
                        "categories"
                    ].get(category, 0) + 1
                    landed.append(node.userData("assetlib_id") or "")    # the save's own stamp
                except (AttributeError, hou.Error) as exc:    # one entry fails, not the run ▸r/gallery-entries
                    summary["failed"] += 1
                    debug.event("gallery", "entry import failed",
                                entry=entry.name(), type=type_name,
                                error=str(exc))
                finally:
                    if node is not None:
                        try:
                            node.destroy()
                        except hou.Error:
                            pass
    finally:
        if owns_parent:
            try:
                with hou.undos.disabler():
                    parent.destroy()
            except hou.Error:
                pass
    debug.event("gallery", "import finished", **{
        k: v for k, v in summary.items() if k != "categories"
    })
    if library is not None and library.preferences.render_on_import:
        from amaze.render import thumbs
        rows = [library.find_asset_row_by_id(key) for key in landed if key]
        mats = [library.assets[row] for row in rows if row != -1]
        if mats:
            thumbs.ThumbNailRenderer.render_assets(library.preferences, mats)
    return summary
