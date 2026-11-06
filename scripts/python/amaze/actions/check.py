"""Check Library in the panel: the library let go before an action, read again after it."""

from amaze.core import debug
from amaze.core import library as library_mod


def let_go(panel) -> None:
    """Every list and the settings written, and no stamp check left running to write after."""
    library_mod.stamps.cancel()
    for model in panel.library_models():
        save = getattr(model, "save", None)
        if save is not None:
            save()
    panel.prefs.save()
    debug.event("repair", "the panel let go of the library", dir=str(panel.prefs.dir))


def read_again(panel) -> None:
    """The Reload path without its save: settings, then every model, read from disk."""
    panel.prefs.load()
    panel.open_library()
    panel.stand_again()
    debug.event("repair", "the panel read the library again", dir=str(panel.prefs.dir))
