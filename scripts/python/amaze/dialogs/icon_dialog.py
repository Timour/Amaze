"""Pick a tile icon and its background colour.

Not a form, so not an AssetDialog: the thing being chosen is a picture,
and the only honest way to choose a picture is to look at it. The
dialog is a searchable grid of the 287 Feather icons, four preset
colours plus a custom one, and a live preview of the actual composed
tile - the same `tile_icons.compose()` the grid will use, so what is
previewed is what lands.

The preview is the point. Colour and icon interact (a light symbol
disappears on a light background), and nobody can hold that in their
head from two separate pickers.

    dlg = IconDialog(current={"name": "box", "bg": "#ef8878"})
    dlg.finished.connect(on_finished)   # then read dlg.canceled/.spec
    dlg.show()                          # NON-modal, deliberately

NON-MODAL like Preferences, and for the same recorded reason: the
Custom Color button opens Houdini's own picker, which is a NATIVE
modal - raised while a Qt modal exec loop is active it lands UNDER the
dialog, invisible, and the nested cross-toolkit loops crashed Houdini
once. A dialog that wants the Houdini picker must not hold an exec
loop of its own.
"""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from amaze.core import tile_icons
from amaze.helpers import theme, ui_helpers

#: Size of one icon button in the chooser grid.
CELL = 34
#: How wide the grid runs before wrapping.
COLUMNS = 10
#: The right-hand column's width - preview, swatches and buttons all
#: measure exactly this, so the side of the dialog reads as one block.
SIDE_WIDTH = 150


