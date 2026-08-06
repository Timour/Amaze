"""Gallery Import: Houdini .gal gallery entries -> Amaze library.

A gallery entry is a node preset (parameters, channels, spare parms and
- for subnet types - the whole child network), instantiated by
hou.GalleryEntry.createChildNode. Every material a user built before
Amaze lives in these files: the Material Palette's own galleries under
$HOUDINI_USER_PREF_DIR/gallery plus whatever ships with Houdini.

The import runs each entry through the SAME save funnel a hand-saved
material takes (MaterialLibrary.add_asset), so a gallery material is
indistinguishable from one saved by hand afterwards.

Thumbnails are deliberately NOT rendered during a bulk run (hundreds of
Karma renders would take hours): the caller restores its own
render_on_import preference and the user renders a selection
afterwards, which is also interruptible and resumable.
"""

import os

import hou

from amaze.core import debug

#: Node-type categories whose entries can become library materials.
#: Everything else in a gallery (lsystem SOP presets, for example) is
#: reported as skipped rather than silently ignored.
_MATERIAL_CATEGORIES = ("Vop", "Lop")


def default_gallery_dir() -> str:
    """Where Houdini keeps the user's own galleries - the sensible
    place to open a file dialog, since most users have never seen the
    path."""
    pref_dir = hou.getenv("HOUDINI_USER_PREF_DIR") or ""
    if pref_dir:
        candidate = os.path.join(pref_dir, "gallery")
        if os.path.isdir(candidate):
            return candidate
        return pref_dir
    return os.path.expanduser("~")


def entries_from_file(gallery_path: str) -> list:
    """Material entries from ONE .gal file, as (entry, type_name,
    category_label).

    Houdini reads galleries by PATH REGISTRATION, and a freshly
    installed gallery is appended LAST to hou.galleries.galleries()
    (verified on both installs) - so the file is re-registered
    (removed first, in case it was already on the path, which also
    makes the append position deterministic), read from the last
    gallery object, and left registered exactly as it was found.
    """
    gallery_path = os.path.abspath(os.path.expanduser(gallery_path))
    was_installed = False
    try:
        hou.galleries.removeGallery(gallery_path)
        was_installed = True
    except (AttributeError, hou.OperationFailed, hou.Error):
        pass          # not previously registered - nothing to restore
    try:
        hou.galleries.installGallery(gallery_path)
    except (AttributeError, hou.Error) as exc:
        debug.event("gallery", "install failed",
                    file=gallery_path, error=str(exc))
        # PUT IT BACK. removeGallery above already succeeded, so
        # returning here left a gallery the user HAD registered off
        # their path for the rest of the Houdini session - from a
        # browse operation whose docstring promises to leave it
        # "registered exactly as it was found". The restoring finally
        # below is never entered on this path, and only covers the
        # opposite case anyway.
        if was_installed:
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
            # Leave the user's gallery path as it was found.
            try:
                hou.galleries.removeGallery(gallery_path)
            except (AttributeError, hou.Error):
                pass


def _best_type(entry):
    try:
        return entry.bestNodeType()
    except hou.Error:
        return None


def _category_of(entry) -> str:
    """The Amaze category for an entry: the LAST component of its own
    gallery category ("Redshift/Materials/Fabric" -> "Fabric"), which
    is how the palette already organised them. "Gallery" when an entry
    carries none."""
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
    """Import (entry, type_name, category) tuples into `model` (a
    MaterialLibrary). Returns a summary dict.

    Each entry is instantiated in a throwaway staging network, saved
    through model.add_asset, then destroyed - the scene is left exactly
    as it was found. Undo is disabled for the whole run: nothing
    user-visible remains to undo, and hundreds of node creations would
    otherwise bury the user's own undo history.
    """
    summary = {"imported": 0, "skipped": 0, "failed": 0, "categories": {}}
    if model is None or not entries:
        return summary
    # The container joins the disabler below at BOTH ends: created or
    # destroyed on the live stack, one Ctrl+Z resurrects it (#278) -
    # this pair sat just outside the block the docstring promises.
    with hou.undos.disabler():
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
                    node = entry.createChildNode(parent)
                    if node is None:
                        summary["skipped"] += 1
                        continue
                    node.setGenericFlag(hou.nodeFlag.Material, True)
                    model.add_asset(node, category, "gallery", False)
                    summary["imported"] += 1
                    summary["categories"][category] = summary[
                        "categories"
                    ].get(category, 0) + 1
                except hou.Error as exc:
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
