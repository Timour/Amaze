"""Which user is this machine, on a library that already has some.

Asked once, and only in the case that earns it: the library has people
in it and this machine's pointer names none of them (ROADMAP line 21).
A library with nobody yet mints silently and never reaches here.
"""

from __future__ import annotations

from PySide6 import QtWidgets

from amaze.dialogs.base_dialog import AssetDialog


class UserPickerDialog(AssetDialog):
    """Pick an existing user, or create one.

    `uid` is set when an existing user was picked, `new_name` when a new
    one was named; both stay empty if the dialog was cancelled.
    """

    #: itemData for the create row. Not a name and not a UID, so it can
    #: never be mistaken for either.
    CREATE = "\x00create"

    def __init__(self, known: dict) -> None:
        super().__init__("Who is using this library?")
        self.uid = ""
        self.new_name = ""

        self._combo = QtWidgets.QComboBox()
        for user_id, name in sorted(known.items(),
                                    key=lambda pair: pair[1].lower()):
            self._combo.addItem(name, user_id)
        self._combo.addItem("Create a new user...", self.CREATE)
        self.add_row("You are", self._combo)
        self._line = self.add_line("New name")

        # Connected AFTER populating: the first `addItem` on an empty
        # combo emits `currentIndexChanged(0)` (research.md ▸ Qt
        # widgets, measured), which would run this before the field
        # exists.
        self._combo.currentIndexChanged.connect(self._sync_new_name)
        self.finish()
        self._sync_new_name()

    def _sync_new_name(self, _index: int = 0) -> None:
        creating = self._combo.currentData() == self.CREATE
        self._line.setEnabled(creating)
        if creating:
            self._line.setFocus()

    def _on_accept(self) -> None:
        data = self._combo.currentData()
        if data == self.CREATE:
            self.new_name = self._line.text().strip()
        else:
            self.uid = str(data or "")
        super()._on_accept()
