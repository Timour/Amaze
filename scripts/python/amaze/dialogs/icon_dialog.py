"""Pick a tile icon and its background colour. SHOW it, never exec: Custom Color opens Houdini's native picker, which lands under a Qt exec loop. ▸r/houdini-colour-picker"""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from amaze.core import tile_icons
from amaze.helpers import theme, ui_helpers

CELL = 34            # one icon button in the chooser grid
COLUMNS = 10         # how wide the grid runs before wrapping
SIDE_WIDTH = 150     # preview, swatches and buttons all measure this, so the side reads as one block


class IconDialog(QtWidgets.QDialog):
    """NON-MODAL icon + colour picker; `spec` is the result and `canceled` stays True until the user accepts, so Esc and the title-bar X read as cancel."""

    def __init__(self, current=None, stroke_units: float = 0.0,
                 parent=None, tile_name=None,
                 tile_name_enabled: bool = True) -> None:
        super().__init__(parent)
        self.canceled = True
        self._tile_name = tile_name   # None = the section has no rename at all; "" with tile_name_enabled False = a multi-selection, so the field greys out
        self._tile_name_enabled = bool(tile_name_enabled)
        self.new_tile_name = None
        self._stroke = stroke_units or tile_icons.STROKE_UNITS
        current = tile_icons.normalise(current)
        self.spec = dict(current)
        self._name = current.get("name", "") or "box"
        self._bg = current.get("bg", "") or tile_icons.PRESETS[0][1]
        self._ink = current.get("ink", "") or tile_icons.DEFAULT_INK
        self._buttons_by_name: dict = {}

        self.setWindowTitle("Tile Icon")
        gap = theme.ui_px(8)

        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(gap, gap, gap, gap)
        root.setSpacing(gap)
        root.addLayout(self._build_chooser(gap), 1)
        root.addWidget(self._build_side(gap), 0)
        self._refresh_preview()


    def _build_chooser(self, gap: int):
        column = QtWidgets.QVBoxLayout()
        column.setSpacing(gap // 2)

        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Search %d icons"
                                       % len(tile_icons.icon_names()))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        column.addWidget(self.search)

        chooser_bg = self.palette().color(   # the dialog's OWN window colour, so the grid is not a light island in it
            QtGui.QPalette.ColorRole.Window).name()
        icon_ink = theme.color_hex("text_bright")

        area = QtWidgets.QScrollArea()
        area.setWidgetResizable(True)
        area.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        holder = QtWidgets.QWidget()
        holder.setStyleSheet(
            "QWidget { background: %s; }"
            " QToolButton { background: transparent; border: none;"
            " border-radius: 3px; }"
            " QToolButton:hover { background: rgba(255, 255, 255, 28); }"
            " QToolButton:checked { background: %s;"
            " border: 2px solid %s; }"
            % (chooser_bg, theme.color_hex("field"), icon_ink)
        )
        self._grid = QtWidgets.QGridLayout(holder)
        self._grid.setSpacing(2)
        self._grid.setContentsMargins(0, 0, 0, 0)

        group = QtWidgets.QButtonGroup(self)   # every button is built ONCE and only shown/hidden by the filter; rebuilding 287 per keystroke feels broken
        group.setExclusive(True)
        icon_px = theme.ui_px(CELL - 14)
        self._icon_px = icon_px
        self._icon_ink = icon_ink
        self._icon_dpr = None                             # the ratio the icons currently carry; None until the first ink ▸r/screen-dpr
        for name in tile_icons.icon_names():
            button = QtWidgets.QToolButton()
            button.setCheckable(True)
            button.setAutoRaise(True)
            button.setToolTip(name)
            button.setFixedSize(theme.ui_px(CELL), theme.ui_px(CELL))
            button.setIconSize(QtCore.QSize(icon_px, icon_px))
            button.clicked.connect(
                lambda _checked=False, chosen=name: self._choose(chosen))
            group.addButton(button)
            self._buttons_by_name[name] = button
        self._ink_for_screen()      # again on show, when the window finally has a screen to ask ▸r/screen-dpr
        self._relayout(tile_icons.icon_names())

        area.setStyleSheet("QScrollArea { background: %s; border: none; }"
                           % chooser_bg)
        area.setWidget(holder)
        area.setMinimumSize(
            theme.ui_px(CELL * COLUMNS + 30), theme.ui_px(CELL * 8))
        column.addWidget(area, 1)
        return column

    def _build_side(self, gap: int):
        """The right-hand column: name, preview, swatches, buttons."""
        side = theme.ui_px(SIDE_WIDTH)
        panel = QtWidgets.QWidget()
        panel.setFixedWidth(side)         # the ONE width preview, swatches and buttons all fill, so the column reads as a block
        column = QtWidgets.QVBoxLayout(panel)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(gap // 2)

        if self._tile_name is not None:
            self.tile_name_edit = QtWidgets.QLineEdit(self._tile_name)   # no "Name" label: the field fills the column and its own content says what it is
            self.tile_name_edit.setEnabled(self._tile_name_enabled)
            self.tile_name_edit.setPlaceholderText("Name")
            self.tile_name_edit.setToolTip(ui_helpers.tooltip_text(
                "Rename this tile. The name is what the grid, the "
                "sidebar count and every search look at."))
            column.addWidget(self.tile_name_edit)
            column.addSpacing(gap // 2)
        else:
            self.tile_name_edit = None

        self.preview = QtWidgets.QLabel()
        self.preview.setFixedSize(side, side)
        self.preview.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self.preview)

        self.chosen_label = QtWidgets.QLabel()
        self.chosen_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self.chosen_label)
        column.addSpacing(gap)

        swatches = QtWidgets.QHBoxLayout()   # expanding widths and NO stretch, so the four share exactly the column width
        swatches.setSpacing(4)
        self._swatches = []
        for label, colour in tile_icons.PRESETS:
            swatch = QtWidgets.QToolButton()
            swatch.setToolTip(label)
            swatch.setFixedHeight(theme.ui_px(28))
            swatch.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Expanding,
                QtWidgets.QSizePolicy.Policy.Fixed,
            )
            swatch.setStyleSheet(
                "background:%s; border:1px solid #222;" % colour)
            swatch.clicked.connect(
                lambda _checked=False, picked=colour: self._set_bg(picked))
            swatches.addWidget(swatch)
            self._swatches.append(swatch)
        column.addLayout(swatches)

        self.custom_button = QtWidgets.QPushButton("Custom Color...")
        self.custom_button.setToolTip(ui_helpers.tooltip_text(
            "Pick any color, with Houdini's color picker."))
        self.custom_button.clicked.connect(self._pick_custom)
        column.addWidget(self.custom_button)

        ink_row = QtWidgets.QHBoxLayout()   # ink sits next to the background it must work against; dark on dark is an invisible icon
        ink_row.setSpacing(6)
        ink_row.addWidget(QtWidgets.QLabel("Icon Color"))
        self.ink_combo = QtWidgets.QComboBox()
        self.ink_combo.addItem("Dark", "dark")
        self.ink_combo.addItem("Light", "light")
        self.ink_combo.setCurrentIndex(
            max(self.ink_combo.findData(self._ink), 0))
        self.ink_combo.currentIndexChanged.connect(self._set_ink)
        ink_row.addWidget(self.ink_combo, 1)
        column.addLayout(ink_row)
        column.addStretch(1)

        actions = QtWidgets.QHBoxLayout()   # two buttons, no Cancel: closing IS cancelling, and Remove is the way back so an icon is never a one-way door
        actions.setSpacing(6)
        self.clear_button = QtWidgets.QPushButton("Remove")
        self.clear_button.setToolTip(
            "Show this tile's own thumbnail again")
        self.clear_button.clicked.connect(self._clear)
        actions.addWidget(self.clear_button)

        self.accept_button = QtWidgets.QPushButton("Accept")
        self.accept_button.setDefault(True)
        self.accept_button.clicked.connect(self._accept)
        actions.addWidget(self.accept_button)
        column.addLayout(actions)
        return panel


    def showEvent(self, event) -> None:
        """Ink the grid for the screen the dialog actually opened on; an unrealised widget answers with the primary ratio. ▸r/screen-dpr"""
        super().showEvent(event)
        self._ink_for_screen()

    def _ink_for_screen(self) -> None:
        """Redraw the chooser icons when this window's ratio differs from the one they carry; a no-op when it does not."""
        dpr = float(self.devicePixelRatioF())
        if dpr == self._icon_dpr:
            return
        self._icon_dpr = dpr
        for name, button in self._buttons_by_name.items():
            button.setIcon(QtGui.QIcon(self._chooser_icon(
                name, self._icon_px, dpr, self._icon_ink)))

    @staticmethod
    def _chooser_icon(name: str, icon_px, dpr: float, ink: str):
        """One chooser icon: the Feather SVG re-inked, rendered at device pixels with the ratio stamped, the contract every badge pixmap follows."""
        return ui_helpers.device_pixmap(
            tile_icons.icon_path(name), icon_px, dpr, {"currentColor": ink})

    def _relayout(self, names) -> None:
        while self._grid.count():
            self._grid.takeAt(0)
        for position, name in enumerate(names):
            self._grid.addWidget(self._buttons_by_name[name],
                                 position // COLUMNS, position % COLUMNS)

    def _apply_filter(self, text: str) -> None:
        """Show the icons whose name contains `text`; the visibility test asks a SET, since on 287 icons a list test made an unfiltered keystroke 287 x 287 scans."""
        text = (text or "").strip().lower()
        matching = [n for n in tile_icons.icon_names() if text in n] \
            if text else list(tile_icons.icon_names())
        visible = set(matching)
        for name, button in self._buttons_by_name.items():
            button.setVisible(name in visible)
        self._relayout(matching)

    def _choose(self, name: str) -> None:
        self._name = name
        self._refresh_preview()

    def _set_bg(self, colour: str) -> None:
        if tile_icons.is_valid_colour(colour):
            self._bg = colour
            self._refresh_preview()

    def _set_ink(self, index: int) -> None:
        token = self.ink_combo.itemData(index)
        if token:
            self._ink = str(token)
            self._refresh_preview()

    def _pick_custom(self) -> None:
        """Houdini's colour picker, reachable ONLY because this dialog holds no exec loop. ▸r/houdini-colour-picker"""
        from amaze.helpers import ui_helpers
        chosen = ui_helpers.pick_color(self._bg, self, "Tile Background")
        if chosen is not None:
            self._set_bg(chosen.name())

    def _refresh_preview(self) -> None:
        button = self._buttons_by_name.get(self._name)
        if button is not None and not button.isChecked():
            button.setChecked(True)
        image = tile_icons.compose(self._name, self._bg, 256, self._stroke,
                                   self._ink)
        if image is not None:
            self.preview.setPixmap(QtGui.QPixmap.fromImage(image).scaled(
                self.preview.size(),
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            ))
        self.chosen_label.setText("%s  %s" % (self._name, self._bg))

    def _clear(self) -> None:
        self.spec = {}
        self.canceled = False
        self._harvest_tile_name()
        self.accept()

    def _harvest_tile_name(self) -> None:
        """On any accepting close: the new name, or None when the field is absent, greyed, blank or unchanged."""
        if self.tile_name_edit is None or \
                not self.tile_name_edit.isEnabled():
            return
        text = self.tile_name_edit.text().strip()
        if text and text != (self._tile_name or ""):
            self.new_tile_name = text

    def _accept(self) -> None:
        self.spec = tile_icons.normalise(
            {"name": self._name, "bg": self._bg, "ink": self._ink})
        self.canceled = False
        self._harvest_tile_name()
        self.accept()
