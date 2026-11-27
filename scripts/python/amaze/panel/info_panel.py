"""The info page: an image file's picture, then a read-only table of facts about the selection."""

from __future__ import annotations

from PySide6 import QtGui, QtWidgets

from amaze import amazetheme
from amaze.helpers import theme, ui_helpers
from amaze.panel import side_pane

_DRAWN = amazetheme.drawn_info()    # every size and spacing below is from the N02 design frame

DESCRIPTION = side_pane.Page(    # what the page is made of; the engine builds it
    drawn=_DRAWN,
    header=side_pane.Header(
        "icon_info.svg", amazetheme.INFO_ICON_ART_COLOR, amazetheme.INFO_ICON_COLOR, _DRAWN["preview_button_pad"],
        (side_pane.Button("preview_button", _DRAWN["preview_button"]),)),
    body=(side_pane.Picture("preview", _DRAWN["preview_height"], amazetheme.INFO_PREVIEW_LEAST),
          side_pane.DragLine("drag_line", _DRAWN["drag_line"]),
          side_pane.Rows("table", _DRAWN)))


class InfoPanel(side_pane.SidePage):
    """The side pane's page showing the pane engine's `info`; it is open only while shown."""

    def __init__(self, info, parent=None) -> None:
        super().__init__(DESCRIPTION, parent)
        self._info = info
        self.table.setFont(self.type_label.font())
        self.preview_button.setIconSize(self.preview_button.size())
        self.preview_button.clicked.connect(info.toggle_preview)
        saved = info.preview_height()
        if saved:
            self.body_widget.set_wanted_height(saved)
        self.body_widget.height_set.connect(info.keep_preview_height)
        info.changed.connect(self._show)
        info.another.connect(self.body_widget.scroll_to_top)    # another selection starts at the top
        info.picture_changed.connect(self._show_picture)
        self._show()

    def copy_font(self, source: QtWidgets.QWidget) -> None:
        """Take the base font from a .ui-loaded sibling."""
        self.table.setFont(self.copy_header_font(source))

    def _show(self) -> None:
        """The engine's header, rows and preview button."""
        import amaze
        info = self._info
        self._dimmed = info.dimmed()
        self.set_header(info.name(), info.type())
        self.table.set_rows(info.rows())
        self.paint_header()
        shown = info.preview_shown()
        self.preview_button.setIcon(QtGui.QIcon(ui_helpers.device_pixmap(
            amaze.package_file("ui", "icon_preview_hide.svg" if shown else "icon_preview_show.svg"),
            theme.ui_px(_DRAWN["preview_button"]), theme.screen_ratio(self))))
        self.preview_button.setToolTip(ui_helpers.tooltip_text(
            amazetheme.INFO_HIDE_PREVIEW if shown else amazetheme.INFO_SHOW_PREVIEW))
        self.preview_button.setVisible(info.preview_offered())    # only an image file has a picture to hide

    def _show_picture(self) -> None:
        self.preview.set_image(self._info.picture())

    def rows(self) -> tuple:
        """The rows shown, for tests."""
        return self.table.rows()

    def _picture_width(self) -> int:
        """The pane's width in screen pixels: the picture is read no wider."""
        return max(1, round(self.body_widget.width() * theme.screen_ratio(self)))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._info.set_width(self._picture_width())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._info.set_width(self._picture_width())
        self._info.set_open(True)

    def hideEvent(self, event) -> None:
        self._info.set_open(False)
        super().hideEvent(event)
