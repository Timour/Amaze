"""Pick a tile icon and its background colour. Show it, never exec. ▸r/houdini-colour-picker"""

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
    """Non-modal icon and colour picker: result in `spec`, Apply emits `applied`. ▸r/accept-apply"""

    FORM_WIDTH = amazetheme.D02_FORM_WIDTH
    FRAME_KEY = "D02"     # the fixed-size parts only; the fields, search and grid stretch

    applied = QtCore.Signal()

    def __init__(self, current=None, stroke_units: float = 0.0,
                 parent=None, tile_name=None,
                 tile_name_enabled: bool = True, tile_tags=None,
                 categories=None, tile_category="",
                 face=None, faces=None, can_preview=True) -> None:
        super().__init__(tile_name if tile_name and tile_name_enabled
                         else amazetheme.TITLE_TILE_ICON,    # the asset's name; a multi-selection keeps the generic one
                         fixed_size=False, parent=parent)
        self._tile_name = tile_name   # None = no rename; "" with tile_name_enabled False = greyed field
        self._tile_name_enabled = bool(tile_name_enabled)
        self._tile_tags = tile_tags   # None = this section has no tags; on a multi-selection the field opens empty and ADDS
        self._categories = list(categories or [])   # None = this section has no categories, so no field at all
        self._tile_category = tile_category or ""
        self._face = face if face in tile_icons.FACES else tile_icons.face_of(
            tile_icons.normalise(current))    # what the tile shows now
        self._faces = dict(faces or {})    # {face: image} for the preview square
        self._can_preview = bool(can_preview)
        self.new_tile_name = None
        self.new_tags = None
        self.new_category = None    # NOT greyed on a multi-selection: moving a whole selection to one category is the point of it
        self._stroke = stroke_units or tile_icons.STROKE_UNITS
        current = tile_icons.normalise(current)
        self.spec = dict(current)
        self._name = current.get("name", "") or "box"
        self._bg = current.get("bg", "") or tile_icons.PRESETS[0][1]
        self._icon_shade = current.get("ink", "") or tile_icons.DEFAULT_INK
        self._buttons_by_name: dict = {}

        content = QtWidgets.QWidget()
        column = QtWidgets.QVBoxLayout(content)
        column.setContentsMargins(0, 0, 0, 0)   # AssetDialog.finish sets the outer margins
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
        self.face_combo.currentIndexChanged.connect(self._face_changed)
        self._face_changed()
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
            self.category_combo = ui_helpers.DesignedComboBox()   # its dropdown keeps the box's width ▸r/combo-popup-width
            self.category_combo.setFixedHeight(field_h)
            base_dialog.fill_categories(self.category_combo,
                                        self._categories, self._tile_category,
                                        blank=True)    # mixed or none: an empty first row that changes no category
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
        """The icon filter, placed above the grid."""
        self.search = QtWidgets.QLineEdit()
        self.search.setFixedHeight(theme.ui_px(amazetheme.D02_FIELD_H))
        self.search.setPlaceholderText(amazetheme.PLACEHOLDER_SEARCH_ICONS)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        return self.search

    def _build_chooser(self):
        """The icon grid only; the search field is ABOVE it, in the column that holds both."""
        chooser_bg = self.palette().color(   # the dialog's OWN window colour, so the grid is not a lighter area in it
            QtGui.QPalette.ColorRole.Window).name()
        icon_color = theme.color_hex("text_bright")

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
               icon_color)
        )
        self._grid = QtWidgets.QGridLayout(holder)
        self._grid.setSpacing(amazetheme.D02_GRID_SPACING)
        self._grid.setContentsMargins(0, 0, 0, 0)

        group = QtWidgets.QButtonGroup(self)   # every button is built once; the filter only shows or hides
        group.setExclusive(True)
        icon_px = theme.ui_px(CELL - 14)
        self._icon_px = icon_px
        self._icon_color = icon_color
        self._icon_dpr = None                             # the device pixel ratio of the current icons; None until first drawn ▸r/screen-dpr
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
        self._redraw_icons_for_screen()      # called again in showEvent, once the window has a screen ▸r/screen-dpr
        self._relayout(tile_icons.icon_names())

        area.setStyleSheet("QScrollArea { background: %s; border: none; }"
                           % chooser_bg)
        area.setWidget(holder)
        area.setMinimumHeight(theme.ui_px(CELL * 4))    # a height floor only; never set a width minimum here
        self._chooser_area = area
        return area

    def _build_preview_block(self):
        """The preview square beside the stack: the Image menu, Light Icons, the colour chip, presets."""
        block = QtWidgets.QHBoxLayout()
        block.setSpacing(theme.ui_px(amazetheme.D02_STACK_GAP))

        self.preview = QtWidgets.QLabel()
        ui_helpers.fit_drawn(self.preview, self.FRAME_KEY, "QLabel", None)
        self.preview.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        preview_column = QtWidgets.QVBoxLayout()
        preview_column.setSpacing(0)
        preview_column.addSpacing(theme.ui_px(amazetheme.D02_PREVIEW_DROP))
        preview_column.addWidget(self.preview)
        preview_column.addStretch(1)
        block.addLayout(preview_column)

        stack = QtWidgets.QVBoxLayout()
        stack.setSpacing(0)

        def switch_row(label_text, tooltip):
            row = QtWidgets.QHBoxLayout()
            row.setSpacing(theme.ui_px(amazetheme.D02_LABEL_GAP))
            toggle = ui_helpers.ToggleSwitch()
            toggle.setToolTip(ui_helpers.tooltip_text(tooltip))
            row.addWidget(toggle)       # the switch on the left, its label after
            label = QtWidgets.QLabel(label_text)
            label.setMinimumWidth(1)    # the label shrinks before the row overflows the column under a wide style's font
            row.addWidget(label)
            row.addStretch(1)
            return row, toggle

        face_row = QtWidgets.QHBoxLayout()    # the Image menu: Render, Capture, Generic, Custom
        face_row.setSpacing(theme.ui_px(amazetheme.D02_FACE_GAP))
        face_label = QtWidgets.QLabel(amazetheme.LABEL_ICON)
        ui_helpers.fit_drawn(face_label, self.FRAME_KEY, "QLabel", amazetheme.LABEL_ICON,
                             height=False, grow=True)
        face_row.addWidget(face_label)
        self.face_combo = ui_helpers.DesignedComboBox()
        ui_helpers.fit_drawn(self.face_combo, self.FRAME_KEY, "QComboBox", None, nth=1)
        self.face_combo.setToolTip(ui_helpers.tooltip_text(tooltips.CUSTOMIZE_ICON))
        for face, label in zip(tile_icons.FACES, amazetheme.FACE_LABELS):
            self.face_combo.addItem(label, face)
        offered = {"image": self._can_preview}    # a row with no picture greys Image
        for position, face in enumerate(tile_icons.FACES):
            self.face_combo.model().item(position).setEnabled(offered.get(face, True))
        self.face_combo.setCurrentIndex(tile_icons.FACES.index(self._face))
        face_row.addWidget(self.face_combo)
        face_row.addStretch(1)
        stack.addLayout(face_row)
        stack.addSpacing(theme.ui_px(amazetheme.D02_SECTION_GAP))

        row, self.light_toggle = switch_row(
            amazetheme.LABEL_LIGHT_ICON,
            tooltips.CUSTOMIZE_LIGHT_ICON)
        self.light_toggle.setChecked(self._icon_shade == "light")
        self.light_toggle.toggled.connect(self._set_icon_light)
        stack.addLayout(row)
        stack.addSpacing(theme.ui_px(amazetheme.D02_ROW_GAP))

        colour_row = QtWidgets.QHBoxLayout()
        colour_row.setSpacing(theme.ui_px(amazetheme.D02_SWATCH_GAP))   # the drawn 6: the chip is swatch-sized and the row uses the swatch spacing
        self.custom_chip = QtWidgets.QToolButton()   # shows the current colour, opens the picker ▸r/houdini-colour-picker
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

        swatches = QtWidgets.QHBoxLayout()   # the drawn widths and NO stretch, so the four share exactly the stack width
        swatches.setSpacing(theme.ui_px(amazetheme.D02_SWATCH_GAP))
        self._swatches = []
        for label, colour in tile_icons.PRESETS:
            swatch = QtWidgets.QToolButton()
            swatch.setToolTip(label)
            swatch.setStyleSheet(
                "background:%s; border:%dpx solid #222;"
                % (colour, amazetheme.D02_SWATCH_BORDER))
            swatch.clicked.connect(
                lambda _checked=False, picked=colour: self._set_bg(picked))
            swatches.addWidget(swatch)
            self._swatches.append(swatch)
        ui_helpers.fit_drawn_series(   # the chip is drawn first, above the four
            [self.custom_chip] + self._swatches, self.FRAME_KEY,
            "QToolButton")
        stack.addLayout(swatches)
        stack.addStretch(1)
        block.addLayout(stack, 1)
        self._refresh_chip()
        return block

    def _refresh_chip(self) -> None:
        self.custom_chip.setStyleSheet(
            "background:%s; border:%dpx solid #222;"
            % (self._bg, amazetheme.D02_SWATCH_BORDER))

    def _set_icon_light(self, on: bool) -> None:
        self._icon_shade = "light" if on else "dark"
        self._refresh_preview()

    def _build_actions(self):
        actions = QtWidgets.QHBoxLayout()   # Apply stays open, Accept closes; closing cancels ▸r/accept-apply
        actions.setSpacing(theme.ui_px(amazetheme.D02_SWATCH_GAP))
        actions.addStretch(1)               # both drawn flush RIGHT at a fixed size, not spanning the column
        self.apply_button = QtWidgets.QPushButton(amazetheme.BTN_APPLY)
        self.apply_button.clicked.connect(self._apply)
        actions.addWidget(self.apply_button)

        self.accept_button = QtWidgets.QPushButton(amazetheme.BTN_ACCEPT)
        ui_helpers.fit_drawn_series((self.apply_button, self.accept_button),
                                    self.FRAME_KEY, "QPushButton")
        self.accept_button.setDefault(True)
        self.accept_button.clicked.connect(self._accept)
        actions.addWidget(self.accept_button)
        return actions

    def _face_changed(self, _index=None) -> None:
        """Only Custom has an icon and colours to choose; Name, Category and Tags are the asset's."""
        custom = self.face_combo.currentData() == "custom"
        for widget in (self._chooser_area, self.search, self.custom_chip,
                       self.light_toggle, *self._swatches):
            widget.setEnabled(custom)
        self._refresh_preview()


    def showEvent(self, event) -> None:
        """Redraw the grid icons for the screen the dialog opened on. ▸r/screen-dpr"""
        super().showEvent(event)
        self._redraw_icons_for_screen()

    def _redraw_icons_for_screen(self) -> None:
        """Redraw the chooser icons when this window's ratio differs from the icons' ratio."""
        dpr = float(self.devicePixelRatioF())
        if dpr == self._icon_dpr:
            return
        self._icon_dpr = dpr
        for name, button in self._buttons_by_name.items():
            button.setIcon(QtGui.QIcon(self._chooser_icon(
                name, self._icon_px, dpr, self._icon_color)))

    @staticmethod
    def _chooser_icon(name: str, icon_px, dpr: float, color: str):
        """One chooser icon: the Feather SVG recoloured, rendered at device pixels, ratio set."""
        return ui_helpers.device_pixmap(
            tile_icons.icon_path(name), icon_px, dpr, {"currentColor": color})

    def _relayout(self, names) -> None:
        while self._grid.count():
            self._grid.takeAt(0)
        for position, name in enumerate(names):
            self._grid.addWidget(self._buttons_by_name[name],
                                 position // COLUMNS, position % COLUMNS)

    def _apply_filter(self, text: str) -> None:
        """Show the icons whose name contains `text`."""
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
        """Houdini's colour picker; needs this dialog to hold no exec loop. ▸r/houdini-colour-picker"""
        chosen = ui_helpers.pick_color(self._bg, self, "Tile Background")
        if chosen is not None:
            self._set_bg(chosen.name())

    def _refresh_preview(self) -> None:
        button = self._buttons_by_name.get(self._name)
        if button is not None and not button.isChecked():
            button.setChecked(True)
        face = self.face_combo.currentData()
        if face == "custom":
            image = tile_icons.compose(self._name, self._bg, 256,
                                       self._stroke, self._icon_shade)
        else:
            image = self._faces.get(face) or self._faces.get("generic")    # no picture yet: generic
        if image is None:
            self.preview.clear()
            return
        self.preview.setPixmap(QtGui.QPixmap.fromImage(image).scaled(
            self.preview.size(),
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        ))

    def _read_tile_name(self) -> None:
        """The new name, or None when the field is absent, greyed, blank or unchanged."""
        if self.tile_name_edit is None or \
                not self.tile_name_edit.isEnabled():
            return
        text = self.tile_name_edit.text().strip()
        if text and text != (self._tile_name or ""):
            self.new_tile_name = text

    def _read_tags(self) -> None:
        """The tag line to write, or None when absent, greyed or unchanged; an empty field clears the tags."""
        if self.tags_edit is None or not self.tags_edit.isEnabled():
            return
        text = self.tags_edit.text().strip()
        if text != (self._tile_tags or "").strip():
            self.new_tags = text

    def _read_category(self) -> None:
        """The category to move to, or None when the field is absent, blank or unchanged."""
        if self.category_combo is None:
            return
        chosen = base_dialog.chosen_category(self.category_combo)    # STORED, never the label
        if chosen and chosen != (self._tile_category or "").strip():
            self.new_category = chosen

    def _read_fields(self) -> None:
        """Everything a commit writes: the chosen face, and the name, tags and category."""
        self.new_tile_name = self.new_tags = self.new_category = None    # reset: only THIS commit's values
        face = self.face_combo.currentData()
        if face == "custom":
            self.spec = tile_icons.normalise(
                {"name": self._name, "bg": self._bg, "ink": self._icon_shade})
        else:
            self.spec = {"face": face}    # the model stores it only where it is not the default
        self._read_tile_name()
        self._read_tags()
        self._read_category()

    def _apply(self) -> None:
        """Commit and STAY OPEN; `canceled` stays True, so a later X re-applies nothing."""
        self._read_fields()
        self.applied.emit()
        self._keep_committed_values()

    def _keep_committed_values(self) -> None:
        """What Apply just committed is what the next commit compares against."""
        if self.new_tile_name is not None:
            self._tile_name = self.new_tile_name
        if self.new_tags is not None:
            self._tile_tags = self.new_tags
        if self.new_category is not None:
            self._tile_category = self.new_category

    def _accept(self) -> None:
        self._read_fields()
        self._on_accept()
