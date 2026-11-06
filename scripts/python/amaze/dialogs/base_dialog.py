"""AssetDialog, the shared dialog shell: `add_*` rows or `set_content`, then `finish()`."""

from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from amaze import amazetheme
from amaze.core import category
from amaze.helpers import theme, ui_helpers

SAVE_WIDTH = amazetheme.SAVE_WIDTH    # every small save dialog is this wide, whatever its labels ▸p/save-dialog-rows


def fill_categories(combo, stored_names, current: str = "",
                    blank: bool = False) -> None:
    """Rows LABELLED as the sidebar shows them, each carrying its STORED name; `current` selected."""
    combo.clear()
    for name in stored_names:
        combo.addItem(category.display_name(name), name)
    row = combo.findData(current) if current else -1
    if row >= 0:
        combo.setCurrentIndex(row)
    elif blank:
        combo.insertItem(0, "", "")    # leads and means UNCHANGED: `chosen_category` answers ""
        combo.setCurrentIndex(0)


def chosen_category(combo) -> str:
    """The STORED name behind the row a category combo shows, "" for none."""
    return str(combo.currentData() or "")


class AssetDialog(QtWidgets.QDialog):
    """Base form dialog; `canceled` stays True until accepted, fields are read in `_on_accept()`."""

    FORM_WIDTH = None    # a shared width in logical px, or None to hug the content ▸p/save-dialog-rows
    FIELD_WIDTH = None   # the drawn field width every `add_*` row takes exactly ▸p/save-dialog-rows
    FIELD_HEIGHT = amazetheme.SAVE_FIELD_H   # the field height every `add_*` row takes ▸p/save-dialog-rows
    HEADER_BAND = False  # the drawn strip over the content: only D11 wears one ▸p/one-design-document
    FRAME_KEY = ""       # the drawn frame that sizes every `add_*` row and OK/Cancel ▸p/one-design-document

    def __init__(self, title: str = "", fixed_size: bool = True,
                 parent=None) -> None:
        super().__init__(parent)
        self.canceled = True
        self._fixed_size = fixed_size
        self._rows_built: dict = {}    # each row's widget per kind, in creation order
        if title:
            self.setWindowTitle(title)

        self._form = QtWidgets.QFormLayout()
        self._form.setLabelAlignment(   # the house convention: labels right-aligned

            QtCore.Qt.AlignmentFlag.AlignRight
            | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        self._form.setFieldGrowthPolicy(
            QtWidgets.QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )
        self._buttons = None
        self._content = None

    def header_band_text(self) -> str:
        """What the drawn band says: the window title unless overridden. ▸p/one-design-document"""
        return self.windowTitle()

    def build_header_band(self):
        """The drawn strip over the content; a dialog that draws more in it builds its own."""
        return ui_helpers.header_band(self, self.header_band_text(),
                                      *amazetheme.drawn_band(self.FRAME_KEY))

    def add_row(self, label, widget):
        """Add a labelled row sized by FRAME_KEY or FIELD_WIDTH; returns the widget. ▸p/save-dialog-rows"""
        if self.FRAME_KEY:
            self._rows_built.setdefault(
                ui_helpers.drawn_kind(widget, self.FRAME_KEY),
                []).append(widget)
        elif self.FIELD_WIDTH:
            widget.setFixedWidth(theme.ui_px(self.FIELD_WIDTH))
        if self.FIELD_HEIGHT and not self.FRAME_KEY:
            widget.setFixedHeight(theme.ui_px(self.FIELD_HEIGHT))
        self._form.addRow(label, widget)
        return widget

    def add_line(self, label: str, default: str = ""):
        return self.add_row(label, QtWidgets.QLineEdit(default))

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
        """Adopt a prebuilt central widget in place of form rows; never use both."""
        self._content = widget

    def finish(self, ok_cancel: bool = True, margins: int | tuple | None = None) -> None:
        """Lay out the rows or content and OK/Cancel, once; `margins`: house 5px, an int or (l, t, r, b)."""
        for kind, widgets in self._rows_built.items():
            ui_helpers.pin_drawn_series(widgets, self.FRAME_KEY, kind)
        if ok_cancel:
            self._buttons = QtWidgets.QDialogButtonBox(
                QtWidgets.QDialogButtonBox.StandardButton.Ok
                | QtWidgets.QDialogButtonBox.StandardButton.Cancel
            )
            self._buttons.accepted.connect(self._on_accept)
            self._buttons.rejected.connect(self.reject)
            self._pin_button_row()

        layout = QtWidgets.QVBoxLayout()
        self._inner_layout = layout    # the margined content layout, for a dialog whose drawn margins are per-side
        form = (amazetheme.drawn_form(self.FRAME_KEY)
                if self.FRAME_KEY and self._content is None
                and not self.HEADER_BAND else {})
        if self._content is not None:
            if self._form.rowCount():
                raise RuntimeError(
                    "AssetDialog.finish: %d add_* row(s) would be lost - "
                    "a dialog uses form rows OR set_content, never both"
                    % self._form.rowCount())
            layout.addWidget(self._content)
            if self._buttons is not None:
                layout.addWidget(self._buttons)
        elif form:    # every margin and gap is the frame's ▸p/save-dialog-rows
            self._form.setHorizontalSpacing(theme.ui_px(form["label_gap"]))
            self._form.setVerticalSpacing(theme.ui_px(form["row_gap"]))
            layout.setSpacing(0)
            layout.addLayout(self._form)
            if self._buttons is not None:
                layout.addSpacing(theme.ui_px(form["button_gap"]))
                layout.addWidget(self._buttons)
        else:
            if self._buttons is not None:
                self._form.addRow(self._buttons)
            layout.addLayout(self._form)
        if form:
            sides = [theme.ui_px(form[k]) for k in ("left", "top", "right", "bottom")]
        elif isinstance(margins, tuple):
            sides = [theme.ui_px(side) for side in margins]
        else:
            sides = [theme.ui_px(amazetheme.HOUSE_MARGIN if margins is None else margins)] * 4
        layout.setContentsMargins(*sides)
        if self.FORM_WIDTH:
            layout.addStrut(theme.ui_px(self.FORM_WIDTH) - sides[0] - sides[2])    # ▸r/fixed-size-constraint
        if not self.HEADER_BAND:
            if self._fixed_size:
                layout.setSizeConstraint(
                    QtWidgets.QLayout.SizeConstraint.SetFixedSize)
            self.setLayout(layout)
            self._pin_label_column(sides[0] + sides[2])
            return

        outer = QtWidgets.QVBoxLayout()    # the band is FULL WIDTH, so the house margins move inside it rather than around it
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self.build_header_band())
        outer.addLayout(layout)
        if self._fixed_size:
            outer.setSizeConstraint(
                QtWidgets.QLayout.SizeConstraint.SetFixedSize)
        self.setLayout(outer)
        self._pin_label_column(sides[0] + sides[2])

    def _pin_button_row(self) -> None:
        """Pin OK/Cancel to the drawn sizes, gap and order, OK first. ▸p/one-design-document"""
        box = self._buttons
        ok = box.button(QtWidgets.QDialogButtonBox.StandardButton.Ok)
        cancel = box.button(QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        height = theme.ui_px(amazetheme.SAVE_BUTTON_H)
        for button, label, width in ((ok, "OK", amazetheme.SAVE_BUTTON_W[0]),
                                     (cancel, "Cancel",
                                      amazetheme.SAVE_BUTTON_W[1])):
            if button is None:
                continue
            if self.FRAME_KEY:
                ui_helpers.pin_drawn(button, self.FRAME_KEY, "QPushButton",
                                     label)
            else:
                button.setFixedSize(theme.ui_px(width), height)
        row = box.layout()
        row.setContentsMargins(0, 0, 0, 0)
        gap = amazetheme.drawn_pair_gap(self.FRAME_KEY) if self.FRAME_KEY else None
        row.setSpacing(theme.ui_px(amazetheme.SAVE_BUTTON_GAP if gap is None else gap))
        if ok is None or cancel is None:
            return
        built = [row.itemAt(i).widget() for i in range(row.count())]
        if [w for w in built if w is not None][:1] != [ok]:   # a macOS or GNOME button layout draws Cancel first; no frame does
            while row.count():
                row.takeAt(0)
            row.addStretch(1)      # the pair is drawn flush RIGHT, level with the fields above it
            row.addWidget(ok)
            row.addWidget(cancel)

    def drawn_pair(self, primary_label: str, on_primary):
        """The frame's primary button and Cancel, flush right at their drawn sizes: (primary, cancel, row)."""
        primary = QtWidgets.QPushButton(primary_label)
        cancel = QtWidgets.QPushButton(amazetheme.BTN_CANCEL)
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.ui_px(amazetheme.drawn_pair_gap(self.FRAME_KEY)))
        row.addStretch(1)
        for button in (primary, cancel):
            ui_helpers.pin_drawn(button, self.FRAME_KEY, "QPushButton", button.text())
            button.setAutoDefault(False)    # Enter goes to the button a dialog makes default, or none
            row.addWidget(button)
        primary.clicked.connect(on_primary)
        cancel.clicked.connect(self.reject)
        return primary, cancel, row

    def _pin_label_column(self, sides: int) -> None:
        """Pin every label to the width left over; call it after setLayout. ▸p/save-dialog-rows"""
        if not (self.FORM_WIDTH and self.FIELD_WIDTH):
            return
        slack = (theme.ui_px(self.FORM_WIDTH) - sides
                 - self._form.horizontalSpacing()
                 - theme.ui_px(self.FIELD_WIDTH))
        if slack <= 0:
            return
        for row in range(self._form.rowCount()):
            item = self._form.itemAt(
                row, QtWidgets.QFormLayout.ItemRole.LabelRole)
            if item is not None and item.widget() is not None:
                item.widget().setFixedWidth(slack)

    def _on_accept(self) -> None:
        """Override to read fields, then call super()._on_accept()."""
        self.canceled = False
        self.accept()

    def exec(self) -> int:
        """Run modally, then `deleteLater`; read the answers `_on_accept` stored. ▸r/deferred-delete"""
        try:
            return super().exec()
        finally:
            self.deleteLater()


class NameDialog(AssetDialog):
    """One text field and a title, in place of `hou.ui.readInput`; the answer is `name`."""

    FORM_WIDTH = SAVE_WIDTH
    FIELD_WIDTH = amazetheme.NAME_FIELD_WIDTH
    FRAME_KEY = "D13"

    def __init__(self, title: str = "Name", default: str = "",
                 parent=None) -> None:
        super().__init__(title, parent=parent)
        self.name = ""
        self._line_name = self.add_line("Name", default)
        self.finish()

    def _on_accept(self) -> None:
        self.name = self._line_name.text().strip()
        super()._on_accept()
