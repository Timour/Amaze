"""The code dialog, D11: New Snippet and Edit. A tab per open version, and a + that lists them."""

import math

from PySide6 import QtWidgets, QtGui, QtCore

import amaze
from amaze import amazetheme
from amaze import branding
from amaze import messages
from amaze import tooltips
from amaze.core import versions as version_store
from amaze.dialogs import base_dialog
from amaze.helpers import theme, ui_helpers, vex_syntax

LANGUAGES = ("VEX", "OpenCL", "Python", "Code")
NO_VERSION = None    # `version` for a snippet that keeps none: Apply saves the snippet itself
NEW_VERSION = 0      # `version` once New Version is picked, until an Apply saves it


def _code_font() -> QtGui.QFont:
    family, px = amazetheme.CODE_FONT
    font = QtGui.QFont(family)
    font.setStyleHint(QtGui.QFont.StyleHint.Monospace)    # where the face is missing: still fixed
    font.setPixelSize(theme.ui_px(px))
    return font


class _LineNumberArea(QtWidgets.QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self):
        return QtCore.QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self._editor.line_number_area_paint(event)


class _VersionTabs(QtWidgets.QWidget):
    """The band's version tabs as drawn: each as wide as its name and its ×, the front one lit."""

    picked = QtCore.Signal(int)    # a tab clicked, by its place in the row
    closed = QtCore.Signal(int)    # a tab's × clicked

    def __init__(self, drawn: dict, parent=None) -> None:
        super().__init__(parent)
        self._drawn = drawn
        self._names, self._front = [], 0
        font = QtGui.QFont(self.font())
        font.setPixelSize(theme.ui_px(amazetheme.HEADER_BAND_TEXT_PX))
        font.setBold(amazetheme.HEADER_BAND_TEXT_BOLD)
        self.setFont(font)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed)

    def sizeHint(self):
        boxes = self.boxes()
        return QtCore.QSize(int(math.ceil(boxes[-1].right())) if boxes else 0,
                            theme.ui_px(self._drawn["tab"][1]))

    def show_tabs(self, names, front: int) -> None:
        self._names = [name or amazetheme.BAND_UNTITLED for name in names]
        self._front = front
        self.updateGeometry()    # the row and the + after it follow the tabs' width
        self.update()

    def names(self) -> list:
        return list(self._names)

    def boxes(self) -> list:
        """Each tab's box: its name and its × wide, up to the drawn maximum, a gap apart."""
        inset, close_w = (theme.ui_px(v) for v in (self._drawn["tab_text"][0],
                                                   self._drawn["tab_close"][0]))
        high, gap = theme.ui_px(self._drawn["tab"][1]), theme.ui_px(self._drawn["tab_gap"])
        widest = theme.ui_px(amazetheme.CODE_TAB_MAX_W)
        metrics = QtGui.QFontMetricsF(self.font())
        boxes, x = [], 0.0
        for name in self._names:
            wide = min(widest, inset + math.ceil(metrics.horizontalAdvance(name)) + close_w)
            boxes.append(QtCore.QRectF(x, 0, wide, high))
            x += wide + gap
        return boxes

    def close_box(self, box) -> QtCore.QRectF:
        wide, high, inset = (theme.ui_px(v) for v in self._drawn["tab_close"])
        return QtCore.QRectF(box.right() - inset - wide, 0, wide, high)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setFont(self.font())
        radius = theme.ui_px(amazetheme.CODE_RADIUS)
        inset, top, high = (theme.ui_px(v) for v in self._drawn["tab_text"])
        close_w = theme.ui_px(self._drawn["tab_close"][0])
        art = ui_helpers.device_pixmap(    # a lone tab cannot close
            amaze.package_file("ui", "icon_tab_close.svg"), close_w, theme.screen_ratio(self),
            opacity=None if len(self._names) > 1 else ui_helpers.DISABLED_OPACITY)
        for index, (box, name) in enumerate(zip(self.boxes(), self._names)):
            painter.save()
            painter.setClipRect(box)
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(QtGui.QColor(amazetheme.CODE_TAB if index == self._front
                                          else amazetheme.CODE_BAND))
            painter.drawRoundedRect(QtCore.QRectF(box.x(), 0, box.width(), box.height() + radius),
                                    radius, radius)    # its lower corners fall below the band
            room = box.width() - inset - close_w
            painter.setPen(QtGui.QColor(amazetheme.CODE_TAB_INK))
            painter.drawText(QtCore.QRectF(box.x() + inset, top, room, high),
                             QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter,
                             painter.fontMetrics().elidedText(
                                 name, QtCore.Qt.TextElideMode.ElideRight, int(room)))
            painter.drawPixmap(self.close_box(box).topLeft(), art)
            painter.restore()
        painter.end()

    def mousePressEvent(self, event):
        point = event.position()
        for index, box in enumerate(self.boxes()):
            if box.contains(point):
                if not self.close_box(box).contains(point):
                    self.picked.emit(index)
                elif len(self._names) > 1:
                    self.closed.emit(index)
                return
        super().mousePressEvent(event)


