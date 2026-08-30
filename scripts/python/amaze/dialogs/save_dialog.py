"""The save dialog every section saves through - name, category and tags, built from the house form rows so it shares the shell and the drawn width. ▸p/save-dialog-rows"""

from PySide6 import QtWidgets

from amaze import amazetheme
from amaze import branding
from amaze.dialogs import base_dialog
from amaze.helpers import theme, ui_helpers


class SaveDialog(base_dialog.AssetDialog):

    FORM_WIDTH = base_dialog.SAVE_WIDTH
    FIELD_WIDTH = amazetheme.SAVE_FIELD_WIDTH    # the drawn field width ▸p/save-dialog-rows

    def __init__(
        self,
        cat_list: list[str],
        default_cat: str = "",
        name: str | None = None,
        name_enabled: bool = True,
        title: str | None = None,
        parent=None,
    ) -> None:
        """`name` prefills the Name row; `name_enabled=False` greys it, which is the multi-selection save - one field cannot name several assets, so each keeps its node-derived name. `default_cat` pre-selects the category active in the panel, and `title` overrides the house one."""
        super().__init__(title or ("Save to " + branding.APP_NAME),
                         parent=parent)

        self.categories = ""
        self.tags = ""
        self.fav = False    # there is no Favorite row: the attribute stays because the COP save reads it, and it was already always False ▸p/save-dialog-rows
        self.name = name or ""

        self.line_name = self.add_line("Name", self.name,
                                       width=self.FIELD_WIDTH)
        self.line_name.setEnabled(name_enabled)
        self.line_name.setToolTip(ui_helpers.tooltip_text(
            "Name it, pick a category, and add tags to find "
            "it again later."))

        self.combo_cats = self.add_combo("Category", cat_list, default_cat)   # a PLAIN dropdown (the design's rule since 2026-08-30): new categories are minted at the sidebar's Add Category door, never typed here
        self.combo_cats.setInsertPolicy(
            QtWidgets.QComboBox.InsertPolicy.InsertAtTop)
        self.combo_cats.setMinimumWidth(theme.ui_px(self.FIELD_WIDTH))

        self.line_tags = self.add_line("Tags", width=self.FIELD_WIDTH)
        self.finish()

    def _on_accept(self) -> None:
        self.categories = self.combo_cats.currentText()
        self.tags = self.line_tags.text()
        if self.line_name.isEnabled():    # a greyed field's text is nobody's answer
            self.name = self.line_name.text().strip()
        super()._on_accept()
