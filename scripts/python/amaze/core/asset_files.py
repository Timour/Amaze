"""The files one asset owns, by kind; the library model and the version store both ask here."""

from amaze.core import debug, library_files, material, tile_icons


def asset_files_for(preferences, mat_id: str, section: str) -> dict:
    """{kind: path} of every FILE a `section` row owns; {} for an unsafe id."""
    mat_id = str(mat_id)
    if not material.is_safe_asset_id(mat_id):    # read verbatim from a database: `../x` escapes
        debug.event("library", "asset id cannot name a file - it owns "
                    "no paths", mat_id=mat_id)
        return {}

    found = {"thumbnail": tile_icons.thumbnail_path(preferences, mat_id, section)}    # render or capture
    if section not in library_files.ASSET_SECTIONS:    # Code and Colors keep their rows inline
        return found

    def owned(suffix):
        return material.payload_path(preferences, mat_id, suffix, section)

    found.update({
        "mat": owned(preferences.ext),
        "json": owned(material.RECORD_SUFFIX),
        "cop": owned("_cop" + preferences.ext),
    })
    return found
