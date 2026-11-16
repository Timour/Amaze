"""Check Library in the panel: the library let go before an action, read again after it."""

from amaze.core import debug, library_db


def let_go(panel) -> None:
    """Every model's records and the settings handed over, and every waiting change saved."""
    for model in panel.library_models():
        save = getattr(model, "save", None)
        if save is not None:
            save()
    panel.prefs.save()
    library_db.flush()
    debug.event("repair", "the panel let go of the library", dir=str(panel.prefs.dir))


def read_again(panel) -> None:
    """The Reload path without its save: settings, then every model, read from disk."""
    library_db.release(panel.prefs)    # what Check Library changed is read from the files
    panel.prefs.load()
    panel.open_library()
    panel.stand_again()
    debug.event("repair", "the panel read the library again", dir=str(panel.prefs.dir))
