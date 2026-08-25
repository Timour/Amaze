"""Gallery Import: Houdini .gal gallery entries -> Amaze library, each run through the SAME save funnel a hand-saved material takes. ▸r/gallery-entries"""

import os

import hou

from amaze.core import debug

_MATERIAL_CATEGORIES = ("Vop", "Lop")    # everything else in a gallery is reported as SKIPPED, never silently ignored ▸r/gallery-entries


def default_gallery_dir() -> str:
    """Where Houdini keeps the user's own galleries - the sensible place to open a file dialog, since most users have never seen the path."""
    pref_dir = hou.getenv("HOUDINI_USER_PREF_DIR") or ""
    if pref_dir:
        candidate = os.path.join(pref_dir, "gallery")
        if os.path.isdir(candidate):
            return candidate
        return pref_dir
    return os.path.expanduser("~")


def entries_from_file(gallery_path: str) -> list:
    """Material entries from ONE .gal file, as (entry, type_name, category_label) - the file is left registered exactly as it was found, on every path out. ▸r/gallery-entries"""
    gallery_path = os.path.abspath(os.path.expanduser(gallery_path))
    was_installed = False
    try:
        hou.galleries.removeGallery(gallery_path)
        was_installed = True
    except (AttributeError, hou.Error):
        pass          # not previously registered - nothing to restore; `hou.OperationFailed` is a SUBCLASS of hou.Error and naming it added nothing ▸r/gallery-entries
    try:
        hou.galleries.installGallery(gallery_path)
    except (AttributeError, hou.Error) as exc:
        debug.event("gallery", "install failed",
                    file=gallery_path, error=str(exc))
        if was_installed:    # PUT IT BACK: removeGallery already succeeded, and the finally below never runs on this path ▸r/gallery-entries
            try:
                hou.galleries.installGallery(gallery_path)
            except (AttributeError, hou.Error) as restore_exc:
                debug.event("gallery", "could NOT put the user's gallery "
                            "back", file=gallery_path,
                            error=str(restore_exc))
        return []
    try:
        galleries = list(hou.galleries.galleries())
        entries = galleries[-1].galleryEntries() if galleries else []
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
        if not was_installed:
            try:    # leave the user's gallery path as it was found
                hou.galleries.removeGallery(gallery_path)
            except (AttributeError, hou.Error):
                pass


def _best_type(entry):
    try:
        return entry.bestNodeType()
    except hou.Error:
        return None


def _category_of(entry) -> str:
    """The Amaze category for an entry: the LAST component of its own gallery category, as the palette already organised them, or `Gallery` when it carries none."""
    try:
        cats = entry.categories()
    except hou.Error:
        cats = ()
    for raw in cats:
        leaf = str(raw).rstrip("/").split("/")[-1].strip()
        if leaf:
            return leaf
    return "Gallery"


def import_entries(model, entries, staging_parent=None,
                   progress=None) -> dict:
    """Import (entry, type_name, category) tuples into `model`, returning a summary dict - staged in a throwaway network, undo disabled for the whole run. ▸r/gallery-entries"""
    summary = {"imported": 0, "skipped": 0, "failed": 0, "categories": {}}
    if model is None or not entries:
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
                    node = entry.createChildNode(parent)    # documented `-> Node` and measured so on 25 real entries: it returns a node or RAISES, never None ▸r/gallery-entries
                    node.setGenericFlag(hou.nodeFlag.Material, True)
                    if not model.add_asset(node, category, "gallery", False):
                        summary["failed"] += 1    # a refused save lands in failed, never imported: the summary is all the user reads after a bulk run ▸r/gallery-entries
                        debug.event("gallery", "entry was not saved",
                                    entry=entry.name(), type=type_name)
                        continue
                    summary["imported"] += 1
                    summary["categories"][category] = summary[
                        "categories"
                    ].get(category, 0) + 1
                except (AttributeError, hou.Error) as exc:    # AttributeError too: if a build ever DID hand back None, one entry fails instead of the whole run aborting ▸r/gallery-entries
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
    return summary
