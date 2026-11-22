"""The empty grid page's widgets; the pane's `empty_state` says which page shows, and its words."""
from PySide6 import QtCore, QtWidgets

from amaze.helpers import theme
from amaze.panel import grid


class EmptyPage(QtWidgets.QWidget):
    """The empty-state labels and button, with no geometry code. ▸r/transparent-for-mouse"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        base = self.font()
        outer = QtWidgets.QVBoxLayout(self)
        pad = theme.ui_px(24)
        outer.setContentsMargins(pad, pad, pad, pad)
        outer.addStretch(1)

        self._head = QtWidgets.QLabel("", self)
        self._head.setFont(theme.font("empty_headline", base))
        self._text = QtWidgets.QLabel("", self)
        for label in (self._head, self._text):
            label.setWordWrap(True)
            label.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter
                               | QtCore.Qt.AlignmentFlag.AlignTop)    # the label centres its own text ▸r/label-centres-itself
            outer.addWidget(label)
            outer.addSpacing(theme.ui_px(8))

        self._btn = QtWidgets.QPushButton("", self)
        outer.addWidget(self._btn, 0,
                        QtCore.Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch(1)
        self._handler_name = ""

    def button(self):
        return self._btn

    def say(self, panel, blank: str, detail: str) -> None:
        """Show this empty state's texts and connect its button to the method its path names."""
        headline, sentence, label, handler_name = panel.pane.empty_state.words(blank, detail)
        self._head.setText(headline)
        self._head.setVisible(bool(headline))
        self._text.setText(sentence)
        self._text.setVisible(bool(sentence))

        handler = getattr(panel, handler_name, None) if handler_name else None
        wanted = bool(label) and callable(handler)
        self._btn.setText(label if wanted else "")
        self._btn.setVisible(wanted)
        if self._handler_name != handler_name:
            if self._handler_name:          # only ever one connection
                self._btn.clicked.disconnect()
            if wanted:
                self._btn.clicked.connect(handler)
            self._handler_name = handler_name


def page(panel):
    """The panel's EmptyPage, created and added to the grid pane on the first call."""
    found = getattr(panel, "empty_page", None)
    if found is not None:
        return found
    host = grid.grid_pane_layout(panel)
    if host is None:
        return None
    found = EmptyPage(host.parentWidget())
    found.setVisible(False)
    host.addWidget(found)
    panel.empty_page = found
    return found


def refresh(panel) -> None:
    """The only entry point: the pane's empty state, shown through `grid.apply_grid_face`."""
    blank, detail = panel.pane.empty_state.verdict()
    surface = page(panel)
    if surface is None:
        return
    if blank:
        surface.say(panel, blank, detail)
    grid.apply_grid_face(panel, bool(blank))

