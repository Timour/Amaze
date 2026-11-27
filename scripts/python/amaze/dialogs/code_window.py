"""The code window: a snippet's name, language, category, tags and code; each Apply saves it."""

from PySide6 import QtCore
import hou

import amaze
from amaze import amazetheme, branding, messages, tooltips
from amaze.core import code_library
from amaze.pane import asks
from amaze.qml import dialog_window

CODE_QML = amaze.package_file("ui", "dialogs", "CodeWindow.qml")
HIGHLIGHTERS = {"VEX": "vex", "Python": "python"}    # the languages Houdini's code fields colour


class CodeState(dialog_window.DialogState):
    """What the code window shows for a CodeQuestion; it refuses to save a snippet with no code."""

    categories: list = []    # the snippet section's categories, as {text, value: its key}
    categoryRow: int = -1
    languages: list = list(code_library.LANGUAGES)
    languageRow: int = 0
    highlighter: str = ""    # Houdini's colours for the language the snippet opened with
    codeGround: str = ""    # Houdini's own code field ground, "" where no Houdini window gives one
    nameTip: str = tooltips.SAVE_NAME
    applyText: str = amazetheme.BTN_APPLY

    def __init__(self, question, **kwargs) -> None:
        super().__init__(question={"name": question.name or "", "tags": question.tags or "",
                                   "code": question.code or ""}, **kwargs)
        self.categories, self.categoryRow = dialog_window.menu_rows(question.categories, question.category)
        language = question.language if question.language in self.languages else self.languages[0]
        self.languageRow = self.languages.index(language)
        self.highlighter = HIGHLIGHTERS.get(language, "")
        ui = getattr(hou, "ui", None)
        if ui is not None:
            self.codeGround = hou.qt.toQColor(ui.colorFromName("TextboxBG")).name()

    def refused(self, answer) -> bool:
        """A snippet with no code is not saved, and the user is told."""
        if str(answer.get("code") or "").strip():
            return False
        ui = getattr(hou, "ui", None)
        if ui is not None:
            ui.displayMessage(messages.SNIPPET_HAS_NO_CODE, title=messages.TITLE_EMPTY_SNIPPET,
                              severity=hou.severityType.Warning)
        return True


class CodeWindow(dialog_window.DialogWindow):
    """The code window: the four fields over Houdini's code field, then Apply and Cancel."""

    STATE = CodeState
    SOURCE_URL = QtCore.QUrl.fromLocalFile(CODE_QML).toString()
    DEFAULT_SIZE = QtCore.QSize(*amazetheme.DIALOG_LAYOUT["D11"]["frame"])    # D11, which it grows from
    MINIMUM_SIZE = DEFAULT_SIZE

    def setupEngine(self) -> None:
        """Houdini's code colours and line counts for the QML, as its Create Asset window loads them."""
        super().setupEngine()
        from hutil.qt.editors import syntax    # noqa: F401  needs Houdini's UI: it is read as the window opens


def ask(owner, question, apply) -> CodeWindow:
    """The code window for a CodeQuestion: each Apply calls `apply(CodeAnswer)`; a close calls nothing."""
    def applied(fields):
        if fields is not None:
            apply(asks.CodeAnswer(code=str(fields["code"]), name=str(fields["name"]).strip(),
                                  language=str(fields["language"]).strip(), category=str(fields["category"]),
                                  tags=str(fields["tags"]).strip()))
    return CodeWindow.ask(owner, question.title or "Save Code to " + branding.APP_NAME, question, applied)
