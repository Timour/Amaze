"""Pick a tile icon and its background colour. SHOW it, never exec: Custom Color opens Houdini's native picker, which lands under a Qt exec loop. ▸r/houdini-colour-picker"""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from amaze import amazetheme
from amaze.core import tile_icons
from amaze.dialogs import base_dialog
from amaze.helpers import theme, ui_helpers

CELL = amazetheme.D02_CELL            # one icon button in the chooser grid ▸p/one-design-document
COLUMNS = amazetheme.D02_COLUMNS      # how wide the grid runs before wrapping
SIDE_WIDTH = amazetheme.D02_SIDE_WIDTH   # preview, swatches and buttons all measure this, so the side reads as one block


class IconDialog(base_dialog.AssetDialog):
    """NON-MODAL icon + colour picker on the house shell; `spec` is the result and the inherited `canceled` stays True until the user accepts, so Esc and the title-bar X read as cancel. `applied` fires on Apply, which commits without closing - Houdini's own Accept/Apply pair (ref ▸ windows/optype)."""

    FORM_WIDTH = amazetheme.D02_FORM_WIDTH
    HEADER_BAND = True    # D02 wears the drawn name strip ▸p/one-design-document

    applied = QtCore.Signal()

    def __init__(self, current=None, stroke_units: float = 0.0,
                 parent=None, tile_name=None,
                 tile_name_enabled: bool = True, tile_tags=None,
                 categories=None, tile_category="") -> None:
        super().__init__(tile_name if tile_name and tile_name_enabled
                         else amazetheme.TITLE_TILE_ICON,    # the WINDOW TITLE is the asset's own name, as drawn - a multi-selection has none, so it keeps the generic one
                         fixed_size=False, parent=parent)
        self._tile_name = tile_name   # None = the section has no rename at all; "" with tile_name_enabled False = a multi-selection, so the field greys out
        self._tile_name_enabled = bool(tile_name_enabled)
        self._tile_tags = tile_tags   # None = this section has no tags; on a multi-selection the field opens empty and ADDS
        self._categories = list(categories or [])   # None = this section has no categories, so no field at all
        self._tile_category = tile_category or ""
        self.new_tile_name = None
        self.new_tags = None
        self.new_category = None    # NOT greyed on a multi-selection: moving a whole selection to one category is the point of it
        self._stroke = stroke_units or tile_icons.STROKE_UNITS
        current = tile_icons.normalise(current)
        self._has_icon = bool(current)   # what the Custom Icon toggle opens on: OFF = the tile's own thumbnail
        self.spec = dict(current)
        self._name = current.get("name", "") or "box"
        self._bg = current.get("bg", "") or tile_icons.PRESETS[0][1]
        self._ink = current.get("ink", "") or tile_icons.DEFAULT_INK
        self._buttons_by_name: dict = {}

        gap = theme.ui_px(8)

        content = QtWidgets.QWidget()
        body = QtWidgets.QHBoxLayout(content)
        body.setContentsMargins(0, 0, 0, 0)   # the shell owns the outer margins now
        body.setSpacing(gap)
        body.addLayout(self._build_chooser(gap), 1)
        body.addWidget(self._build_side(gap), 0)
        self.set_content(content)
        self.finish(ok_cancel=False)   # Accept and Apply live in the side column
        self.custom_toggle.toggled.connect(self._set_custom_enabled)
        self._set_custom_enabled(self._has_icon)
        self._refresh_preview()

    def _build_name_row(self, gap: int):
        """The asset's name above the grid - as drawn; the side column holds Category and Tags."""
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(gap)
        row.addWidget(QtWidgets.QLabel(amazetheme.LABEL_NAME))
        self.tile_name_edit = QtWidgets.QLineEdit(self._tile_name)
        self.tile_name_edit.setEnabled(self._tile_name_enabled)
        self.tile_name_edit.setToolTip(ui_helpers.tooltip_text(
            "Rename this tile. The name is what the grid, the "
            "sidebar count and every search look at."))
        row.addWidget(self.tile_name_edit, 1)
        return row

    def _build_search(self):
        """The icon filter, drawn at the bottom under the grid."""
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText(amazetheme.PLACEHOLDER_SEARCH_ICONS)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        return self.search

    def _build_chooser(self, gap: int):
        column = QtWidgets.QVBoxLayout()
        column.setSpacing(gap // 2)

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
        self._chooser_area = area
        out = QtWidgets.QVBoxLayout()
        out.setSpacing(gap // 2)
        if self._tile_name is not None:
            out.addLayout(self._build_name_row(gap))
        else:
            self.tile_name_edit = None
        out.addLayout(column, 1)
        column.addWidget(area, 1)
        column.addWidget(self._build_search())   # under the GRID it filters, not beside the buttons - as drawn
        return out

    def _build_side(self, gap: int):
        """The right-hand column: Category and Tags, preview, swatches, the Custom Icon toggle, Lines, buttons."""
        side = theme.ui_px(SIDE_WIDTH)
        panel = QtWidgets.QWidget()
        panel.setFixedWidth(side)         # the ONE width preview, swatches and buttons all fill, so the column reads as a block
        column = QtWidgets.QVBoxLayout(panel)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(gap // 2)

        top = QtWidgets.QFormLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        top.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight
                              | QtCore.Qt.AlignmentFlag.AlignVCenter)
        top.setFieldGrowthPolicy(    # BOTH stated: each defaults per host STYLE ▸r/form-layout-defaults
            QtWidgets.QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        if not self._categories:
            self.category_combo = None
        else:
            self.category_combo = ui_helpers.DesignedComboBox()   # its dropdown holds the box's width ▸r/combo-popup-width
            self.category_combo.setEditable(True)
            for name in self._categories:
                self.category_combo.addItem(name)
            self.category_combo.setCurrentText(self._tile_category)
            self.category_combo.setToolTip(ui_helpers.tooltip_text(
                "Move to this category. Applies to every tile you "
                "have selected."))
            top.addRow(amazetheme.LABEL_CATEGORY, self.category_combo)
        if self._tile_tags is None:
            self.tags_edit = None
        else:
            self.tags_edit = QtWidgets.QLineEdit(self._tile_tags)   # LIVE on a multi-selection: it opens empty and ADDS to every tile
            self.tags_edit.setToolTip(ui_helpers.tooltip_text(
                "Tags for this tile, separated by commas."
                if self._tile_name_enabled else
                "Tags to ADD to every tile you have selected, separated "
                "by commas. Each tile keeps the tags it already has."))
            top.addRow(amazetheme.LABEL_TAGS, self.tags_edit)
        if top.rowCount():
            column.addLayout(top)
            column.addSpacing(gap // 2)

        self.preview = QtWidgets.QLabel()
        self.preview.setFixedSize(side, side)
        self.preview.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self.preview)
        column.addSpacing(gap)

        swatches = QtWidgets.QHBoxLayout()   # expanding widths and NO stretch, so the five share exactly the column width
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

        toggle_row = QtWidgets.QHBoxLayout()   # Custom Icon OFF = the tile's own thumbnail; ON = the chooser applies
        toggle_row.setSpacing(6)
        toggle_row.addWidget(QtWidgets.QLabel(amazetheme.LABEL_CUSTOM_ICON))
        toggle_row.addStretch(1)    # the slack sits BETWEEN label and switch, as drawn
        self.custom_toggle = ui_helpers.ToggleSwitch()
        self.custom_toggle.setChecked(self._has_icon)
        self.custom_toggle.setToolTip(ui_helpers.tooltip_text(
            "Off shows the tile's own thumbnail; on uses the icon "
            "chosen here."))
        toggle_row.addWidget(self.custom_toggle)
        self.custom_button = QtWidgets.QPushButton(
            amazetheme.BTN_CUSTOM_COLOR)
        self.custom_button.setToolTip(ui_helpers.tooltip_text(
            "Pick any color, with Houdini's color picker."))
        self.custom_button.clicked.connect(self._pick_custom)
        toggle_row.addWidget(self.custom_button)
        column.addLayout(toggle_row)

        fields = QtWidgets.QFormLayout()   # ink sits next to the background it must work against - dark on dark is an invisible icon
        fields.setContentsMargins(0, 0, 0, 0)
        fields.setSpacing(6)
        fields.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight
                                 | QtCore.Qt.AlignmentFlag.AlignVCenter)
        fields.setFieldGrowthPolicy(    # BOTH stated: each defaults per host STYLE ▸r/form-layout-defaults
            QtWidgets.QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.ink_combo = ui_helpers.DesignedComboBox()    # its dropdown holds the box's width ▸r/combo-popup-width
        self.ink_combo.addItem("Dark", "dark")
        self.ink_combo.addItem("Light", "light")
        self.ink_combo.setCurrentIndex(
            max(self.ink_combo.findData(self._ink), 0))
        self.ink_combo.currentIndexChanged.connect(self._set_ink)
        fields.addRow(amazetheme.LABEL_LINES, self.ink_combo)
        column.addLayout(fields)
        column.addStretch(1)

        actions = QtWidgets.QHBoxLayout()   # Apply commits and stays open, Accept commits and closes - Houdini's own pair (ref ▸ windows/optype); closing IS cancelling, so there is no Cancel
        actions.setSpacing(6)
        actions.addStretch(1)               # both drawn flush RIGHT at a fixed width, not spanning the column
        self.apply_button = QtWidgets.QPushButton(amazetheme.BTN_APPLY)
        self.apply_button.setFixedWidth(theme.ui_px(amazetheme.D02_BUTTON_W))
        self.apply_button.clicked.connect(self._apply)
        actions.addWidget(self.apply_button)

        self.accept_button = QtWidgets.QPushButton(amazetheme.BTN_ACCEPT)
        self.accept_button.setFixedWidth(theme.ui_px(amazetheme.D02_BUTTON_W))
        self.accept_button.setDefault(True)
        self.accept_button.clicked.connect(self._accept)
        actions.addWidget(self.accept_button)
        column.addLayout(actions)
        return panel

    def _set_custom_enabled(self, on: bool) -> None:
        """The chooser follows the toggle; Name, Category and Tags do not - they are the asset's, not the icon's."""
        for widget in (self._chooser_area, self.search, self.custom_button,
                       self.ink_combo, self.preview, *self._swatches):
            widget.setEnabled(bool(on))


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

    def _harvest_tile_name(self) -> None:
        """On any accepting close: the new name, or None when the field is absent, greyed, blank or unchanged."""
        if self.tile_name_edit is None or \
                not self.tile_name_edit.isEnabled():
            return
        text = self.tile_name_edit.text().strip()
        if text and text != (self._tile_name or ""):
            self.new_tile_name = text

    def _harvest_tags(self) -> None:
        """On any accepting close: the tag line to write, or None when the field is absent, greyed or unchanged. An EMPTY field is a real answer - it clears the tags - so this cannot test for truth the way the name does."""
        if self.tags_edit is None or not self.tags_edit.isEnabled():
            return
        text = self.tags_edit.text().strip()
        if text != (self._tile_tags or "").strip():
            self.new_tags = text

    def _harvest_category(self) -> None:
        """On any accepting close: the category to move to, or None when the field is absent or unchanged. A BLANK is not an answer - unlike tags there is no such thing as no category - so it is ignored."""
        if self.category_combo is None:
            return
        text = self.category_combo.currentText().strip()
        if text and text != (self._tile_category or "").strip():
            self.new_category = text

    def _harvest(self) -> None:
        """Everything a commit writes: the spec per the toggle - OFF is `{}`, which the models read as "clear it" - and the name, tags and category."""
        if self.custom_toggle.isChecked():
            self.spec = tile_icons.normalise(
                {"name": self._name, "bg": self._bg, "ink": self._ink})
        else:
            self.spec = {}
        self._harvest_tile_name()
        self._harvest_tags()
        self._harvest_category()

    def _apply(self) -> None:
        """Commit and STAY OPEN; `canceled` stays True, so a later X re-applies nothing."""
        self._harvest()
        self.applied.emit()

    def _accept(self) -> None:
        self._harvest()
        self._on_accept()
