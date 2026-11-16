"""Models for the Nodes section: node-network assets of any context. ▸p/nodes-section"""

from amaze.core import library, category, library_files, renderers, versions


class CopCategories(category.Categories):
    """The Cop section's category sidebar - same model, own database."""

    DB_FILENAME = library_files.NODES


class CopLibrary(library.AssetLibrary):
    """The Cop section's asset model - the shared AssetLibrary model, reading nodes.json."""

    TILE_FACE = "icon_nodes"    # T07

    NOTES_SECTION = "cop"    # the key prefix of its comments; never rename it

    DB_FILENAME = library_files.NODES    # its own database, and its own folder of asset files

    VERSION_SECTION = versions.NODE

    ROW_NOUN = "node setup"    # the manual's name for a row of this section

    RENDERABLE = renderers.RENDERABLE_CONTEXTS    # defined in renderers.py; Check Library reads it too

    def can_preview(self, row: int) -> bool:
        """Only a renderable context has a rendered thumbnail; other node assets show the node icon."""
        if not 0 <= row < len(self._assets):
            return False
        return renderers.can_hold_a_render(self._assets[row].renderer)
