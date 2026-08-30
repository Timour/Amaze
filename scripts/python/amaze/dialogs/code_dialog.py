"""Save/edit dialog for the Code section. Name + Language + editable Category + Tags + a code editor styled like Houdini's wrangle VEXpression field (black background, line-number gutter, the shared VEX syntax colours). Used for New Snippet (empty), Edit (prefilled), and Save from Node (code + language prefilled)."""

from PySide6 import QtWidgets, QtGui, QtCore

from amaze.helpers import theme
from amaze.helpers import ui_helpers

from amaze import amazetheme
from amaze import branding
from amaze import messages
from amaze import tooltips
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

    GUTTER_BG = QtGui.QColor(amazetheme.GUTTER_BG)
    GUTTER_FG = QtGui.QColor(amazetheme.GUTTER_FG)
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

    FORM_WIDTH = amazetheme.D11_FORM_WIDTH
    HEADER_BAND = True    # D11 wears the drawn name strip ▸p/one-design-document

    def header_band_text(self) -> str:
        """The SNIPPET's name, not the window title, which here is a verb - and `Untitled` while it has none, the programming world's own word for it."""
        return self._line_name.text().strip() or amazetheme.BAND_UNTITLED

    def __init__(
        self,
        categories: list,
        name: str = "",
        language: str = "VEX",
        category: str = "",
        tags: str = "",
        code: str = "",
        title: str = "Save Code to " + branding.APP_NAME,
        parent=None,
    ) -> None:
        super().__init__(title, fixed_size=False, parent=parent)    # the ONE resizable dialog; `FORM_WIDTH` is a floor here rather than a pin, because no `SetFixedSize` constraint follows ▸p/one-design-document
        self.name = ""
        self.language = ""
        self.category = ""
        self.tags = ""
        self.code = ""

        def form():
            half = QtWidgets.QFormLayout()
            half.setContentsMargins(0, 0, 0, 0)
            half.setHorizontalSpacing(theme.ui_px(amazetheme.D11_LABEL_GAP))
            half.setVerticalSpacing(theme.ui_px(amazetheme.D11_ROW_GAP))
            half.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight
                                   | QtCore.Qt.AlignmentFlag.AlignVCenter)
            half.setFieldGrowthPolicy(    # AllNonFixed, so the combos fill their half exactly as the line edits do - all four fields are drawn equal ▸r/form-layout-defaults
                QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            return half

        left, right = form(), form()    # Name | Category over Language | Tags - the drawn 2x2, equal halves

        self._line_name = QtWidgets.QLineEdit(name)
        self._line_name.setToolTip(ui_helpers.tooltip_text(tooltips.CODE_NAME))
        left.addRow("Name", self._line_name)

        self._combo_lang = ui_helpers.DesignedComboBox()    # its dropdown holds the box's width ▸r/combo-popup-width
        for lang in LANGUAGES:
            self._combo_lang.addItem(lang)
        if language in LANGUAGES:
            self._combo_lang.setCurrentText(language)
        left.addRow("Language", self._combo_lang)

        self._combo_category = ui_helpers.DesignedComboBox()   # a PLAIN dropdown like Language beside it (the design's rule since 2026-08-30) - the sidebar's Add Category mints new ones
        for item in categories:
            self._combo_category.addItem(item)
        self._combo_category.setCurrentText(
            category or (categories[0] if categories else ""))
        right.addRow("Category", self._combo_category)

        self._line_tags = QtWidgets.QLineEdit(tags)
        right.addRow("Tags", self._line_tags)

        content = QtWidgets.QWidget()
        stack = QtWidgets.QVBoxLayout(content)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(theme.ui_px(amazetheme.D11_STACK_GAP))
        halves = QtWidgets.QHBoxLayout()
        halves.setSpacing(theme.ui_px(amazetheme.D11_HALF_GAP))
        halves.addLayout(left, 1)
        halves.addLayout(right, 1)
        stack.addLayout(halves)

        self._editor = CodeEditor(code)
        self._editor.setMinimumHeight(theme.ui_px(amazetheme.D11_EDITOR_H))
        stack.addWidget(self._editor, 1)    # FULL width, under both halves - as drawn

        self.set_content(content)
        margins = amazetheme.D11_MARGINS
        self.finish(margins=(margins[0] + margins[2]) // 2)   # the strut needs the drawn CONTENT width; the real, asymmetric margins land below
        self._inner_layout.setContentsMargins(
            *(theme.ui_px(m) for m in margins))
        self._inner_layout.setSpacing(theme.ui_px(amazetheme.D11_BUTTON_GAP))
        field_h = theme.ui_px(amazetheme.D11_FIELD_H)
        for widget in (self._line_name, self._combo_lang,
                       self._combo_category, self._line_tags):
            widget.setFixedHeight(field_h)
        for button in self._buttons.buttons():    # the box's own padding and gap are style defaults otherwise, and the drawing pins both
            button.setFixedHeight(field_h)
        self._buttons.layout().setContentsMargins(0, 0, 0, 0)
        self._buttons.layout().setSpacing(
            theme.ui_px(amazetheme.D11_BUTTON_GAP))

    def _on_accept(self) -> None:
        self.name = self._line_name.text().strip()
        self.language = self._combo_lang.currentText().strip()
        self.category = self._combo_category.currentText().strip()
        self.tags = self._line_tags.text().strip()
        self.code = self._editor.toPlainText()
        if not self.code.strip():
            QtWidgets.QMessageBox.warning(
                self, messages.TITLE_EMPTY_SNIPPET, messages.SNIPPET_HAS_NO_CODE
            )
            return
        super()._on_accept()
