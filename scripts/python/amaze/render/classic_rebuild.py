"""The library conversion's node work: a saved classic container rebuilt as its USD builder."""

import hou

from amaze.core import library_files, material, texstore
from amaze.render import nodes


class Rebuilder:
    """The object `library_conversion.convert` queries and passes the classic Materials to."""

    def __init__(self, preferences, ask) -> None:
        self._preferences = preferences
        self._ask = ask    # (count, renderer) -> True to move them to the trash, False to cancel

    def loaded(self, renderer) -> bool:
        """Whether this session can create both of `renderer`'s containers."""
        return all(nodes.node_type_available(name)
                   for name in (renderer.classic_container, renderer.usd_builder))

    def ask(self, count: int, renderer) -> bool:
        return bool(self._ask(count, renderer))

    def rebuild(self, asset_id: str, name: str, renderer) -> None:
        """Rewrite the asset's `.mat` and builder as `renderer`'s USD builder; raises when it cannot."""
        from amaze.render.material_conversion import engine    # late: its APIs import render/
        preferences = self._preferences
        mat = material.Material(name=name, renderer=renderer.key, mat_id=asset_id)
        handler = nodes.NodeHandler(preferences)
        with hou.undos.disabler():
            scratch = hou.node("/obj").createNode("matnet")
            try:
                fresh = engine.ready_for_solaris(handler.rebuild_saved(mat, scratch), renderer.key)
                if fresh.type().name() != renderer.usd_builder:
                    raise hou.OperationFailed(
                        "it was not rebuilt as %s" % renderer.usd_builder)
                texstore.adopt(fresh, preferences, texstore.asset_folder(name, asset_id))
                items = fresh.allItems()    # NOT children(): a dot is no child
                handler.save_asset_pair(
                    material.payload_path(preferences, asset_id, preferences.ext,
                                          library_files.MATERIALS),
                    lambda path: fresh.saveItemsToFile(
                        items, path, save_hda_fallbacks=nodes.hda_fallbacks_needed(items)),
                    builder_node=fresh, asset_id=asset_id)
            finally:
                scratch.destroy()
