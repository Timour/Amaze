"""AssetDialog - the shared base for Amaze's form dialogs.

The house dialog style (established across the save/category/code/prefs
dialogs and the preferences consistency passes) is a QFormLayout with
right-aligned labels and fields to the right, native 5px content margins,
an OK/Cancel button row, and a content-hugging fixed size. Every dialog
re-implemented it by hand; this centralises it so they look identical by
construction and a new dialog is a few add_* calls.

See docs/architecture/overview.md - the **Dialog** concept. Sections can
own their dialogs through the Section API's `edit_dialog()` hook.

Usage:

    class MyDialog(AssetDialog):
        def __init__(self):
            super().__init__("My Title")
            self.name_field = self.add_line("Name")
            self.finish()                 # adds OK/Cancel + lays out
        def _on_accept(self):
            self.name = self.name_field.text().strip()
            super()._on_accept()          # sets canceled=False, accepts

    dlg = MyDialog()
    dlg.exec_()
    if not dlg.canceled:
        ...
"""

from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from amaze.helpers import theme


class AssetDialog(QtWidgets.QDialog):
    """Base modal form dialog in the house style.

    `canceled` is True until the user accepts; subclasses read their
    fields in `_on_accept()` and call super()._on_accept()."""

    def __init__(self, title: str = "", fixed_size: bool = True) -> None:
        super().__init__()
        self.canceled = True
        self._fixed_size = fixed_size
        if title:
            self.setWindowTitle(title)

        self._form = QtWidgets.QFormLayout()
        # The house convention: label column right-aligned, field right -
        # the same rule the details view and Preferences use.
        self._form.setLabelAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight
            | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        self._form.setFieldGrowthPolicy(
            QtWidgets.QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )
        self._buttons = None

    # -- row helpers ------------------------------------------------------

    def add_row(self, label, widget):
        """Add a labelled row; returns the widget for wiring."""
        self._form.addRow(label, widget)
        return widget

    def add_line(self, label: str, default: str = "", width: int = 280):
        field = QtWidgets.QLineEdit(default)
        field.setMinimumWidth(theme.ui_px(width))
        return self.add_row(label, field)

    def add_combo(
        self, label: str, items, current: str = "", editable: bool = False
    ):
        combo = QtWidgets.QComboBox()
        combo.setEditable(editable)
        for item in items:
            combo.addItem(item)
        if current:
            combo.setCurrentText(current)
        return self.add_row(label, combo)

    # -- assembly ---------------------------------------------------------

    def finish(self, ok_cancel: bool = True) -> None:
        """Add the OK/Cancel button row and lay the dialog out. Call once,
        after all rows are added."""
        if ok_cancel:
            self._buttons = QtWidgets.QDialogButtonBox(
                QtWidgets.QDialogButtonBox.StandardButton.Ok
                | QtWidgets.QDialogButtonBox.StandardButton.Cancel
            )
            self._buttons.accepted.connect(self._on_accept)
            self._buttons.rejected.connect(self.reject)
            self._form.addRow(self._buttons)

        layout = QtWidgets.QVBoxLayout()
        layout.addLayout(self._form)
        _m = theme.ui_px(5)
        layout.setContentsMargins(_m, _m, _m, _m)
        if self._fixed_size:
            layout.setSizeConstraint(
                QtWidgets.QLayout.SizeConstraint.SetFixedSize
            )
        self.setLayout(layout)

    def _on_accept(self) -> None:
        """Override to read fields, then call super()._on_accept()."""
        self.canceled = False
        self.accept()


class NameDialog(AssetDialog):
    """One text field and a title - the house replacement for
    `hou.ui.readInput`, whose native dialog carries an unwanted "i" icon
    and separator lines.

    `CategoryDialog` was this, in `gradient_dialog`, with one caller.
    It lives here so a second caller does not have to import the Colors
    section's dialogs to ask for a name.
    """

    def __init__(self, title: str = "Name", default: str = "") -> None:
        super().__init__(title)
        self.name = ""
        self._line_name = self.add_line("Name", default)
        self.finish()

    def _on_accept(self) -> None:
        self.name = self._line_name.text().strip()
        super()._on_accept()
