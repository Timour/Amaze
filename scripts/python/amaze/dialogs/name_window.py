"""The Name window: one name asked for, in a dialog window that leaves Houdini free while open."""

from PySide6 import QtCore

import amaze
from amaze import amazetheme
from amaze.qml import dialog_window

NAME_QML = amaze.package_file("ui", "dialogs", "NameWindow.qml")


class NameWindow(dialog_window.DialogWindow):
    """The Name window: the one name field, OK and Cancel."""

    SOURCE_URL = QtCore.QUrl.fromLocalFile(NAME_QML).toString()
    DEFAULT_SIZE = QtCore.QSize(amazetheme.SAVE_WIDTH, 0)    # D13's width; as tall as its content
    MINIMUM_SIZE = QtCore.QSize(amazetheme.SAVE_WIDTH, 0)


def ask(owner, title: str, default: str, then) -> NameWindow:
    """The Name window on `default`: `then(name)` once, stripped; "" when cleared, None for Cancel."""
    return NameWindow.ask(owner, title, {"text": default},
                          lambda name: then(None if name is None else str(name).strip()))
