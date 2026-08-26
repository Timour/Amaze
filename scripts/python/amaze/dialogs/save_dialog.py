"""The material/COP save dialog - category, tags and (for COP saves) a name, built from the house form rows so it shares the shell and the drawn width. ▸p/save-dialog-rows"""

from PySide6 import QtWidgets

from amaze import branding
from amaze.dialogs import base_dialog
from amaze.helpers import theme, ui_helpers


class SaveDialog(base_dialog.AssetDialog):

    FORM_WIDTH = base_dialog.SAVE_WIDTH
    FIELD_WIDTH = 276    # the drawn field width ▸p/save-dialog-rows

    def __init__(
        self,
        cat_list: list[str],
        default_cat: str = "",
        name: str | None = None,
        parent=None,
    ) -> None:
        """`name`: when given, an editable Name row is built ABOVE Category, prefilled - COP saves pick category and name, while materials pass nothing and keep node-derived naming, since one field cannot serve their multi-selection saves. `default_cat` pre-selects the category active in the panel."""
        super().__init__("Save to " + branding.APP_NAME, parent=parent)

        self.categories = ""
        self.tags = ""
        self.fav = False    # there is no Favorite row: the attribute stays because the COP save reads it, and it was already always False ▸p/save-dialog-rows
        self.name = name or ""

        self.line_name = None
        if name is not None:
            self.line_name = self.add_line("Name", name,
                                           width=self.FIELD_WIDTH)
            self.line_name.setToolTip(ui_helpers.tooltip_text(
                "Name it, pick a category, and add tags to find "
                "it again later."))

        self.combo_cats = self.add_combo("Category", cat_list, default_cat)
        self.combo_cats.setInsertPolicy(
            QtWidgets.QComboBox.InsertPolicy.InsertAtTop)
        self.combo_cats.setMinimumWidth(theme.ui_px(self.FIELD_WIDTH))

        self.line_tags = self.add_line("Tags", width=self.FIELD_WIDTH)
        self.finish()

    def _on_accept(self) -> None:
        self.categories = self.combo_cats.currentText()
        self.tags = self.line_tags.text()
        if self.line_name is not None:
            self.name = self.line_name.text().strip()
        super()._on_accept()
