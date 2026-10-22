"""The files one asset owns, by kind; the library model and the version store both ask here."""

from amaze.core import captures, debug, material, tile_icons


def asset_files_for(preferences, mat_id: str) -> dict:
    """{kind: path} of every FILE `mat_id` owns; {} for an unsafe id, and PathEscape propagates."""
    mat_id = str(mat_id)
    if not material.is_safe_asset_id(mat_id):    # read verbatim from library.json: `../x` escapes
        debug.event("library", "asset id cannot name a file - it owns "
                    "no paths", mat_id=mat_id)
        return {}

    def owned(suffix):
        return material.payload_path(preferences, mat_id, suffix)

    return {
        "mat": owned(preferences.ext),
        "interface": owned(".interface"),
        "builder": owned(material.BUILDER_SUFFIX),
        "stamp": owned(material.STAMP_SUFFIX),
        "cop": owned("_cop" + preferences.ext),
        "thumbnail": tile_icons.thumbnail_path(preferences, mat_id),
        "tile_icon": tile_icons.icon_image_path(preferences, mat_id),
        "capture": captures.asset_path(preferences, mat_id),
    }
