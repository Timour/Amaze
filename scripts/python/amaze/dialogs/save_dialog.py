"""The material/COP save dialog - category, tags and (for COP saves) a name, its rows loaded from `ui/material_dialog.ui`, the shell inherited from the house base."""

from PySide6 import QtWidgets, QtCore

import amaze
from amaze import branding
from amaze.dialogs import base_dialog
from amaze.helpers import theme, ui_helpers


class SaveDialog(base_dialog.AssetDialog):

    def __init__(
        self,
        cat_list: list[str],
        default_cat: str = "",
        name: str | None = None,
        parent=None,
    ) -> None:
        """`name`: when given, an editable Name row is built above Category, prefilled (COP saves pick category AND name; materials pass nothing and keep node-derived naming, since one field cannot serve their multi-selection saves). `default_cat` pre-selects the category active in the panel. The .ui's root is a full QMainWindow embedded as a plain widget - its 350x200 minimum and status bar are neutralized at runtime so the shell's fixed size hugs the content; the Favorite row is removed while `cb_fav` stays alive unchecked, so `fav` is always False here; the tags field's minimum width is what keeps the content-hugging dialog from coming out cramped; and the button box lives INSIDE the .ui, so the shell adds none and it is wired to the base accept instead of a local copy."""
        super().__init__("Save to " + branding.APP_NAME, parent=parent)
        self.script_path = amaze.PACKAGE_ROOT   # the package locates its own bundled files ONE way

        self.categories = ""
        self.tags = ""
        self.fav = False
        self.name = name or ""

        self.ui = ui_helpers.load_ui(
            self.script_path + "/ui/material_dialog.ui")

        self.ui.setMinimumSize(0, 0)
        statusbar = self.ui.findChild(QtWidgets.QStatusBar)
        if statusbar is not None:
            statusbar.setVisible(False)

        fav_label = self.ui.findChild(QtWidgets.QLabel, "label_3")
        if fav_label is not None:
            fav_label.setVisible(False)
        fav_row = self.ui.findChild(QtWidgets.QHBoxLayout, "horizontalLayout_3")
        parent_layout = self.ui.findChild(QtWidgets.QVBoxLayout, "verticalLayout_2")
        if fav_row is not None and parent_layout is not None:
            parent_layout.removeItem(fav_row)

        self.line_name = None
        if name is not None and parent_layout is not None:
            self.line_name = QtWidgets.QLineEdit()
            self.line_name.setToolTip(ui_helpers.tooltip_text(
                "Name it, pick a category, and add tags to find "
                "it again later."))
            self.line_name.setText(name)
            name_row = QtWidgets.QHBoxLayout()
            name_row.addWidget(QtWidgets.QLabel("Name"))
            name_row.addWidget(self.line_name)
            parent_layout.insertLayout(0, name_row)

        self.combo_cats = self.ui.findChild(QtWidgets.QComboBox, "combo_categories")
        for cat in cat_list:
            self.combo_cats.addItem(cat)
        self.combo_cats.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.InsertAtTop)

        if default_cat:
            default_index = self.combo_cats.findText(default_cat)
            if default_index >= 0:
                self.combo_cats.setCurrentIndex(default_index)

        self.line_tags = self.ui.findChild(QtWidgets.QLineEdit, "line_tags")
        self.line_tags.setMinimumWidth(theme.ui_px(280))
        self.cb_fav = self.ui.findChild(QtWidgets.QCheckBox, "cb_fav")
        self.cb_fav.setVisible(False)

        self.buttons = self.ui.findChild(QtWidgets.QDialogButtonBox, "buttonBox")
        self.buttons.accepted.connect(self._on_accept)
        self.buttons.rejected.connect(self.reject)

        self.set_content(self.ui)
        self.finish(ok_cancel=False)

    def _on_accept(self) -> None:
        self.categories = self.combo_cats.currentText()
        self.tags = self.line_tags.text()
        self.fav = self.cb_fav.isChecked()
        if self.line_name is not None:
            self.name = self.line_name.text().strip()
        super()._on_accept()