class CodeEditor(QtWidgets.QPlainTextEdit):
    """The drawn editor: its ground, the line numbers, the current line's band, the shared colours."""

    def __init__(self, text="", read_only=False, parent=None):
        super().__init__(parent)
        self._drawn = amazetheme.drawn_code_dialog()
        self.setReadOnly(read_only)
        font = _code_font()
        self.setFont(font)
        self.setTabStopDistance(4 * QtGui.QFontMetricsF(font).horizontalAdvance(" "))
        self.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.document().setDocumentMargin(0)    # the first line at the top, code at the drawn x
        self.setStyleSheet(
            "QPlainTextEdit { background-color: %s; color: %s; border: none;"
            " border-radius: %dpx; selection-background-color: #264f78; }"
            % (theme.color_hex("surface_low"), vex_syntax.DEFAULT.name(),    # D11's #272727
               theme.ui_px(amazetheme.CODE_RADIUS)))
        self._gutter = _LineNumberArea(self)
        self.blockCountChanged.connect(self._update_gutter_width)
        self.updateRequest.connect(self._update_gutter)
        self.cursorPositionChanged.connect(self._current_line_moved)
        self._update_gutter_width(0)
        self._highlighter = vex_syntax.VexHighlighter(self.document())
        self.setPlainText(text)

    def line_number_area_width(self) -> int:
        """The drawn gutter, wider only once the line numbers outgrow its box."""
        _x, width = self._drawn["gutter"]
        digits = len(str(max(1, self.blockCount())))
        needed = self.fontMetrics().horizontalAdvance("9") * digits
        return theme.ui_px(self._drawn["text_x"]) + max(0, needed - theme.ui_px(width))

    def _update_gutter_width(self, _count):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_gutter(self, rect, dy):
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_gutter_width(0)

    def _current_line_moved(self):
        self.viewport().update()
        self._gutter.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._gutter.setGeometry(
            QtCore.QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))

    def paintEvent(self, event):
        painter = QtGui.QPainter(self.viewport())
        self._paint_current_line(painter, -self.line_number_area_width())
        painter.end()
        super().paintEvent(event)

    def _paint_current_line(self, painter, offset_x: int) -> None:
        """The drawn band under the line the cursor is on, inset at both ends, across the gutter."""
        block = self.textCursor().block()
        if not block.isVisible():
            return
        rect = self.blockBoundingGeometry(block).translated(self.contentOffset())
        left, right, high = (theme.ui_px(v) for v in self._drawn["current_line"])
        radius = theme.ui_px(amazetheme.CODE_RADIUS)
        letters = QtGui.QFontMetricsF(self.font())
        baseline = rect.top() + block.layout().lineAt(0).ascent()
        middle = baseline + (letters.descent() - letters.capHeight()) / 2.0    # cap top to descender
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(theme.color("field"))    # D11's #434343
        painter.drawRoundedRect(QtCore.QRectF(
            left + offset_x, middle - high / 2.0,
            self.width() - left - right, high), radius, radius)

    def line_number_area_paint(self, event):
        painter = QtGui.QPainter(self._gutter)
        self._paint_current_line(painter, 0)
        x = theme.ui_px(self._drawn["gutter"][0])
        painter.setPen(QtGui.QColor(amazetheme.CODE_LINE_NUMBER_INK))
        painter.setFont(self.font())
        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        bottom = top + self.blockBoundingRect(block).height()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.drawText(QtCore.QRectF(x, top, self._gutter.width() - x, bottom - top),
                                 QtCore.Qt.AlignmentFlag.AlignHCenter
                                 | QtCore.Qt.AlignmentFlag.AlignVCenter, str(number + 1))
            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
            number += 1
        painter.end()


