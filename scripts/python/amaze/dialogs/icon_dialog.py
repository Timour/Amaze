"""Customize as a widget window on `pane.customize`: show it, never exec. ▸r/houdini-colour-picker"""

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
    """Not modal: Apply commits and stays open, Accept closes and then commits. ▸r/accept-apply"""

    FORM_WIDTH = amazetheme.D02_FORM_WIDTH
    FRAME_KEY = "D02"     # the fixed-size parts only; the fields, search and grid stretch

    def __init__(self, engine, parent=None) -> None:
        super().__init__(engine.title, fixed_size=False, parent=parent)
        self.engine = engine    # what this window shows and commits; Qt deletes it with the window
        engine.setParent(self)
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
        self.face_combo.currentIndexChanged.connect(
            lambda _row: engine.set_face(self.face_combo.currentData()))
        engine.changed.connect(self._show_choices)
        engine.listed.connect(self._show_icons)
        self.finished.connect(self._closed)
        self._show_choices()
        self.resize(theme.ui_px(amazetheme.D02_FORM_WIDTH),   # the drawn OPENING size; the grid is the part that grows if the user resizes
                    theme.ui_px(amazetheme.D02_FRAME_H))

    def _build_fields(self):
        """Name, Category and Tags stacked full width - the drawn top form."""
        engine = self.engine
        field_h = theme.ui_px(amazetheme.D02_FIELD_H)
        form = QtWidgets.QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(theme.ui_px(amazetheme.D02_LABEL_GAP))
        form.setVerticalSpacing(theme.ui_px(amazetheme.D02_ROW_GAP))
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight
                               | QtCore.Qt.AlignmentFlag.AlignVCenter)
        form.setFieldGrowthPolicy(    # AllNonFixed, so the combo fills like the line edits ▸r/form-layout-defaults
            QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        if engine.name is None:
            self.tile_name_edit = None
        else:
            self.tile_name_edit = QtWidgets.QLineEdit(engine.name)
            self.tile_name_edit.setFixedHeight(field_h)
            self.tile_name_edit.setEnabled(engine.name_enabled)
            self.tile_name_edit.setToolTip(ui_helpers.tooltip_text(
                tooltips.CUSTOMIZE_TILE_NAME))
            form.addRow(amazetheme.LABEL_NAME, self.tile_name_edit)
        if not engine.categories:
            self.category_combo = None
        else:
            self.category_combo = ui_helpers.DesignedComboBox()   # its dropdown keeps the box's width ▸r/combo-popup-width
            self.category_combo.setFixedHeight(field_h)
            base_dialog.fill_categories(self.category_combo, engine.categories, engine.category)
            self.category_combo.setToolTip(ui_helpers.tooltip_text(
                tooltips.CUSTOMIZE_CATEGORY))
            form.addRow(amazetheme.LABEL_CATEGORY, self.category_combo)
        if engine.tags is None:
            self.tags_edit = None
        else:
            self.tags_edit = QtWidgets.QLineEdit(engine.tags)
            self.tags_edit.setFixedHeight(field_h)
            self.tags_edit.setToolTip(ui_helpers.tooltip_text(engine.tags_tip))
            form.addRow(amazetheme.LABEL_TAGS, self.tags_edit)
        return form

    def _build_search(self):
        """The icon filter, placed above the grid."""
        self.search = QtWidgets.QLineEdit()
        self.search.setFixedHeight(theme.ui_px(amazetheme.D02_FIELD_H))
        self.search.setPlaceholderText(amazetheme.PLACEHOLDER_SEARCH_ICONS)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.engine.search)
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
        icon_px = theme.ui_px(amazetheme.D02_CELL_ART)
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
                lambda _checked=False, chosen=name: self.engine.choose_icon(chosen))
            group.addButton(button)
            self._buttons_by_name[name] = button
        self._redraw_icons_for_screen()      # called again in showEvent, once the window has a screen ▸r/screen-dpr
        self._relayout(self.engine.icons)

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
        for position, (face, label, offered) in enumerate(self.engine.faces):
            self.face_combo.addItem(label, face)
            self.face_combo.model().item(position).setEnabled(offered)    # greyed where it cannot be chosen
        self.face_combo.setCurrentIndex(self.face_combo.findData(self.engine.face))
        face_row.addWidget(self.face_combo)
        face_row.addStretch(1)
        stack.addLayout(face_row)
        stack.addSpacing(theme.ui_px(amazetheme.D02_SECTION_GAP))

        row, self.light_toggle = switch_row(
            amazetheme.LABEL_LIGHT_ICON,
            tooltips.CUSTOMIZE_LIGHT_ICON)
        self.light_toggle.setChecked(self.engine.is_light())
        self.light_toggle.toggled.connect(self.engine.set_light)
        stack.addLayout(row)
        stack.addSpacing(theme.ui_px(amazetheme.D02_ROW_GAP))

        colour_row = QtWidgets.QHBoxLayout()
        colour_row.setSpacing(theme.ui_px(amazetheme.D02_SWATCH_GAP))   # the drawn 6: the chip is swatch-sized and the row uses the swatch spacing
        self.custom_chip = QtWidgets.QToolButton()   # shows the current colour, opens the picker ▸r/houdini-colour-picker
        self.custom_chip.setToolTip(ui_helpers.tooltip_text(
            tooltips.CUSTOMIZE_CUSTOM_COLOR))
        self.custom_chip.clicked.connect(self.engine.pick_colour)
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
                lambda _checked=False, picked=colour: self.engine.set_background(picked))
            swatches.addWidget(swatch)
            self._swatches.append(swatch)
        ui_helpers.fit_drawn_series(   # the chip is drawn first, above the four
            [self.custom_chip] + self._swatches, self.FRAME_KEY,
            "QToolButton")
        stack.addLayout(swatches)
        stack.addStretch(1)
        block.addLayout(stack, 1)
        return block

    def _build_actions(self):
        actions = QtWidgets.QHBoxLayout()   # Apply stays open, Accept closes; closing cancels ▸r/accept-apply
        actions.setSpacing(theme.ui_px(amazetheme.D02_SWATCH_GAP))
        actions.addStretch(1)               # both drawn flush RIGHT at a fixed size, not spanning the column
        self.apply_button = QtWidgets.QPushButton(amazetheme.BTN_APPLY)
        self.apply_button.clicked.connect(self._commit)    # `canceled` stays True: a later X commits nothing
        actions.addWidget(self.apply_button)

        self.accept_button = QtWidgets.QPushButton(amazetheme.BTN_ACCEPT)
        ui_helpers.fit_drawn_series((self.apply_button, self.accept_button),
                                    self.FRAME_KEY, "QPushButton")
        self.accept_button.setDefault(True)
        self.accept_button.clicked.connect(self._on_accept)
        actions.addWidget(self.accept_button)
        return actions

    def _show_choices(self) -> None:
        """The engine's choices shown: what is enabled, the chip, the checked icon and the preview."""
        engine = self.engine
        for widget in (self._chooser_area, self.search, self.custom_chip,
                       self.light_toggle, *self._swatches):
            widget.setEnabled(engine.is_custom())
        chip = "background:%s; border:%dpx solid #222;" % (engine.background, amazetheme.D02_SWATCH_BORDER)
        if chip != self.custom_chip.styleSheet():
            self.custom_chip.setStyleSheet(chip)
        button = self._buttons_by_name.get(engine.icon)
        if button is not None and not button.isChecked():
            button.setChecked(True)
        image = engine.preview()
        if image is None:
            self.preview.clear()
            return
        self.preview.setPixmap(QtGui.QPixmap.fromImage(image).scaled(
            self.preview.size(),
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        ))

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

    def _show_icons(self) -> None:
        """Show the icons the engine lists, in its order."""
        listed = self.engine.icons
        visible = set(listed)
        for name, button in self._buttons_by_name.items():
            button.setVisible(name in visible)
        self._relayout(listed)

    def _commit(self) -> None:
        """The fields as typed go to the engine, which hands on what changed."""
        self.engine.commit(
            self.tile_name_edit.text() if self.tile_name_edit is not None else "",
            self.tags_edit.text() if self.tags_edit is not None else "",
            base_dialog.chosen_category(self.category_combo)    # its key, never the name shown
            if self.category_combo is not None else "")

    def _closed(self, _result=0) -> None:
        """Accept closed the window: its edits are committed. Any other close commits nothing."""
        if not self.canceled:
            self._commit()