class IconDialog(QtWidgets.QDialog):
    """Modal icon + colour picker. `spec` is the result; `canceled`
    follows the house convention (True until the user accepts, so Esc
    and the title-bar X read as cancel)."""

    def __init__(self, current=None, stroke_units: float = 0.0,
                 parent=None, tile_name=None,
                 tile_name_enabled: bool = True) -> None:
        super().__init__(parent)
        self.canceled = True
        # The Name field (2026-08-01): Customize is the one rename
        # path every section shares. None = the section has no rename
        # (File - those names are the files on disk); "" with
        # tile_name_enabled False = a multi-selection, where the field
        # greys out like any single-item action.
        self._tile_name = tile_name
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

    # -- construction -------------------------------------------------

    def _build_chooser(self, gap: int):
        column = QtWidgets.QVBoxLayout()
        column.setSpacing(gap // 2)

        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Search %d icons"
                                       % len(tile_icons.icon_names()))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        column.addWidget(self.search)

        # The chooser wears the dialog's own colours: the backdrop is
        # the dialog's window colour (whatever Houdini painted the rest
        # of this dialog), and the icons are re-inked in the palette's
        # lightest grey - text_bright, the same grey the dialog's own
        # labels read in. The grid used to be a light island instead.
        chooser_bg = self.palette().color(
            QtGui.QPalette.ColorRole.Window).name()
        icon_ink = theme.color_hex("text_bright")

        area = QtWidgets.QScrollArea()
        area.setWidgetResizable(True)
        area.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        holder = QtWidgets.QWidget()
        holder.setStyleSheet(
            "QWidget { background: %s; }"
            # Transparent by default so the backdrop shows through;
            # the checked one has to be unmistakable, since it is the
            # only indication of what the preview is showing - on the
            # dark backdrop that is a lifted fill plus a bright ring.
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

        # The icon set is fixed, so every button is built once and only
        # SHOWN or HIDDEN by the filter - rebuilding 287 buttons on each
        # keystroke is the version of this that feels broken.
        group = QtWidgets.QButtonGroup(self)
        group.setExclusive(True)
        # Feather icons carry stroke="currentColor" and QSvgRenderer
        # does not resolve it (recorded) - straight QIcon(path) draws
        # them BLACK, invisible on the dark backdrop. The shared helper
        # substitutes the ink first, rendered at devicePixelRatio like
        # every pixmap.
        app = QtWidgets.QApplication.instance()
        dpr = app.devicePixelRatio() if app else 1.0
        icon_px = theme.ui_px(CELL - 14)
        for name in tile_icons.icon_names():
            button = QtWidgets.QToolButton()
            button.setCheckable(True)
            button.setAutoRaise(True)
            button.setToolTip(name)
            button.setFixedSize(theme.ui_px(CELL), theme.ui_px(CELL))
            button.setIcon(QtGui.QIcon(
                self._chooser_icon(name, icon_px, dpr, icon_ink)))
            button.setIconSize(QtCore.QSize(icon_px, icon_px))
            button.clicked.connect(
                lambda _checked=False, chosen=name: self._choose(chosen))
            group.addButton(button)
            self._buttons_by_name[name] = button
        self._relayout(tile_icons.icon_names())

        area.setStyleSheet("QScrollArea { background: %s; border: none; }"
                           % chooser_bg)
        area.setWidget(holder)
        area.setMinimumSize(
            theme.ui_px(CELL * COLUMNS + 30), theme.ui_px(CELL * 8))
        column.addWidget(area, 1)
        return column

    def _build_side(self, gap: int):
        # ONE width for the whole column: the preview, the swatch row,
        # Custom Color and the two buttons all measure the same, which
        # is only true if something fixes it. The panel width is that
        # something - everything inside then fills it.
        side = theme.ui_px(SIDE_WIDTH)
        panel = QtWidgets.QWidget()
        panel.setFixedWidth(side)
        column = QtWidgets.QVBoxLayout(panel)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(gap // 2)

        if self._tile_name is not None:
            # NO "Name" label (2026-08-01): the column is one width
            # and the field takes all of it, like the preview and the
            # buttons below. A label would cost the field the space
            # and say what the field's own content already says.
            self.tile_name_edit = QtWidgets.QLineEdit(self._tile_name)
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

        # The swatch row spans the same width as the preview above it
        # and the buttons below: fixed-size boxes with a trailing
        # stretch left the column visibly ragged. Expanding widths and
        # NO stretch means the four share exactly the column.
        swatches = QtWidgets.QHBoxLayout()
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

        # Ink lives here, next to the background it has to work
        # against: dark on a dark tile is an invisible icon, and the
        # preview above is the only place that is obvious.
        ink_row = QtWidgets.QHBoxLayout()
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

        # Two buttons, no Cancel - closing the window IS cancelling,
        # and `canceled` stays True until one of these is pressed, so
        # Esc and the title-bar X leave the tile exactly as it was.
        #
        # "Remove" is the way back: an icon must never be a one-way
        # door, and the render underneath was never overwritten.
        actions = QtWidgets.QHBoxLayout()
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

    # -- behaviour ----------------------------------------------------

    @staticmethod
    def _chooser_icon(name: str, icon_px, dpr: float, ink: str):
        """One chooser icon: the Feather SVG re-inked (currentColor is
        never resolved by QSvgRenderer - recorded) and rendered at
        device pixels with the ratio stamped, the contract every badge
        pixmap follows."""
        pixmap = ui_helpers.render_svg_pixmap(
            tile_icons.icon_path(name),
            max(1, int(round(icon_px * dpr))),
            {"currentColor": ink})
        pixmap.setDevicePixelRatio(dpr)
        return pixmap

    def _relayout(self, names) -> None:
        while self._grid.count():
            self._grid.takeAt(0)
        for position, name in enumerate(names):
            self._grid.addWidget(self._buttons_by_name[name],
                                 position // COLUMNS, position % COLUMNS)

    def _apply_filter(self, text: str) -> None:
        """Show the icons whose name contains `text`.

        The visibility test asks a SET, not the list: it runs once per
        button against a result that is the same length, so on the 287
        shipped icons an unfiltered keystroke was 287 x 287 list scans.
        The list itself stays - `_relayout` places them in order, and
        order is what a grid is.
        """
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
        """Houdini's colour picker, like everywhere else in Amaze.

        Possible ONLY because this dialog is non-modal: the shared
        helper takes the native picker when no Qt modal loop is active,
        which is now true here by construction. The brief detour
        through a typed hex field (one commit, 2026-07-31) mistook
        "no OS picker" for "no picker" - the modal exec loop was the
        actual obstacle, and it is the thing that changed.
        """
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
        """On any accepting close: the new name, or None when the field
        is absent, greyed, blank or unchanged."""
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
