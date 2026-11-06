"""Models for the Nodes section: node-network assets of any context. ▸p/nodes-section"""

from amaze.core import library, category, renderers


class CopCategories(category.Categories):
    """The Cop section's category sidebar - same model, own database."""

    DB_FILENAME = "cops.json"


class CopLibrary(library.AssetLibrary):
    """The Cop section's asset model - the shared engine over cops.json."""

    TILE_FACE = "icon_nodes"    # T07

    NOTES_SECTION = "cop"    # every `cop` name here is in saved data; never rename it

    DB_FILENAME = "cops.json"    # its own database; the asset files share the material folders

    ROW_NOUN = "node setup"    # the manual's name for a row of this section

    RENDERABLE = renderers.RENDERABLE_CONTEXTS    # the one set, which Check Library reads too

    def can_preview(self, row: int) -> bool:
        """Only a renderable context can hold a picture; any other node asset shows its node icon."""
        if not 0 <= row < len(self._assets):
            return False
        return renderers.can_hold_a_render(self._assets[row].renderer)
