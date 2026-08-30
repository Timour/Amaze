"""Pick a tile icon and its background colour. SHOW it, never exec: Custom Color opens Houdini's native picker, which lands under a Qt exec loop. ▸r/houdini-colour-picker"""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from amaze import amazetheme
from amaze import tooltips
from amaze.core import tile_icons
from amaze.dialogs import base_dialog
from amaze.helpers import theme, ui_helpers

CELL = amazetheme.D02_CELL            # one icon button in the chooser grid ▸p/one-design-document
COLUMNS = amazetheme.D02_COLUMNS      # how wide the grid runs before wrapping


class IconDialog(base_dialog.AssetDialog):
    """NON-MODAL icon + colour picker on the house shell; `spec` is the result and the inherited `canceled` stays True until the user accepts, so Esc and the title-bar X read as cancel. `applied` fires on Apply, which commits without closing - Houdini's own Accept/Apply pair (ref ▸ windows/optype)."""

    FORM_WIDTH = amazetheme.D02_FORM_WIDTH
    HEADER_BAND = True    # D02 wears the drawn name strip ▸p/one-design-document

    applied = QtCore.Signal()

    def __init__(self, current=None, stroke_units: float = 0.0,
                 parent=None, tile_name=None,
                 tile_name_enabled: bool = True, tile_tags=None,
                 categories=None, tile_category="",
                 tile_face=None) -> None:
        super().__init__(tile_name if tile_name and tile_name_enabled
                         else amazetheme.TITLE_TILE_ICON,    # the WINDOW TITLE is the asset's own name, as drawn - a multi-selection has none, so it keeps the generic one
                         fixed_size=False, parent=parent)
        self._tile_name = tile_name   # None = the section has no rename at all; "" with tile_name_enabled False = a multi-selection, so the field greys out
        self._tile_name_enabled = bool(tile_name_enabled)
        self._tile_tags = tile_tags   # None = this section has no tags; on a multi-selection the field opens empty and ADDS
        self._categories = list(categories or [])   # None = this section has no categories, so no field at all
        self._tile_category = tile_category or ""
        self._tile_face = tile_face   # the tile's CURRENT grid face - what the preview shows while Custom Icon is off
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

        content = QtWidgets.QWidget()
        column = QtWidgets.QVBoxLayout(content)
        column.setContentsMargins(0, 0, 0, 0)   # the shell owns the outer margins
        column.setSpacing(0)                    # every gap below is a DRAWN number, added explicitly
        column.addLayout(self._build_fields())
        column.addSpacing(theme.ui_px(amazetheme.D02_TOP_GAP))
        column.addLayout(self._build_preview_block())
        column.addSpacing(theme.ui_px(amazetheme.D02_ROW_GAP))
        column.addWidget(self._build_search())
        column.addSpacing(theme.ui_px(amazetheme.D02_GRID_GAP))
        column.addWidget(self._build_chooser(), 1)   # the ONE part that grows on resize
        column.addSpacing(theme.ui_px(amazetheme.D02_BUTTON_GAP))
        column.addLayout(self._build_actions())
        self.set_content(content)
        margins = amazetheme.D02_MARGINS
        self.finish(ok_cancel=False,   # Apply and Accept are the drawn pair at the bottom
                    margins=(margins[0] + margins[2]) // 2)
        self._inner_layout.setContentsMargins(
            *(theme.ui_px(m) for m in margins))
        self.custom_toggle.toggled.connect(self._set_custom_enabled)
        self._set_custom_enabled(self._has_icon)
        self._refresh_preview()
        self.resize(theme.ui_px(amazetheme.D02_FORM_WIDTH),   # the drawn OPENING size; the grid is the part that grows if the user resizes
                    theme.ui_px(amazetheme.D02_FRAME_H))

    def _build_fields(self):
        """Name, Category and Tags stacked full width - the drawn top form."""
        field_h = theme.ui_px(amazetheme.D02_FIELD_H)
        form = QtWidgets.QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(theme.ui_px(amazetheme.D02_LABEL_GAP))
        form.setVerticalSpacing(theme.ui_px(amazetheme.D02_ROW_GAP))
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight
                               | QtCore.Qt.AlignmentFlag.AlignVCenter)
        form.setFieldGrowthPolicy(    # AllNonFixed, so the combo fills like the line edits ▸r/form-layout-defaults
            QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        if self._tile_name is None:
            self.tile_name_edit = None
        else:
            self.tile_name_edit = QtWidgets.QLineEdit(self._tile_name)
            self.tile_name_edit.setFixedHeight(field_h)
            self.tile_name_edit.setEnabled(self._tile_name_enabled)
            self.tile_name_edit.setToolTip(ui_helpers.tooltip_text(
                tooltips.CUSTOMIZE_TILE_NAME))
            form.addRow(amazetheme.LABEL_NAME, self.tile_name_edit)
        if not self._categories:
            self.category_combo = None
        else:
            self.category_combo = ui_helpers.DesignedComboBox()   # its dropdown holds the box's width ▸r/combo-popup-width
            self.category_combo.setFixedHeight(field_h)
            for name in self._categories:
                self.category_combo.addItem(name)
            self.category_combo.setCurrentText(self._tile_category)
            self.category_combo.setToolTip(ui_helpers.tooltip_text(
                tooltips.CUSTOMIZE_CATEGORY))
            form.addRow(amazetheme.LABEL_CATEGORY, self.category_combo)
        if self._tile_tags is None:
            self.tags_edit = None
        else:
            self.tags_edit = QtWidgets.QLineEdit(self._tile_tags)   # LIVE on a multi-selection: it opens empty and ADDS to every tile
            self.tags_edit.setFixedHeight(field_h)
            self.tags_edit.setToolTip(ui_helpers.tooltip_text(
                tooltips.CUSTOMIZE_TAGS_ONE_TILE
                if self._tile_name_enabled else
                tooltips.CUSTOMIZE_TAGS_MANY_TILES))
            form.addRow(amazetheme.LABEL_TAGS, self.tags_edit)
        return form

    def _build_search(self):
        """The icon filter, drawn at the bottom under the grid."""
        self.search = QtWidgets.QLineEdit()
        self.search.setFixedHeight(theme.ui_px(amazetheme.D02_FIELD_H))
        self.search.setPlaceholderText(amazetheme.PLACEHOLDER_SEARCH_ICONS)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        return self.search

    def _build_chooser(self):
        """The icon grid alone - the search sits ABOVE it since the overhaul, in the column that owns both."""
        chooser_bg = self.palette().color(   # the dialog's OWN window colour, so the grid is not a light island in it
            QtGui.QPalette.ColorRole.Window).name()
        icon_ink = theme.color_hex("text_bright")

        area = QtWidgets.QScrollArea()
        area.setWidgetResizable(True)
        area.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        holder = QtWidgets.QWidget()
        holder.setStyleSheet(    # the two px numbers are UNSCALED, like every stylesheet number in this file
            "QWidget { background: %s; }"
            " QToolButton { background: transparent; border: none;"
            " border-radius: %dpx; }"
            " QToolButton:hover { background: rgba(255, 255, 255, 28); }"
            " QToolButton:checked { background: %s;"
            " border: %dpx solid %s; }"
            % (chooser_bg, amazetheme.D02_CHOOSER_RADIUS,
               theme.color_hex("field"), amazetheme.D02_CHECKED_BORDER,
               icon_ink)
        )
        self._grid = QtWidgets.QGridLayout(holder)
        self._grid.setSpacing(amazetheme.D02_GRID_SPACING)
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
        area.setMinimumHeight(theme.ui_px(CELL * 4))    # HEIGHT only, a floor: the drawn 250 comes from the frame height, and a width minimum here once forced the whole window past the drawing
        self._chooser_area = area
        return area

    def _build_preview_block(self):
        """The preview square with the switch stack beside it - Custom Icon, Light Icon, the current-colour chip, the four presets. The stack's fixed heights sum to the preview's own 150."""
        block = QtWidgets.QHBoxLayout()
        block.setSpacing(theme.ui_px(amazetheme.D02_STACK_GAP))

        self.preview = QtWidgets.QLabel()
        self.preview.setFixedSize(theme.ui_px(amazetheme.D02_PREVIEW),
                                  theme.ui_px(amazetheme.D02_PREVIEW))
        self.preview.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        block.addWidget(self.preview,
                        alignment=QtCore.Qt.AlignmentFlag.AlignTop)

        stack = QtWidgets.QVBoxLayout()
        stack.setSpacing(0)

        def switch_row(label_text, tooltip):
            row = QtWidgets.QHBoxLayout()
            row.setSpacing(theme.ui_px(amazetheme.D02_LABEL_GAP))
            toggle = ui_helpers.ToggleSwitch()
            toggle.setToolTip(ui_helpers.tooltip_text(tooltip))
            row.addWidget(toggle)       # the pill sits LEFT since the 2026-08-30 redraw, its label 8px after - the Preferences rows' own shape
            label = QtWidgets.QLabel(label_text)
            label.setMinimumWidth(1)    # the label yields before the row overflows the column under a wide style's font
            row.addWidget(label)
            row.addStretch(1)
            return row, toggle

        row, self.custom_toggle = switch_row(
            amazetheme.LABEL_CUSTOM_ICON,
            tooltips.CUSTOMIZE_CUSTOM_ICON)
        self.custom_toggle.setChecked(self._has_icon)
        stack.addLayout(row)
        stack.addSpacing(theme.ui_px(amazetheme.D02_ROW_GAP))

        row, self.light_toggle = switch_row(
            amazetheme.LABEL_LIGHT_ICON,
            tooltips.CUSTOMIZE_LIGHT_ICON)
        self.light_toggle.setChecked(self._ink == "light")
        self.light_toggle.toggled.connect(self._set_ink_light)
        stack.addLayout(row)
        stack.addSpacing(theme.ui_px(amazetheme.D02_SECTION_GAP))

        colour_row = QtWidgets.QHBoxLayout()
        colour_row.setSpacing(theme.ui_px(amazetheme.D02_LABEL_GAP))
        self.custom_chip = QtWidgets.QToolButton()   # the chip IS the picker: it wears the current colour and opens Houdini's picker ▸r/houdini-colour-picker
        self.custom_chip.setFixedSize(theme.ui_px(amazetheme.D02_CHIP_W),
                                      theme.ui_px(amazetheme.D02_SWATCH_H))
        self.custom_chip.setToolTip(ui_helpers.tooltip_text(
            tooltips.CUSTOMIZE_CUSTOM_COLOR))
        self.custom_chip.clicked.connect(self._pick_custom)
        colour_row.addWidget(self.custom_chip)   # chip LEFT, label after - the 2026-08-30 redraw, like the switch rows above
        colour_label = QtWidgets.QLabel(amazetheme.LABEL_CUSTOM_COLOR)
        colour_label.setMinimumWidth(1)
        colour_row.addWidget(colour_label)
        colour_row.addStretch(1)
        stack.addLayout(colour_row)
        stack.addSpacing(theme.ui_px(amazetheme.D02_PRESET_GAP))

        swatches = QtWidgets.QHBoxLayout()   # expanding widths and NO stretch, so the four share exactly the stack width
        swatches.setSpacing(theme.ui_px(amazetheme.D02_SWATCH_GAP))
        self._swatches = []
        for label, colour in tile_icons.PRESETS:
            swatch = QtWidgets.QToolButton()
            swatch.setToolTip(label)
            swatch.setFixedHeight(theme.ui_px(amazetheme.D02_SWATCH_H))
            swatch.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Expanding,
                QtWidgets.QSizePolicy.Policy.Fixed,
            )
            swatch.setStyleSheet(
                "background:%s; border:%dpx solid #222;"
                % (colour, amazetheme.D02_SWATCH_BORDER))
            swatch.clicked.connect(
                lambda _checked=False, picked=colour: self._set_bg(picked))
            swatches.addWidget(swatch)
            self._swatches.append(swatch)
        stack.addLayout(swatches)
        stack.addStretch(1)
        block.addLayout(stack, 1)
        self._refresh_chip()
        return block

    def _refresh_chip(self) -> None:
        self.custom_chip.setStyleSheet(
            "background:%s; border:%dpx solid #222;"
            % (self._bg, amazetheme.D02_SWATCH_BORDER))

    def _set_ink_light(self, on: bool) -> None:
        self._ink = "light" if on else "dark"
        self._refresh_preview()

    def _build_actions(self):
        actions = QtWidgets.QHBoxLayout()   # Apply commits and stays open, Accept commits and closes - Houdini's own pair (ref ▸ windows/optype); closing IS cancelling, so there is no Cancel
        actions.setSpacing(theme.ui_px(amazetheme.D02_SWATCH_GAP))
        actions.addStretch(1)               # both drawn flush RIGHT at a fixed size, not spanning the column
        self.apply_button = QtWidgets.QPushButton(amazetheme.BTN_APPLY)
        self.apply_button.setFixedSize(theme.ui_px(amazetheme.D02_BUTTON_W),
                                       theme.ui_px(amazetheme.D02_FIELD_H))
        self.apply_button.clicked.connect(self._apply)
        actions.addWidget(self.apply_button)

        self.accept_button = QtWidgets.QPushButton(amazetheme.BTN_ACCEPT)
        self.accept_button.setFixedSize(theme.ui_px(amazetheme.D02_BUTTON_W),
                                        theme.ui_px(amazetheme.D02_FIELD_H))
        self.accept_button.setDefault(True)
        self.accept_button.clicked.connect(self._accept)
        actions.addWidget(self.accept_button)
        return actions

    def _set_custom_enabled(self, on: bool) -> None:
        """The chooser follows the toggle; Name, Category and Tags do not - they are the asset's, not the icon's. The preview stays live either way: off, it shows the tile's current face."""
        for widget in (self._chooser_area, self.search, self.custom_chip,
                       self.light_toggle, *self._swatches):
            widget.setEnabled(bool(on))
        self._refresh_preview()


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
            self._refresh_chip()
            self._refresh_preview()

    def _pick_custom(self) -> None:
        """Houdini's colour picker, reachable ONLY because this dialog holds no exec loop. ▸r/houdini-colour-picker"""
        chosen = ui_helpers.pick_color(self._bg, self, "Tile Background")
        if chosen is not None:
            self._set_bg(chosen.name())

    def _refresh_preview(self) -> None:
        button = self._buttons_by_name.get(self._name)
        if button is not None and not button.isChecked():
            button.setChecked(True)
        if self.custom_toggle.isChecked():
            image = tile_icons.compose(self._name, self._bg, 256,
                                       self._stroke, self._ink)
        else:
            image = self._tile_face   # off = what the grid shows today: the render, the swatches, the painted code
        if image is None:
            self.preview.clear()
            return
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
