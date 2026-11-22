"""Check Library in the panel: save the library before each action, read it from disk after."""

from amaze.core import debug, library_db


def save_before_check(pane) -> None:
    """Save every model's records and the settings, then every pending database change."""
    for model in pane.library.models():
        save = getattr(model, "save", None)
        if save is not None:
            save()
    pane.prefs.save()
    library_db.flush()
    debug.event("repair", "the pane saved the library", dir=str(pane.prefs.dir))


def reload_after_check(pane) -> None:
    """The Reload path without its save: settings, then every model, read from disk."""
    library_db.release(pane.prefs)    # drop the cached databases: Check Library's changes are read from disk
    pane.prefs.load()
    pane.library.open_library()
    pane.sidebar.reselect()
    debug.event("repair", "the pane read the library again", dir=str(pane.prefs.dir))
