"""Save/edit dialog for the Code section. Name + Language + editable Category + Tags + a code editor styled like Houdini's wrangle VEXpression field (black background, line-number gutter, the shared VEX syntax colours). Used for New Snippet (empty), Edit (prefilled), and Save from Node (code + language prefilled)."""

from PySide6 import QtWidgets, QtGui, QtCore

from amaze.helpers import theme
from amaze.helpers import ui_helpers

from amaze import branding
from amaze.dialogs import base_dialog
from amaze.helpers import vex_syntax

LANGUAGES = ("VEX", "OpenCL", "Python", "Code")


class _LineNumberArea(QtWidgets.QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self):
        return QtCore.QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self._editor.line_number_area_paint(event)


class CodeEditor(QtWidgets.QPlainTextEdit):
    """A wrangle-style code editor: black background, monospace, a grey line-number gutter, and the shared VEX syntax highlighter - the standard Qt CodeEditor pattern, coloured to match Houdini."""

    GUTTER_BG = QtGui.QColor("#1a1a1a")
    GUTTER_FG = QtGui.QColor("#7a7a7a")
    BG = vex_syntax.BACKGROUND
    FG = vex_syntax.DEFAULT

    def __init__(self, text="", read_only=False, parent=None):
        super().__init__(parent)
        self.setReadOnly(read_only)
        font = QtGui.QFont("Courier New")
        font.setStyleHint(QtGui.QFont.StyleHint.Monospace)
        font.setPixelSize(theme.ui_px(14))
        self.setFont(font)
        self.setTabStopDistance(
            4 * QtGui.QFontMetricsF(font).horizontalAdvance(" ")
        )
        self.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        self.setStyleSheet(   # black field, light default text, teal-ish selection - the wrangle editor look; scrollbars stay native (no ancestor stylesheet, so no scrollbar-rendering regression)

            "QPlainTextEdit { background-color: %s; color: %s;"
            " border: 1px solid #2b2b2b; selection-background-color:"
            " #264f78; }"
            % (self.BG.name(), self.FG.name())
        )
        self._gutter = _LineNumberArea(self)
        self.blockCountChanged.connect(self._update_gutter_width)
        self.updateRequest.connect(self._update_gutter)
        self._update_gutter_width(0)
        self._highlighter = vex_syntax.VexHighlighter(self.document())
        self.setPlainText(text)

    def line_number_area_width(self) -> int:
        digits = max(2, len(str(max(1, self.blockCount()))))
        return (
            theme.ui_px(12)
            + self.fontMetrics().horizontalAdvance("9") * digits
        )

    def _update_gutter_width(self, _count):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_gutter(self, rect, dy):
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(
                0, rect.y(), self._gutter.width(), rect.height()
            )
        if rect.contains(self.viewport().rect()):
            self._update_gutter_width(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._gutter.setGeometry(
            QtCore.QRect(
                cr.left(), cr.top(), self.line_number_area_width(), cr.height()
            )
        )

    def line_number_area_paint(self, event):
        painter = QtGui.QPainter(self._gutter)
        painter.fillRect(event.rect(), self.GUTTER_BG)
        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = self.blockBoundingGeometry(block).translated(
            self.contentOffset()
        ).top()
        bottom = top + self.blockBoundingRect(block).height()
        painter.setPen(self.GUTTER_FG)
        width = self._gutter.width() - theme.ui_px(6)
        h = self.fontMetrics().height()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.drawText(
                    0, int(top), width, h,
                    QtCore.Qt.AlignmentFlag.AlignRight,
                    str(number + 1),
                )
            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
            number += 1
        painter.end()


class CodeDialog(base_dialog.AssetDialog):
    """The snippet save form on the house shell - resizable, because the editor is the point of the window."""

    def __init__(
        self,
        categories: list,
        name: str = "",
        language: str = "VEX",
        category: str = "",
        tags: str = "",
        code: str = "",
        description: str = "",
        title: str = "Save Code to " + branding.APP_NAME,
        parent=None,
    ) -> None:
        super().__init__(title, fixed_size=False, parent=parent)
        self.name = ""
        self.language = ""
        self.category = ""
        self.tags = ""
        self.code = ""
        self.description = ""

        self._line_name = QtWidgets.QLineEdit(name)
        self._line_name.setToolTip(ui_helpers.tooltip_text(
            "Name it, pick a category, and add tags to find "
            "it again later."))
        self._line_name.setMinimumWidth(theme.ui_px(360))
        self.add_row("Name", self._line_name)

        self._combo_lang = QtWidgets.QComboBox()
        for lang in LANGUAGES:
            self._combo_lang.addItem(lang)
        if language in LANGUAGES:
            self._combo_lang.setCurrentText(language)
        self.add_row("Language", self._combo_lang)

        self._combo_category = self.add_combo(
            "Category", categories,
            current=category or (categories[0] if categories else ""),
            editable=True,
        )

        self._line_tags = self.add_row("Tags", QtWidgets.QLineEdit(tags))

        self._text_desc = QtWidgets.QPlainTextEdit(description)   # shown on hover over the tile - a short note on what the snippet does (the curated starter snippets ship one)
        self._text_desc.setPlaceholderText(
            "Optional - shown on hover (what it does, sliders to add...)"
        )
        self._text_desc.setFixedHeight(theme.ui_px(56))
        self.add_row("Description", self._text_desc)

        self._editor = CodeEditor(code)
        self._editor.setMinimumSize(theme.ui_px(560), theme.ui_px(320))
        self.add_row("Code", self._editor)

        self.finish()

    def _on_accept(self) -> None:
        self.name = self._line_name.text().strip()
        self.language = self._combo_lang.currentText().strip()
        self.category = self._combo_category.currentText().strip()
        self.tags = self._line_tags.text().strip()
        self.description = self._text_desc.toPlainText().strip()
        self.code = self._editor.toPlainText()
        if not self.code.strip():
            QtWidgets.QMessageBox.warning(
                self, "Empty snippet", "There is no code to save."
            )
            return
        super()._on_accept()
