"""Models for the Nodes section: node-network assets of any context. ▸p/nodes-section"""

from amaze.core import library, category


class CopCategories(category.Categories):
    """The Cop section's category sidebar - same model, own database."""

    DB_FILENAME = "cops.json"


class CopLibrary(library.AssetLibrary):
    """The Cop section's asset model - the shared engine over cops.json."""

    TILE_FACE = "icon_nodes"    # T07

    NOTES_SECTION = "cop"    # every `cop` name here is in saved data; never rename it

    DB_FILENAME = "cops.json"    # its own database; the asset files share the material folders

    RENDERABLE = ("SOP", "COP", "")    # contexts whose tiles can hold a render; "" is a pre-context COP ▸p/nodes-section

    def can_preview(self, row: int) -> bool:
        """Only a RENDERABLE context can hold a picture; any other node asset shows its node icon."""
        if not 0 <= row < len(self._assets):
            return False
        return str(self._assets[row].renderer or "").upper() in self.RENDERABLE
