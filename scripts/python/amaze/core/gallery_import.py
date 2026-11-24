"""Gallery Import: .gal entries into the library, each through the normal save. ▸r/gallery-entries"""

import contextlib
import os

import hou

from amaze import messages
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


@contextlib.contextmanager
def opened(gallery_path: str):
    """(entry, type_name, category) per material in one .gal, live until the gallery is put back."""
    gallery_path = os.path.abspath(os.path.expanduser(gallery_path))
    was_installed = bool(hou.galleries.removeGallery(gallery_path))    # False: not registered; neither call raises ▸r/gallery-entries
    gallery = hou.galleries.installGallery(gallery_path)    # the file's own gallery, or None
    if gallery is None:
        debug.event("gallery", "install failed", file=gallery_path,
                    error="not a gallery, or missing")
        if was_installed and hou.galleries.installGallery(gallery_path) is None:    # put the user's gallery back ▸r/gallery-entries
            debug.event("gallery", "could NOT put the user's gallery back", file=gallery_path)
            debug.alert(messages.GALLERY_NOT_PUT_BACK % gallery_path, key="gallery-not-put-back")
        yield []
        return
    try:    # an entry is dead once its gallery is removed, so the import runs inside this block
        entries = gallery.galleryEntries()
        found = [(entry, node_type.name(), _category_of(entry))
                 for entry, node_type in ((e, _best_type(e)) for e in entries)
                 if node_type is not None
                 and node_type.category().name() in _MATERIAL_CATEGORIES]
        debug.event("gallery", "read file", file=gallery_path,
                    entries=len(entries), materials=len(found))
        yield found
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
    summary = summary if summary is not None else {}    # the caller's dict: after Esc it keeps the counts so far
    for key in ("imported", "skipped", "failed"):
        summary.setdefault(key, 0)
    summary.setdefault("categories", {})
    asked = {} if library is None else {"render": False}    # `library`: one batch render after
    saved_ids = []
    if save is None or not entries:
        return summary
    with hou.undos.disabler():    # make and destroy undo-free, or Ctrl+Z restores it ▸r/undo-groups
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
                    saved_ids.append(node.userData("assetlib_id") or "")    # the id the save wrote on the node
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
        _render_saved(library, saved_ids)    # after Esc too: what was saved gets its picture
    return summary


def _render_saved(library, saved_ids) -> None:
    """One render batch of the saved rows, when Render on Import is on; a failure is only logged."""
    if library is None or not library.preferences.render_on_import:
        return
    try:
        from amaze.render import thumbs
        rows = [library.find_asset_row_by_id(key) for key in saved_ids if key]
        mats = [library.assets[row] for row in rows if row != -1]
        if mats:
            thumbs.ThumbNailRenderer.render_assets(library.preferences, mats)
    except Exception as exc:                          # noqa: BLE001 - never masks the import's own end
        debug.exception("gallery render", exc)