class CodeDialog(base_dialog.AssetDialog):
    """D11 on the house shell: version tabs and their + menu, the form, the editor, Apply, Cancel."""

    FORM_WIDTH = amazetheme.D11_FORM_WIDTH
    HEADER_BAND = True    # D11 draws a band that carries the version tabs
    FRAME_KEY = "D11"
    applied = QtCore.Signal()    # Apply: the fields are read, the caller saves, the window stays

    @property
    def version(self):
        """What Apply saves: a version number, NEW_VERSION, or NO_VERSION for the snippet alone."""
        return self._tabs[self._front]["n"]

    def __init__(self, categories: list, name: str = "", language: str = "VEX",
                 category: str = "", tags: str = "", code: str = "",
                 title: str = "Save Code to " + branding.APP_NAME, versions=(),
                 active: int = 0, load_version=None, saved: bool = False,
                 versions_on: bool = True, parent=None) -> None:
        super().__init__(title, fixed_size=False, parent=parent)    # the one resizable dialog
        drawn = self._drawn = amazetheme.drawn_code_dialog()
        self._versions = list(versions)        # [{n, name, ...}] oldest first, as the ledger
        self._load_version = load_version      # n -> the version's text, or None when unreadable
        self._tabs = [{"n": active if self._versions else NO_VERSION, "name": name, "code": code}]
        self._front = 0                        # the tab the fields and the editor show
        self.name = self.language = self.category = self.tags = self.code = ""
        self._versions_on = versions_on    # the library's Versions switch, in Preferences
        self.can_add_version = saved and versions_on    # and a snippet in the library to belong to

        form = QtWidgets.QGridLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(0)
        form.setVerticalSpacing(theme.ui_px(drawn["row_gap"]))
        left, right = drawn["label_columns"]
        gap = drawn["label_gap"]
        for column, width in ((0, left), (1, gap), (3, drawn["half_gap"]), (4, right), (5, gap)):
            form.setColumnMinimumWidth(column, theme.ui_px(width))
        form.setColumnStretch(2, 1)
        form.setColumnStretch(6, 1)    # the two fields grow alike when the window does

        self._line_name = QtWidgets.QLineEdit(name)
        self._line_name.setToolTip(ui_helpers.tooltip_text(tooltips.CODE_NAME))
        self._combo_lang = ui_helpers.DesignedComboBox()    # its dropdown holds the box's width
        for lang in LANGUAGES:
            self._combo_lang.addItem(lang)
        if language in LANGUAGES:
            self._combo_lang.setCurrentText(language)
        self._combo_category = ui_helpers.DesignedComboBox()    # the sidebar's Add mints new ones
        base_dialog.fill_categories(self._combo_category, categories, category)
        self._line_tags = QtWidgets.QLineEdit(tags)
        field_w, field_h = (theme.ui_px(v) for v in drawn["field"])
        for row, column, span, label, field in (
                (0, 0, 1, "Name", self._line_name),
                (1, 0, 1, "Language", self._combo_lang),
                (0, 3, 2, "Category", self._combo_category),    # a right label may use the gap
                (1, 3, 2, "Tags", self._line_tags)):
            at = 2 if column == 0 else 6    # each field's column, past its label and the label gap
            text = QtWidgets.QLabel(label)
            text.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored,    # never widens a column
                               QtWidgets.QSizePolicy.Policy.Preferred)
            text.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight
                              | QtCore.Qt.AlignmentFlag.AlignVCenter)
            field.setMinimumWidth(field_w)
            field.setFixedHeight(field_h)
            form.addWidget(text, row, column, 1, span)
            form.addWidget(field, row, at)

        self._editor = CodeEditor(code)
        self._editor.setMinimumHeight(theme.ui_px(drawn["editor"][1]))

        self._apply_button, self._cancel_button, buttons = self.drawn_pair(    # Cancel keeps what Apply saved
            amazetheme.BTN_APPLY, self._apply)

        content = QtWidgets.QWidget()
        stack = QtWidgets.QVBoxLayout(content)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(0)
        stack.addLayout(form)
        stack.addSpacing(theme.ui_px(drawn["stack_gap"]))
        stack.addWidget(self._editor, 1)    # the editor is what the window's resize grows
        stack.addSpacing(theme.ui_px(drawn["button_gap"]))
        stack.addLayout(buttons)

        self._version_menu = None
        self.set_content(content)
        self.finish(ok_cancel=False, margins=drawn["margins"])
        self._line_name.textChanged.connect(self._name_changed)
        self._name_changed()

    def header_band_text(self) -> str:
        """The version's name, which the Name field holds, and `Untitled` while it holds none."""
        return self._line_name.text().strip() or amazetheme.BAND_UNTITLED

    def paintEvent(self, event):
        """The window's drawn ground; painted here, so no child inherits it as its own colour."""
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor(amazetheme.CODE_GROUND))
        painter.end()

    def build_header_band(self):
        """The strip with the version tabs and the +, which lists New Version and every version."""
        drawn = self._drawn
        band = QtWidgets.QWidget(self)
        band.setObjectName("amaze_header_band")
        band.setFixedHeight(theme.ui_px(amazetheme.drawn_band(self.FRAME_KEY)[0]))
        band.setAutoFillBackground(True)
        ground = band.palette()
        ground.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColor(amazetheme.CODE_BAND))
        band.setPalette(ground)
        row = QtWidgets.QHBoxLayout(band)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        self._tabbar = _VersionTabs(drawn, band)
        self._tabbar.setObjectName("amaze_code_version_tabs")
        self._tabbar.picked.connect(self._select_tab)
        self._tabbar.closed.connect(self._close_tab)

        self._plus = QtWidgets.QToolButton(band)
        self._plus.setAutoRaise(True)
        self._plus.setToolTip(ui_helpers.tooltip_text(tooltips.CODE_VERSIONS))
        self._plus.setStyleSheet(    # a bare + filling its drawn box
            "QToolButton { border: none; padding: 0; }"
            " QToolButton::menu-indicator { image: none; }")
        _x, _y, side, high = (theme.ui_px(v) for v in drawn["plus"])
        art, dpr = amaze.package_file("ui", "icon_version_add.svg"), theme.screen_ratio(self)
        icon = QtGui.QIcon(ui_helpers.device_pixmap(art, side, dpr))
        icon.addPixmap(ui_helpers.device_pixmap(art, side, dpr,    # Houdini's style dims nothing
                                                opacity=ui_helpers.DISABLED_OPACITY),
                       QtGui.QIcon.Mode.Disabled)
        self._plus.setIcon(icon)
        self._plus.setIconSize(QtCore.QSize(side, high))
        self._plus.setFixedSize(side, high)
        self._version_menu = QtWidgets.QMenu(self._plus)    # one menu, refilled as it opens
        self._version_menu.aboutToShow.connect(self._fill_version_menu)
        self._plus.setMenu(self._version_menu)
        self._plus.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        self._plus.setEnabled(self.can_add_version)
        self._plus.setVisible(self._versions_on)    # Versions off: no + at all

        row.addWidget(self._tabbar)
        row.addSpacing(theme.ui_px(drawn["plus_gap"]))
        row.addWidget(self._plus)
        row.addStretch(1)
        return band

    def _name_changed(self, _text=""):
        """The front tab shows the Name field."""
        self._tabs[self._front]["name"] = self._line_name.text().strip()
        self._tabbar.show_tabs([tab["name"] for tab in self._tabs], self._front)

    def _keep_front(self) -> None:
        tab = self._tabs[self._front]
        tab["name"], tab["code"] = self._line_name.text().strip(), self._editor.toPlainText()

    def _bring_forward(self, index: int) -> None:
        """Show tab `index`: its name in the field, its code in the editor."""
        self._front = index
        tab = self._tabs[index]
        self._line_name.setText(tab["name"])
        self._editor.setPlainText(tab["code"])
        self._name_changed()

    def _select_tab(self, index: int) -> None:
        if index != self._front:
            self._keep_front()
            self._bring_forward(index)

    def _close_tab(self, index: int) -> None:
        """Close one tab; its version stays, and the last tab cannot close."""
        if len(self._tabs) < 2:
            return
        if index != self._front:
            self._keep_front()
        del self._tabs[index]
        if index < self._front:
            self._front -= 1
        elif index == self._front:    # its unsaved edits go with it
            self._bring_forward(min(index, len(self._tabs) - 1))
            return
        self._name_changed()

    def _open_tab(self, tab: dict) -> None:
        self._keep_front()
        self._tabs.append(tab)
        self._bring_forward(len(self._tabs) - 1)

    def _fill_version_menu(self) -> None:
        menu = self._version_menu
        menu.clear()
        menu.addAction(amazetheme.MENU_NEW_VERSION).triggered.connect(self._new_version)
        menu.addSeparator()
        for entry in reversed(self._versions):    # newest first, as the Versions window lists them
            number = int(entry.get("n", 0))
            action = menu.addAction(version_store.version_label(entry))
            action.setCheckable(True)
            action.setChecked(number == self.version)
            action.triggered.connect(lambda _on=False, n=number: self._show_version(n))

    def _new_version(self) -> None:
        """A tab for a new version holding the front tab's code; Apply saves it under its name."""
        self._open_tab({"n": NEW_VERSION, "code": self._editor.toPlainText(),
                        "name": version_store.version_label({"n": self._next_number()})})
        self._line_name.setFocus()
        self._line_name.selectAll()

    def _next_number(self) -> int:
        waiting = sum(1 for tab in self._tabs if tab["n"] == NEW_VERSION)
        return max([int(v.get("n", 0)) for v in self._versions] or [0]) + 1 + waiting + (
            0 if self._versions else 1)    # a snippet's first New Version is Version 2

    def _show_version(self, number: int) -> None:
        """Version `number` in a tab of its own, or its tab brought forward; nothing is saved."""
        for index, tab in enumerate(self._tabs):
            if tab["n"] == number:
                self._select_tab(index)
                return
        text = self._load_version(number) if self._load_version else None
        if text is None:
            QtWidgets.QMessageBox.warning(self, messages.TITLE_AMAZE,
                                          messages.CODE_VERSION_UNREADABLE)
            return
        entry = next(v for v in self._versions if int(v.get("n", 0)) == number)
        self._open_tab({"n": number, "code": text, "name": version_store.version_label(entry)})

    def versions_saved(self, versions, active: int) -> None:
        """What the caller's save left: the ledger and the version that is now active."""
        kept_before = bool(self._versions)
        self._versions = list(versions) if self._versions_on else []    # off: the snippet alone
        self._tabs[self._front]["n"] = active if self._versions else NO_VERSION
        if self._versions and not kept_before:    # the snippet alone became the first version
            first = min(int(v.get("n", 0)) for v in self._versions)
            for index, tab in enumerate(self._tabs):
                if index != self._front and tab["n"] is NO_VERSION:
                    tab["n"] = first
        self.can_add_version = self._versions_on    # the snippet exists once an Apply saved it
        self._plus.setEnabled(self.can_add_version)

    def _harvest(self) -> bool:
        self.name = self._line_name.text().strip()
        self.language = self._combo_lang.currentText().strip()
        self.category = base_dialog.chosen_category(self._combo_category)
        self.tags = self._line_tags.text().strip()
        self.code = self._editor.toPlainText()
        if not self.code.strip():
            QtWidgets.QMessageBox.warning(
                self, messages.TITLE_EMPTY_SNIPPET, messages.SNIPPET_HAS_NO_CODE)
            return False
        return True

    def _apply(self) -> None:
        """Read the fields and hand them to the caller, which saves; the window stays open."""
        if self._harvest():
            self.canceled = False
            self.applied.emit()
