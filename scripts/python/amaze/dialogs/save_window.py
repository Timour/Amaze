"""Save to Amaze as a dialog window: a scene node's section, name, category, language and tags."""

from PySide6 import QtCore

import amaze
from amaze import amazetheme, branding, tooltips
from amaze.dialogs import code_dialog
from amaze.pane import asks
from amaze.qml import dialog_window

SAVE_QML = amaze.package_file("ui", "dialogs", "SaveWindow.qml")


class SaveState(dialog_window.DialogState):
    """What the Save window shows for a SaveQuestion; the categories follow the section picked."""

    sections: list = []    # the sections that can take the save, as {text, value: its key}
    section: str = ""    # the picked section's key
    sectionRow: int = 0
    categories: list = []    # the picked section's categories, as {text, value: its key}
    categoryRow: int = -1
    languages: list = list(code_dialog.LANGUAGES)
    languageRow: int = 0
    languageOn: bool = False    # the picked section stores a language
    nameTip: str = tooltips.SAVE_NAME

    def __init__(self, question, **kwargs) -> None:
        super().__init__(question={"name": question.name or "", "nameEnabled": bool(question.name_enabled)},
                         **kwargs)
        self._asked = question
        self._keys = [key for key, _label in question.sections]
        self.sections = [{"text": label, "value": key} for key, label in question.sections]
        self.languageRow = (self.languages.index(question.language)
                            if question.language in self.languages else 0)
        first = question.section if question.section in self._keys else (self._keys or [""])[0]
        self._show_section(first)
        self._show_categories(question.categories, question.current)

    def _show_section(self, key: str) -> None:
        self.section = key
        self.sectionRow = self._keys.index(key) if key in self._keys else 0
        self.languageOn = key in self._asked.language_sections

    def _show_categories(self, choices, current: str) -> None:
        """The (key, name) choices, `current` picked, else the first as a list shows on filling."""
        self.categories, self.categoryRow = dialog_window.menu_rows(choices, current)

    @QtCore.Slot(str)
    def chooseSection(self, key: str) -> None:
        """Another section picked: its categories and language row; the name and tags stay."""
        if key not in self._keys or key == self.section:
            return
        self._show_section(key)
        if self._asked.categories_for is not None:
            self._show_categories(*self._asked.categories_for(key))


class SaveWindow(dialog_window.DialogWindow):
    """Save to Amaze: Section, Name, Category, Language and Tags, then OK and Cancel."""

    STATE = SaveState
    SOURCE_URL = QtCore.QUrl.fromLocalFile(SAVE_QML).toString()
    DEFAULT_SIZE = QtCore.QSize(amazetheme.SAVE_WIDTH, 0)    # D09's width; as tall as its content
    MINIMUM_SIZE = QtCore.QSize(amazetheme.SAVE_WIDTH, 0)


def ask(owner, question, then) -> SaveWindow:
    """The Save window for a SaveQuestion: `then(SaveAnswer)` once on OK, None for Cancel."""
    def answered(fields):
        if fields is None:
            then(None)
            return
        name = str(fields["name"]).strip() if question.name_enabled else (question.name or "")
        then(asks.SaveAnswer(section=fields["section"], name=name, categories=str(fields["category"]),
                             tags=str(fields["tags"]), fav=False, language=str(fields["language"])))
    return SaveWindow.ask(owner, "Save to " + branding.APP_NAME, question, answered)
