"""What an update asks and says; the About tab, the shelf's Updates tool and the panel share it."""

import hou

from amaze import messages
from amaze.core import debug, updater


def install_and_say(found) -> bool:
    """Install `found` and say in a message how it went; True once it is installed."""
    try:
        updater.install(found)
    except OSError as exc:
        hou.ui.displayMessage(str(exc), title=messages.TITLE_AMAZE)    # already a finished sentence
        return False
    except Exception as exc:                                  # noqa: BLE001
        debug.exception("update install", exc)
        hou.ui.displayMessage(messages.UPDATE_FAILED_UNEXPECTED % exc, title=messages.TITLE_AMAZE)
        return False
    hou.ui.displayMessage(messages.UPDATE_INSTALLED % found.version, title=messages.TITLE_AMAZE)
    return True


def confirmed(found, library_dir: str) -> bool:
    """Continue or Cancel, asked only when installing `found` updates the library."""
    if not updater.updates_library(found, library_dir):
        return True
    return hou.ui.displayMessage(
        messages.LIBRARY_UPDATE_WARNING % found.library_since,
        buttons=messages.BUTTONS_CONTINUE, default_choice=1, close_choice=1,
        severity=hou.severityType.Warning, title=messages.TITLE_AMAZE) == 0
