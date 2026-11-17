"""Check Library in the panel: save the library before each action, read it from disk after."""

from amaze.core import debug, library_db


def save_before_check(panel) -> None:
    """Save every model's records and the settings, then every pending database change."""
    for model in panel.library_models():
        save = getattr(model, "save", None)
        if save is not None:
            save()
    panel.prefs.save()
    library_db.flush()
    debug.event("repair", "the panel saved the library", dir=str(panel.prefs.dir))


def reload_after_check(panel) -> None:
    """The Reload path without its save: settings, then every model, read from disk."""
    library_db.release(panel.prefs)    # drop the cached databases: Check Library's changes are read from disk
    panel.prefs.load()
    panel.open_library()
    panel.reselect_sidebar_row()
    debug.event("repair", "the panel read the library again", dir=str(panel.prefs.dir))
