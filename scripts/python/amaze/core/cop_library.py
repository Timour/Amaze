"""Models for the Nodes section - standalone node-network assets, saved from and restored into any context Houdini has. ▸p/nodes-section"""

from amaze.core import library, category


class CopCategories(category.Categories):
    """The Cop section's category sidebar - same model, own database."""

    DB_FILENAME = "cops.json"


class CopLibrary(library.AssetLibrary):
    """The Cop section's asset model - the shared engine over cops.json."""

    TILE_FACE = "icon_nodes"    # T07

    NOTES_SECTION = "cop"    # the section was Copernicus-only once, so every `cop` name here and in the saved data is load-bearing and stayed put when the section widened

    DB_FILENAME = "cops.json"    # its own database in the material library's directory, but the asset FILES share that library's folders - `<id>.mat`, `<id>.interface` and `<id>.png` under globally unique ids - so `cleanup_db` unions the ids of BOTH databases before calling any file an orphan

    RENDERABLE = ("SOP", "COP", "")    # contexts whose tiles can hold a rendered picture at all; every other one gets the node icon, and the empty string is the pre-context COP assets ▸p/nodes-section

    def can_preview(self, row: int) -> bool:
        """Only a RENDERABLE context can hold a picture; any other node asset shows its node icon."""
        if not 0 <= row < len(self._assets):
            return False
        return str(self._assets[row].renderer or "").upper() in self.RENDERABLE
