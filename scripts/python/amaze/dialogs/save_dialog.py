"""The save dialog every section saves through - name, category and tags, built from the house form rows so it shares the shell and the drawn width. ▸p/save-dialog-rows"""

from PySide6 import QtWidgets

from amaze import amazetheme
from amaze import branding
from amaze import tooltips
from amaze.dialogs import base_dialog
from amaze.dialogs import code_dialog
from amaze.helpers import ui_helpers


class SaveDialog(base_dialog.AssetDialog):

    FORM_WIDTH = base_dialog.SAVE_WIDTH
    FIELD_WIDTH = amazetheme.SAVE_FIELD_WIDTH    # the drawn field width ▸p/save-dialog-rows
    FRAME_KEY = "D09"

    def __init__(
        self,
        cat_list: list[str],
        default_cat: str = "",
        name: str | None = None,
        name_enabled: bool = True,
        title: str | None = None,
        parent=None,
        sections=(),
        section: str = "",
        categories_for=None,
        language: str = "",
        language_sections=(),
    ) -> None:
        """`name` prefills the Name row; `name_enabled=False` greys it, which is the multi-selection save - one field cannot name several assets, so each keeps its node-derived name. `default_cat` pre-selects the category active in the panel, and `title` overrides the house one."""
        super().__init__(title or ("Save to " + branding.APP_NAME),
                         parent=parent)

        self.categories = ""
        self.tags = ""
        self.fav = False    # there is no Favorite row: the attribute stays because the COP save reads it, and it was already always False ▸p/save-dialog-rows
        self.name = name or ""
        self.language = ""
        self._section_keys = [key for key, _ in sections]
        self.section = (section if section in self._section_keys
                        else (self._section_keys or [""])[0])
        self._categories_for = categories_for
        self._language_sections = tuple(language_sections)

        self.combo_section = self.add_combo(    # ▸p/save-section-row
            "Section", [label for _, label in sections])
        if self.section:
            self.combo_section.setCurrentIndex(
                self._section_keys.index(self.section))
        self.combo_section.setEnabled(len(self._section_keys) > 1)

        self.line_name = self.add_line("Name", self.name)
        self.line_name.setEnabled(name_enabled)
        self.line_name.setToolTip(ui_helpers.tooltip_text(tooltips.SAVE_NAME))

        self.combo_cats = self.add_combo("Category", ())   # PLAIN: new ones come from the sidebar
        base_dialog.fill_categories(self.combo_cats, cat_list, default_cat)
        self.combo_cats.setInsertPolicy(
            QtWidgets.QComboBox.InsertPolicy.InsertAtTop)

        self.combo_language = self.add_combo(
            "Language", code_dialog.LANGUAGES,
            language if language in code_dialog.LANGUAGES else "")
        self._language_enabled()

        self.line_tags = self.add_line("Tags")
        self.combo_section.currentIndexChanged.connect(self._on_section)
        self.finish()

    def _language_enabled(self) -> None:
        self.combo_language.setEnabled(self.section in self._language_sections)

    def _on_section(self, row: int) -> None:
        """The categories follow the section; the typed name and tags stay."""
        if not 0 <= row < len(self._section_keys):
            return
        self.section = self._section_keys[row]
        self._language_enabled()
        if self._categories_for is None:
            return
        categories, default = self._categories_for(self.section)
        base_dialog.fill_categories(self.combo_cats, categories, default)

    def _on_accept(self) -> None:
        if self.combo_language.isEnabled():
            self.language = self.combo_language.currentText()
        self.categories = base_dialog.chosen_category(self.combo_cats)
        self.tags = self.line_tags.text()
        if self.line_name.isEnabled():    # a greyed field's text is nobody's answer
            self.name = self.line_name.text().strip()
        super()._on_accept()
