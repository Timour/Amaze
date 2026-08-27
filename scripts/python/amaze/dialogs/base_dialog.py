"""AssetDialog - the shared shell for every Amaze dialog: the house style (right-aligned QFormLayout labels, 5px content margins, an OK/Cancel row, a content-hugging fixed size) plus the `canceled`/accept contract, so dialogs look and cancel identically by construction. A form dialog is a few `add_*` calls then `finish()`; a one-off body is `set_content(widget)` then `finish()`; either way subclasses read their fields in `_on_accept()` and call `super()._on_accept()`, and callers run `exec_()` and check `canceled`. See docs/architecture/overview.md - the Dialog concept - and NameDialog below for the smallest complete rider."""

from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from amaze import amazetheme
from amaze.helpers import theme, ui_helpers

SAVE_WIDTH = amazetheme.SAVE_WIDTH    # every small save dialog is this wide, whatever its labels ▸p/save-dialog-rows


class AssetDialog(QtWidgets.QDialog):
    """Base modal form dialog in the house style. - `canceled` is True until the user accepts; subclasses read their fields in `_on_accept()` and call super()._on_accept()."""

    FORM_WIDTH = None    # a shared width in logical px, or None to hug the content; the save family sets one so siblings match ▸p/save-dialog-rows
    FIELD_WIDTH = None   # the drawn field width; every row built through `add_*` takes it EXACTLY, so a dialog with fewer rows cannot end up with wider fields than its siblings ▸p/save-dialog-rows
    HEADER_BAND = False  # the drawn header strip carrying the asset's name - D01, D02 and D11 wear one, the save family and Preferences do not ▸p/one-design-document

    def __init__(self, title: str = "", fixed_size: bool = True,
                 parent=None) -> None:
        super().__init__(parent)
        self.canceled = True
        self._fixed_size = fixed_size
        if title:
            self.setWindowTitle(title)

        self._form = QtWidgets.QFormLayout()
        self._form.setLabelAlignment(   # the house convention: label column right-aligned, field right - the same rule the details view and Preferences use

            QtCore.Qt.AlignmentFlag.AlignRight
            | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        self._form.setFieldGrowthPolicy(
            QtWidgets.QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )
        self._buttons = None
        self._content = None

    def header_band_text(self) -> str:
        """What the drawn band says - the window title by default, since for most dialogs that already IS the asset's name. A dialog whose title is a verb rather than a name overrides this. ▸p/one-design-document"""
        return self.windowTitle()

    def add_row(self, label, widget):
        """Add a labelled row; returns the widget for wiring. A dialog declaring `FIELD_WIDTH` gets it EXACTLY here, so the label column absorbs the slack and siblings with different labels still draw the same field. ▸p/save-dialog-rows"""
        if self.FIELD_WIDTH:
            widget.setFixedWidth(theme.ui_px(self.FIELD_WIDTH))
        self._form.addRow(label, widget)
        return widget

    def add_line(self, label: str, default: str = "", width: int = 0):
        field = QtWidgets.QLineEdit(default)
        if width:
            field.setMinimumWidth(theme.ui_px(width))    # an explicit override; the shared width comes from `FIELD_WIDTH` through `add_row`
        return self.add_row(label, field)

    def add_combo(
        self, label: str, items, current: str = "", editable: bool = False
    ):
        combo = ui_helpers.DesignedComboBox()    # its dropdown holds the box's width ▸r/combo-popup-width
        combo.setEditable(editable)
        for item in items:
            combo.addItem(item)
        if current:
            combo.setCurrentText(current)
        return self.add_row(label, combo)

    def set_content(self, widget) -> None:
        """Adopt a prebuilt central widget in place of form rows - the shell (title, house margins, `canceled`/accept, the optional OK/Cancel strip, the sizing rule) stays the base's while the guts stay the dialog's; the four one-off dialogs hand-copied exactly this shell before ROADMAP R51 moved them onto it."""
        self._content = widget

    def finish(self, ok_cancel: bool = True, margins: int | None = None) -> None:
        """Add the OK/Cancel button row and lay the dialog out - call once, after all rows are added (or after `set_content`). `margins` is the house 5px unless a dialog records its reason to differ at the call."""
        if ok_cancel:
            self._buttons = QtWidgets.QDialogButtonBox(
                QtWidgets.QDialogButtonBox.StandardButton.Ok
                | QtWidgets.QDialogButtonBox.StandardButton.Cancel
            )
            self._buttons.accepted.connect(self._on_accept)
            self._buttons.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout()
        self._inner_layout = layout    # the margined content layout, for a dialog whose drawn margins are per-side
        if self._content is not None:
            if self._form.rowCount():
                raise RuntimeError(
                    "AssetDialog.finish: %d add_* row(s) would be lost - "
                    "a dialog uses form rows OR set_content, never both"
                    % self._form.rowCount())
            layout.addWidget(self._content)
            if self._buttons is not None:
                layout.addWidget(self._buttons)
        else:
            if self._buttons is not None:
                self._form.addRow(self._buttons)
            layout.addLayout(self._form)
        _m = theme.ui_px(5 if margins is None else margins)
        layout.setContentsMargins(_m, _m, _m, _m)
        if self.FORM_WIDTH:
            layout.addStrut(theme.ui_px(self.FORM_WIDTH) - 2 * _m)    # THE LAYOUT'S OWN HINT, never `setFixedWidth`: under `SetFixedSize` the hint IS the width and is re-imposed on every activation, so a hand-set width dies at `show()` ▸r/fixed-size-constraint
        if not self.HEADER_BAND:
            if self._fixed_size:
                layout.setSizeConstraint(
                    QtWidgets.QLayout.SizeConstraint.SetFixedSize)
            self.setLayout(layout)
            return

        from amaze.helpers import ui_helpers    # HERE, not at module scope: `ui_helpers` is the widget library and importing it at the top makes the shell depend on it for every dialog, band or no band
        band_text = self.header_band_text()
        outer = QtWidgets.QVBoxLayout()    # the band is FULL WIDTH, so the house margins move inside it rather than around it
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(ui_helpers.header_band(self, band_text))
        outer.addLayout(layout)
        if self._fixed_size:
            outer.setSizeConstraint(
                QtWidgets.QLayout.SizeConstraint.SetFixedSize)
        self.setLayout(outer)

    def _on_accept(self) -> None:
        """Override to read fields, then call super()._on_accept()."""
        self.canceled = False
        self.accept()


class NameDialog(AssetDialog):
    """One text field and a title - the house replacement for `hou.ui.readInput`, whose native dialog carries an unwanted "i" icon and separator lines. - `CategoryDialog` was this, in `gradient_dialog`, with one caller. It lives here so a second caller does not have to import the Colors section's dialogs to ask for a name."""

    FORM_WIDTH = SAVE_WIDTH
    FIELD_WIDTH = amazetheme.SAVE_FIELD_WIDTH

    def __init__(self, title: str = "Name", default: str = "",
                 parent=None) -> None:
        super().__init__(title, parent=parent)
        self.name = ""
        self._line_name = self.add_line("Name", default)
        self.finish()

    def _on_accept(self) -> None:
        self.name = self._line_name.text().strip()
        super()._on_accept()
