"""THE DESIGN, in ONE document: every colour, size, placement and word the DESIGNS fix and Houdini's theme does NOT own, so a Figma change is one edit. `helpers/theme.py` holds what FOLLOWS Houdini's live theme; sizes here are the design's number HALVED and go through `theme.ui_px` AT THE CALL SITE. ▸p/one-design-document"""

from __future__ import annotations

HEADER_BAND_H = 30       # ▸ THE DRAWN HEADER: a full-width strip carrying the asset's own name, on D01, D02 and D11 and nowhere else. Its fill and ink follow Houdini (`surface_low`, `text_bright`), so only the geometry is here
HEADER_BAND_INSET = 18   # where the name starts
HEADER_BAND_TEXT_PX = 12
HEADER_BAND_TEXT_BOLD = True    # the drawn weight on D01, D02 and D11

HOUSE_MARGIN = 5         # ▸ the content margin every compact form dialog wears; a dialog records its reason at the call to differ

D01_FRAME = (256, 185)      # ▸ D01 Versions, header band included
D01_INSET = 18              # 35, both sides, leaving a 220-wide column
D01_FIRST_FIELD_Y = 15      # 30, the first field's top
D01_BUTTON_GAP = 19         # 38
D01_RADIUS = 5              # 10
D01_LABEL_PX = 10
D01_BUTTON_PX = 12
D01_LABEL_INK = "#93b9e7"   # the accent-blue field label, e.g. Change Name

D02_FORM_WIDTH = 335     # ▸ D02 Customize (Tile Icon): ONE narrow column since the 2026-08-27 overhaul; band included
D02_FRAME_H = 610        # the drawn OPENING height; the dialog stays resizable and the grid is the part that grows
D02_MARGINS = (8, 6, 8, 12)   # left, top-under-band, right, bottom
D02_CELL = 34            # one icon button in the chooser grid
D02_COLUMNS = 8          # what the drawn 319 grid column fits at 2px spacing
D02_FIELD_H = 22         # every field, the search and both buttons
D02_SWATCH_GAP = 6
D02_BUTTON_W = 72        # Apply and Accept, drawn flush right - they do NOT span the column
D02_CHIP_W = 35          # the current-colour chip beside the Custom Color label - swatch-sized since the 2026-08-30 redraw; clicking it IS the picker
D02_STACK_GAP = 13       # preview to the switch stack, and its label column to its fields
D02_ROW_GAP = 9          # between the stacked field rows, and the column rhythm below them
D02_LABEL_GAP = 8        # a label to its field in the top form
D02_GRID_GAP = 6         # search to the grid
D02_SECTION_GAP = 37     # the Icon menu's row to the Light Icon row
D02_PRESET_GAP = 10      # the current-colour chip to the preset row
D02_TOP_GAP = 9          # the Tags row to the Icon menu
D02_PREVIEW_DROP = 2     # the Icon menu's top to the preview square's
D02_BUTTON_GAP = 8       # grid to the button row
D02_GRID_SPACING = 2     # the chooser grid's cell gap, UNSCALED: D02_COLUMNS is the count the drawn 319 column fits at exactly this gap
D02_CHOOSER_RADIUS = 3   # an icon button's corner, UNSCALED - a stylesheet px, like the two below
D02_CHECKED_BORDER = 2   # the ring on the chosen icon, UNSCALED
D02_SWATCH_BORDER = 1    # the preset chips and the current-colour chip, UNSCALED

SAVE_WIDTH = 350         # ▸ the save family D09 and D13: both are this wide, whatever its labels. D10/D12 retired 2026-08-30 - one save engine, D09 is THE save dialog
D14_WIDTH = 369          # ▸ D14 User Picker, the family's shape 19 wider: `Existing Users` is 69 and the family's label column is 60, so the column takes the 19 and the field keeps its 276
D14_LABEL_RIGHT = 79     # where D14's label column ends, the family's 60 plus that 19
SAVE_FIELD_WIDTH = 276   # the drawn field width inside it
SAVE_FRAME_H = {"D09": 177, "D13": 72, "D14": 100}   # each frame's drawn height; the row count is the only difference between them
SAVE_LABEL_RIGHT = 60    # a label is RIGHT-aligned and ends here
SAVE_FIELD_X = 67        # every field starts here; 67 + 276 = 343, so the right inset is 7
SAVE_FIRST_ROW_Y = 11    # the first field's top
SAVE_FIELD_H = 22
SAVE_ROW_PITCH = 26      # field top to field top
SAVE_BUTTON_H = 22       # the OK / Cancel pair, drawn flush right
SAVE_BUTTON_W = (31, 50)  # OK, Cancel
SAVE_BUTTON_GAP = 8
SAVE_BUTTON_RIGHT = 343  # Cancel's right edge, level with the fields'
SAVE_BUTTON_BOTTOM = 9   # the button row's bottom to the frame's, on D09/D10/D12; D13 draws 11 and is the odd one

D11_FORM_WIDTH = 638     # ▸ D11 Save Code: a FLOOR, not a pin - the only dialog that resizes, because it carries an editor
D11_EDITOR_H = 364       # the editor's minimum HEIGHT; it spans the full content width, under the two-column form
D11_MARGINS = (18, 19, 8, 13)  # left, top-under-band, right, bottom
D11_FIELD_H = 22         # every field and button in the frame
D11_ROW_GAP = 4          # between the two form rows
D11_LABEL_GAP = 7        # label to its field
D11_HALF_GAP = 18        # between the two form halves
D11_STACK_GAP = 12       # fields to the editor
D11_BUTTON_GAP = 8       # editor to the OK/Cancel row

PREFS_FRAME = (498, 451)    # ▸ D04-D08 Preferences, the one tabbed window - the drawn frame, every tab. The width carries Qt's 8 for a tab widget, which no widget draws and every such frame must leave room for ▸r/tabwidget-adds-eight
PREFS_FORM_WIDTH = 490   # the frame's width, kept under its old name because call sites use it
PREFS_INSET = 20         # content to the frame edge, both sides: rows span 20..470
PREFS_DIALOG_MARGIN = 12  # the tabbed window's own margin, outside the tab strip
PREFS_PAGE_MARGIN = 8    # each tab page's margin, inside it: 12 + 8 is the drawn 20
PREFS_CONTENT_WIDTH = 450  # the drawn content column, spanned by every row and divider: 20..470. PINNED, because the page is handed more than this - Qt makes the window 8 wider than the tab widget needs and then lets the page use all of it ▸r/tabwidget-adds-eight
PREFS_TAB_BAR = (12, 12, 466, 22)   # x, y, w, h - the strip above every page
PREFS_CONTENT_TOP = 42   # the first row's top, under the tab bar
PREFS_LABEL_RIGHT = 140  # a form label is RIGHT-aligned and ends here
PREFS_LABEL_COL = 120    # the label column itself, from the inset to LABEL_RIGHT
PREFS_LABEL_GAP = 8      # a label to its field: FIELD_X less LABEL_RIGHT
PREFS_FIELD_X = 148      # every field, button and toggle column starts here
PREFS_FIELD_H = 22       # a line edit, combo or button
PREFS_SPIN_H = 24        # a spin box is 2 taller, its inner line edit inset 1
PREFS_TOGGLE_H = 19      # a ToggleSwitch
PREFS_ROW_GAP = 6        # between rows inside one group
PREFS_BUTTON_GAP = 8     # between two controls sharing one row, and a spin box to its slider
PREFS_SECTION_GAP = 27   # across a divider, bottom of one row to top of the next
PREFS_BROWSE_W = 28      # the `...` button that opens a file dialog
PREFS_DIVIDER_INK = "#434343"   # the 1px group divider; groups carry no title, like Houdini's own parameter panes
PREFS_DIVIDER_H = 1
PREFS_DIVIDER_ABOVE = 8  # inside the divider's own row box
PREFS_DIVIDER_BELOW = 6  # so a divider costs ROW_GAP + ABOVE + H + BELOW + ROW_GAP = PREFS_SECTION_GAP

COMMENT_INK = "#1e8051"        # ▸ the Comments pane (N01): the header icon's art colour
COMMENT_DONE_INK = "#4af2a1"   # a done to-do
COMMENT_OPEN_INK = "#ff7760"   # an open to-do
COMMENT_ADD_INK = "#5d7abd"    # the + art's colour
COMMENT_HEADER_BG = "#262626"
COMMENT_PAGE_BG = "#2d2d2d"
COMMENT_DIM_NAME = "Nothing Selected"   # ▸ nothing selected (N01B): the header's two labels,
COMMENT_DIM_TYPE = "Type"
COMMENT_DIM_TEXT_OPACITY = 0.5          # drawn at half their usual ink
COMMENT_DIM_ICON_OPACITY = 0.25         # the speech bubble
COMMENT_DIM_ADD_INK = "#565656"         # the + art; Houdini's menu triangle keeps its colour

LIST_HEADER_BG = "#2a2a2a"       # ▸ list mode's header strip: a QHeaderView picks up none of these, so the strip states them
LIST_HEADER_DIVIDER = "#454545"

TILE_TEXT = "#cdc8bc"           # ▸ the tile and list delegates
TILE_SUBTITLE = "#5d7abd"       # the accent DEFAULT only - overwritten per instance from `prefs.accent_color`
CODE_TEXT_OPACITY = 0.5         # T05B: a code tile's text at half strength, under its run button
BADGE_REST_OPACITY = 0.75       # every button badge at rest, ground and icon alike
BADGE_HOVER_OPACITY = 1.0       # and under the pointer
LIST_INK = "#d8d6d4"            # a table is read down its columns, so every column paints in this except Category
LIST_SELECTED_TEXT = "#000000"  # selection turns EVERY column black: the palette's highlightedText was not reliably dark against the amber highlight
BAND_TEXT_DARK = "#262626"      # text on a coloured band; a category colour can be any lightness at all
BAND_TEXT_LIGHT = "#f0eeee"

SLIDER_LEFT = "#5d7abd"         # ▸ the slider, the tabs and the icon-menu button. Also the project accent default, which `set_accent_color` overrides at runtime
SLIDER_HANDLE = "#777f95"
SLIDER_TRACK = "#1a1a1a"        # the progress track's OWN colour, never the slider's, so one tweak cannot recolour both
TAB_TEXT_HOVER = "#cccdcd"      # not in the design, which draws no tab hover state - matching the toolbar icons' hover
MENU_IDLE_BODY = "#5d7abd"
MENU_LIT_BODY = "#cccdcd"
MENU_IDLE_TRIANGLE = "#7f807f"
MENU_LIT_TRIANGLE = "#a5b3d4"
MENU_PUNCH_OUT = "#2d2d2d"
MENU_OPEN_PUNCH_OUT = "#2d4075"
MENU_HOVER_PUNCH_OUT = "#424142"
MENU_CHIP_FILL = "#2d4075"
MENU_CHIP_BORDER = "#1e2c50"
MENU_CHIP_RING = "#707ca3"
MENU_HOVER_CHIP_FILL = "#424142"
MENU_HOVER_CHIP_RING = "#555455"
MENU_TEXT = "#e6e6e6"

GUTTER_BG = "#1a1a1a"           # ▸ the code editor's gutter (D11)
GUTTER_FG = "#7a7a7a"

SIDEBAR_PICKER_START = "#4af2a1"    # the colour picker's starting colour for a row that has none
LINK_COLOR = "#8e8a85"              # About-tab links, a step darker than body text so they read as secondary

BTN_APPLY = "Apply"                 # ▸ THE WORDS, from here down. Buttons first
BTN_CANCEL = "Cancel"
BTN_ACCEPT = "Accept"               # commits and CLOSES; Apply commits and stays open - Houdini's own pair (ref ▸ windows/optype)
LABEL_CUSTOM_COLOR = "Custom Color"      # a LABEL since the 2026-08-27 overhaul: the chip beside it is the button
BTN_ADD_FOLDER = "Add Folder"
BTN_CLEAR_SEARCH = "Clear Search"
BTN_SHOW_ALL = "Show All"
BTN_LOCATE = "Locate"
BTN_NEW_FILE = "New File"

LABEL_CHANGE_NAME = "Change Name"       # ▸ field labels and placeholders
LABEL_TAGS = "Tags"
LABEL_CATEGORY = "Category"
LABEL_ICON = "Icon"                 # the D02 menu choosing the tile's face
FACE_LABELS = ("Preview", "Generic", "Custom")    # its items, in `tile_icons.FACES` order
LABEL_LIGHT_ICON = "Light Icon"     # the D02 toggle that replaced the Lines dropdown: OFF = dark lines, ON = light
LABEL_NAME = "Name"
PLACEHOLDER_SEARCH_ICONS = "Search"     # D02 drew the count in it; it does not any more
PLACEHOLDER_VERSION_NAME = "Rename this version"

TITLE_TILE_ICON = "Tile Icon"    # what D02 says when the selection has no ONE name to show
BAND_UNTITLED = "Untitled"       # what D11's band says for a snippet that has no name yet

EMPTY_SHARED = {    # ▸ E06-E08, the blanks EVERY section shares. Each row is (headline, sentence, button label, verb); a blank verb means no button, and `%s` takes the section's own noun
    "nothing-matches": (
        'Nothing matches "%s"',
        "No saved %s has that in its name, tags or category.",
        BTN_CLEAR_SEARCH, "clear_filter_box"),
    "nothing-here": (
        '"%s" is empty',
        "Drag and drop to add a %s to this category.",
        BTN_SHOW_ALL, "show_all_categories"),
    "no-favourites": (
        "No favorites yet",
        "Click the favorites button on a tile to favorite it.",
        BTN_SHOW_ALL, "clear_favourites_filter"),
    "unreachable": (
        "Can't find the folder",
        "“%s” is not available at the current location.",
        BTN_LOCATE, "locate_unreadable_folder"),
}

EMPTY_MATERIAL = {    # ▸ E01-E05, each section's FIRST-RUN blank, and the quotation drawn under it
    "nothing-yet": (
        "No materials saved yet",
        "Right-click a material in the network editor and choose "
        "Save to Amaze.",
        "", ""),
}
QUOTE_MATERIAL = (
    "Kunst gibt nicht das Sichtbare wieder, sondern macht sichtbar.",
    "Paul Klee, Schöpferische Konfession, 1920")

EMPTY_COLOR = {
    "nothing-yet": (
        "No palettes saved yet",
        "Right-click a color ramp and choose Save to Amaze.",
        "", ""),
}
QUOTE_COLOR = ('"I\'m profoundly optimistic about nothing."',
               "Francis Bacon")

EMPTY_NODE = {
    "nothing-yet": (
        "No node assets saved yet",
        "Select nodes in a network, right-click and choose Save to "
        "Amaze.",
        "", ""),
}
QUOTE_NODE = ('"I have nothing to say and I am saying it."',
              "John Cage, Lecture on Nothing, 1949")

EMPTY_CODE = {
    "nothing-yet": (
        "No code saved yet",
        "Right-click a wrangle and choose Save to Amaze.",
        BTN_NEW_FILE, "new_code_snippet"),
}

EMPTY_FILE = {
    "nothing-yet": (
        "No locations added yet",
        "Add folders of images, geometry or .hip files.",
        BTN_ADD_FOLDER, "add_file_folder_user"),
}


DIALOG_LAYOUT = {    # ▸ EVERY DRAWN FIGURE: (kind, x, y, w, h, text) per node, per frame; `AmazeNotes/tools/figma-diff.py` checks Figma against it ▸p/one-design-document
    "D01": {   # Versions
        "frame": (256, 185),
        "nodes": (
            ("header band", 0, 0, 256, 30, None),
            ("QLabel", 18, 4, 93, 15, "[name of version] "),
            ("QComboBox", 18, 42, 220, 30, None),
            ("QComboBox ▸ text", 23, 50, 153, 15, "Version 2   (2026-08-01)   active"),
            ("QLabel", 18, 81, 59, 13, "Change Name"),
            ("QLineEdit", 18, 98, 220, 30, None),
            ("QLineEdit ▸ text", 23, 106, 46, 15, "Version 2"),
            ("QPushButton", 18, 146, 101, 21, None),
            ("QPushButton", 138, 146, 101, 21, None),
            ("QPushButton ▸ text", 52, 149, 34, 15, "Cancel"),
            ("QPushButton ▸ text", 174, 149, 29, 15, "Apply"),
        ),
    },
    "D02": {   # Customize (Tile Icon)
        "frame": (335, 610),
        "nodes": (
            ("header band", 0, 0, 335, 30, None),
            ("QLabel", 18, 7, 82, 15, "[name of asset] "),
            ("QLineEdit", 71, 36, 256, 22, None),
            ("QLabel", 33, 40, 30, 15, "Name"),
            ("QLineEdit ▸ text", 76, 40, 72, 15, "brushed_steel"),
            ("QComboBox", 71, 67, 255, 22, None),
            ("QLabel", 18, 71, 45, 15, "Category"),
            ("QLineEdit", 71, 98, 255, 22, None),
            ("QLabel", 40, 101, 23, 15, "Tags"),
            ("QLabel", 8, 131, 150, 150, None),
            ("QLabel", 171, 133, 22, 15, "Icon"),
            ("QComboBox", 201, 129, 125, 22, None),
            ("QLabel", 202, 189, 50, 15, "Light Icon"),
            ("ToggleSwitch", 171, 189, 23, 15, None),
            ("QToolButton", 171, 214, 35, 28, None),
            ("QLabel", 212, 220, 68, 15, "Custom Color"),
            ("QToolButton", 171, 252, 35, 28, None),
            ("QToolButton", 212, 252, 34, 28, None),
            ("QToolButton", 252, 252, 35, 28, None),
            ("QToolButton", 293, 252, 34, 28, None),
            ("QLineEdit", 8, 290, 319, 22, None),
            ("QLineEdit ▸ text", 14, 294, 35, 15, "Search"),
            ("icon grid ▸ 287 cells (collapsed)", 8, 318, 319, 250, None),
            ("QScrollBar", 311, 323, 16, 240, None),
            ("icon grid ▸ note", 16, 405, 136, 11, "287 icon cells, 34×34 — scrolls"),
            ("QPushButton", 177, 576, 72, 22, None),
            ("QPushButton", 255, 576, 72, 22, None),
            ("QPushButton ▸ text", 198, 579, 29, 15, "Apply"),
            ("QPushButton ▸ text", 274, 579, 34, 15, "Accept"),
        ),
    },
    "D04": {   # Preferences - Library
        "frame": (498, 451),
        "nodes": (
            ("QTabBar", 12, 12, 466, 22, None),
            ("QTabBar::tab ▸ Library (selected)", 12, 12, 64, 22, None),
            ("QTabBar::tab ▸ Library", 26, 16, 36, 15, "Library"),
            ("QTabBar::tab ▸ Render", 91, 16, 36, 15, "Render"),
            ("QTabBar::tab ▸ Show/Hide", 155, 16, 56, 15, "Show/Hide"),
            ("QTabBar::tab ▸ Look", 239, 16, 25, 15, "Look"),
            ("QTabBar::tab ▸ About", 292, 16, 31, 15, "About"),
            ("QLineEdit", 148, 42, 292, 22, None),
            ("QPushButton", 442, 42, 28, 22, None),
            ("QLabel", 79, 46, 61, 15, "Library Path"),
            ("QLineEdit ▸ text", 153, 46, 35, 15, "<path>"),
            ("QPushButton ▸ text", 452, 46, 9, 15, "..."),
            ("QPushButton", 148, 70, 99, 22, None),
            ("QPushButton ▸ text", 156, 74, 83, 15, "Clean Up Library"),
            ("QPushButton", 148, 98, 88, 22, None),
            ("QPushButton ▸ text", 156, 102, 73, 15, "Reload Library"),
            ("QPushButton", 148, 126, 115, 22, None),
            ("QPushButton ▸ text", 156, 130, 100, 15, "Open Library Folder"),
            ("QWidget ▸ group divider", 20, 162, 450, 1, None),
            ("ToggleSwitch", 148, 177, 23, 15, None),
            ("ToggleSwitch ▸ text", 179,177, 86, 15, "Material Versions"),
            ("QComboBox", 148, 200, 196, 22, None),
            ("QPushButton", 352, 200, 56, 22, None),
            ("QPushButton", 414, 200, 56, 22, None),
            ("QLabel", 117, 204, 23, 15, "User"),
            ("QComboBox ▸ text", 153, 204, 27, 15, "Plum"),
            ("QPushButton ▸ text", 360, 204, 42, 15, "Rename"),
            ("QPushButton ▸ text", 422, 204, 33, 15, "Delete"),
            ("QWidget ▸ group divider", 20, 236, 450, 1, None),
            ("QLineEdit", 148, 249, 236, 22, None),
            ("QPushButton", 388, 249, 28, 22, None),
            ("QPushButton", 418, 249, 52, 22, None),
            ("QLabel", 83, 253, 57, 15, "Cache Path"),
            ("QLineEdit ▸ text", 153, 253, 35, 15, "<path>"),
            ("QPushButton ▸ text", 398, 253, 9, 15, "..."),
            ("QPushButton ▸ text", 426, 253, 37, 15, "Default"),
            ("QPushButton", 148, 277, 110, 22, None),
            ("QPushButton ▸ text", 156, 281, 95, 15, "Delete Local Cache"),
        ),
    },
    "D05": {   # Preferences - Render
        "frame": (498, 451),
        "nodes": (
            ("QTabBar", 12, 12, 466, 22, None),
            ("QTabBar::tab ▸ Render (selected)", 76, 12, 65, 22, None),
            ("QTabBar::tab ▸ Library", 26, 16, 36, 15, "Library"),
            ("QTabBar::tab ▸ Render", 91, 16, 36, 15, "Render"),
            ("QTabBar::tab ▸ Show/Hide", 155, 16, 56, 15, "Show/Hide"),
            ("QTabBar::tab ▸ Look", 239, 16, 25, 15, "Look"),
            ("QTabBar::tab ▸ About", 292, 16, 31, 15, "About"),
            ("QSpinBox", 148, 42, 64, 24, None),
            ("QLineEdit", 149, 43, 62, 22, None),
            ("ClickSlider", 220, 43, 250, 22, None),
            ("QLabel", 83, 47, 57, 15, "RenderSize"),
            ("QSpinBox ▸ text", 153, 47, 18, 15, "256"),
            ("QLineEdit ▸ text", 154, 47, 18, 15, "256"),
            ("QSpinBox", 148, 72, 64, 24, None),
            ("QLineEdit", 149, 73, 62, 22, None),
            ("ClickSlider", 220, 73, 250, 22, None),
            ("QLabel", 46, 77, 94, 15, "Samples (Redshift)"),
            ("QSpinBox ▸ text", 153, 77, 18, 15, "256"),
            ("QLineEdit ▸ text", 154, 77, 18, 15, "256"),
            ("QSpinBox", 148, 102, 64, 24, None),
            ("QLineEdit", 149, 103, 62, 22, None),
            ("ClickSlider", 220, 103, 250, 22, None),
            ("QLabel", 54, 107, 86, 15, "Samples (Karma)"),
            ("QSpinBox ▸ text", 153, 107, 6, 15, "9"),
            ("QLineEdit ▸ text", 154, 107, 6, 15, "9"),
            ("QSpinBox", 148, 132, 64, 24, None),
            ("QLineEdit", 149, 133, 62, 22, None),
            ("ClickSlider", 220, 133, 250, 22, None),
            ("QLabel", 59, 137, 81, 15, "RAM Cache (MB)"),
            ("QSpinBox ▸ text", 153, 137, 18, 15, "256"),
            ("QLineEdit ▸ text", 154, 137, 18, 15, "256"),
            ("QComboBox", 148, 162, 165, 22, None),
            ("QLabel", 46, 166, 94, 15, "Geometry Shading"),
            ("QComboBox ▸ text", 153, 166, 93, 15, "Hidden Line Ghost"),
            ("QComboBox", 148, 190, 165, 22, None),
            ("QLabel", 27, 194, 113, 15, "Geometry Background"),
            ("QComboBox ▸ text", 153, 194, 28, 15, "Black"),
            ("ToggleSwitch", 148, 220, 23, 15, None),
            ("ToggleSwitch ▸ text", 179,220, 132, 15, "Render Thumbs on Import"),
            ("QWidget ▸ group divider", 20, 251, 450, 1, None),
            ("QSpinBox", 148, 264, 64, 24, None),
            ("QLineEdit", 149, 265, 62, 22, None),
            ("ClickSlider", 220, 265, 250, 22, None),
            ("QLabel", 40, 269, 100, 15, "Conversion Threads"),
            ("QSpinBox ▸ text", 153, 269, 6, 15, "4"),
            ("QLineEdit ▸ text", 154, 269, 6, 15, "4"),
            ("QWidget ▸ group divider", 20, 302, 450, 1, None),
            ("QComboBox", 148, 315, 72, 22, None),
            ("QLabel", 32, 319, 108, 15, "Download Resolution"),
            ("QComboBox ▸ text", 153, 319, 12, 15, "2k"),
            ("QSpinBox", 148, 343, 64, 24, None),
            ("QLineEdit", 149, 344, 62, 22, None),
            ("ClickSlider", 220, 344, 250, 22, None),
            ("QLabel", 44, 348, 96, 15, "Parallel Downloads"),
            ("QSpinBox ▸ text", 153, 348, 6, 15, "8"),
            ("QLineEdit ▸ text", 154, 348, 6, 15, "8"),
        ),
    },
    "D06": {   # Preferences - Show/Hide
        "frame": (498, 451),
        "nodes": (
            ("QTabBar", 12, 12, 466, 22, None),
            ("QTabBar::tab ▸ Show/Hide (selected)", 141, 12, 84, 22, None),
            ("QTabBar::tab ▸ Library", 26, 16, 36, 15, "Library"),
            ("QTabBar::tab ▸ Render", 91, 16, 36, 15, "Render"),
            ("QTabBar::tab ▸ Show/Hide", 155, 16, 56, 15, "Show/Hide"),
            ("QTabBar::tab ▸ Look", 239, 16, 25, 15, "Look"),
            ("QTabBar::tab ▸ About", 292, 16, 31, 15, "About"),
            ("ToggleSwitch", 148, 44, 23, 15, None),
            ("ToggleSwitch ▸ text", 179,44, 34, 15, "Karma"),
            ("ToggleSwitch", 148, 69, 23, 15, None),
            ("ToggleSwitch ▸ text", 179,69, 41, 15, "Redshift"),
            ("ToggleSwitch", 148, 94, 23, 15, None),
            ("ToggleSwitch ▸ text", 179,94, 36, 15, "Octane"),
            ("QWidget ▸ group divider", 20, 125, 450, 1, None),
            ("ToggleSwitch", 148, 140, 23, 15, None),
            ("ToggleSwitch ▸ text", 179,140, 41, 15, "Material"),
            ("ToggleSwitch", 148, 165, 23, 15, None),
            ("ToggleSwitch ▸ text", 179,165, 28, 15, "Color"),
            ("ToggleSwitch", 148, 190, 23, 15, None),
            ("ToggleSwitch ▸ text", 179,190, 27, 15, "Node"),
            ("ToggleSwitch", 148, 215, 23, 15, None),
            ("ToggleSwitch ▸ text", 179,215, 26, 15, "Code"),
            ("ToggleSwitch", 148, 240, 23, 15, None),
            ("ToggleSwitch ▸ text", 179,240, 18, 15, "File"),
        ),
    },
    "D07": {   # Preferences - Look
        "frame": (498, 451),
        "nodes": (
            ("QTabBar", 12, 12, 466, 22, None),
            ("QTabBar::tab ▸ Look (selected)", 225, 12, 53, 22, None),
            ("QTabBar::tab ▸ Library", 26, 16, 36, 15, "Library"),
            ("QTabBar::tab ▸ Render", 91, 16, 36, 15, "Render"),
            ("QTabBar::tab ▸ Show/Hide", 155, 16, 56, 15, "Show/Hide"),
            ("QTabBar::tab ▸ Look", 239, 16, 25, 15, "Look"),
            ("QTabBar::tab ▸ About", 292, 16, 31, 15, "About"),
            ("ToggleSwitch", 148, 44, 23, 15, None),
            ("ToggleSwitch ▸ text", 179,44, 137, 15, "Show Counts on Categories"),
            ("ToggleSwitch", 148, 69, 23, 15, None),
            ("ToggleSwitch ▸ text", 179,69, 114, 15, "Hide Empty Categories"),
            ("ToggleSwitch", 148, 94, 23, 15, None),
            ("ToggleSwitch ▸ text", 179,94, 115, 15, "All show unknown files"),
            ("QComboBox", 148, 117, 105, 22, None),
            ("QLabel", 69, 121, 71, 15, "Write Paths As"),
            ("QComboBox ▸ text", 153, 121, 37, 15, "$HOME"),
            ("QComboBox", 148, 145, 145, 22, None),
            ("QLabel", 74, 149, 66, 15, "Tile Icon Line"),
            ("QComboBox ▸ text", 153, 149, 23, 15, "Thin"),
            ("QSpinBox", 148, 173, 64, 24, None),
            ("QLineEdit", 149, 174, 62, 22, None),
            ("ClickSlider", 220, 174, 250, 22, None),
            ("QLabel", 57, 178, 83, 15, "Scroll Speed (%)"),
            ("QSpinBox ▸ text", 153, 178, 12, 15, "75"),
            ("QLineEdit ▸ text", 154, 178, 12, 15, "75"),
        ),
    },
    "D08": {   # Preferences - About
        "frame": (498, 451),
        "nodes": (
            ("QTabBar", 12, 12, 466, 22, None),
            ("QTabBar::tab ▸ About (selected)", 278, 12, 59, 22, None),
            ("QTabBar::tab ▸ Library", 26, 16, 36, 15, "Library"),
            ("QTabBar::tab ▸ Render", 91, 16, 36, 15, "Render"),
            ("QTabBar::tab ▸ Show/Hide", 155, 16, 56, 15, "Show/Hide"),
            ("QTabBar::tab ▸ Look", 239, 16, 25, 15, "Look"),
            ("QTabBar::tab ▸ About", 292, 16, 31, 15, "About"),
            ("QTextBrowser", 20, 42, 450, 227, None),
            ("QScrollBar", 454, 42, 16, 227, None),
            ("QLabel", 148, 274, 322, 15, "Amaze version 1.0.31"),
            ("QPushButton", 148, 295, 108, 22, None),
            ("QPushButton", 264, 295, 90, 22, None),
            ("QPushButton ▸ text", 156, 299, 92, 15, "Check for Updates"),
            ("QPushButton ▸ text", 272, 299, 74, 15, "Report a Bug..."),
            ("QPushButton", 260, 323, 64, 22, None),
            ("QPushButton", 332, 323, 70, 22, None),
            ("QPushButton", 408, 323, 62, 22, None),
            ("ToggleSwitch", 148, 326, 23, 15, None),
            ("ToggleSwitch ▸ text", 179, 326, 63, 15, "Debug Mode"),
            ("QPushButton ▸ text", 268, 327, 48, 15, "Open Log"),
            ("QPushButton ▸ text", 340, 327, 54, 15, "Save Log..."),
            ("QPushButton ▸ text", 416, 327, 47, 15, "Clear Log"),
            ("QWidget ▸ group divider", 20, 359, 450, 1, None),
            ("ToggleSwitch", 148, 374, 23, 15, None),
            ("ToggleSwitch ▸ text", 179, 374, 59, 15, "Test Library"),
            ("QLineEdit", 148, 397, 292, 22, None),
            ("QPushButton", 442, 397, 28, 22, None),
            ("QLabel", 85, 401, 55, 15, "Test Folder"),
            ("QPushButton ▸ text", 452, 401, 9, 15, "..."),
        ),
    },
    "D09": {   # Save to Amaze - the Section row picks where the save lands
        "frame": (350, 177),
        "nodes": (
            ("QComboBox", 67, 11, 276, 22, None),
            ("QLabel", 22, 15, 38, 15, "Section"),
            ("QComboBox ▸ text", 72, 15, 41, 15, "Material"),
            ("QLineEdit", 67, 37, 276, 22, None),
            ("QLabel", 30, 41, 30, 15, "Name"),
            ("QLineEdit ▸ text", 72, 41, 33, 15, "rocks1"),
            ("QComboBox", 67, 63, 276, 22, None),
            ("QLabel", 15, 67, 45, 15, "Category"),
            ("QComboBox ▸ text", 72, 67, 28, 15, "Metal"),
            ("QComboBox", 67, 89, 276, 22, None),
            ("QLabel", 11, 93, 49, 15, "Language"),
            ("QComboBox ▸ text", 72, 93, 19, 15, "VEX"),
            ("QLineEdit", 67, 115, 276, 22, None),
            ("QLabel", 37, 119, 23, 15, "Tags"),
            ("QPushButton", 254, 146, 31, 22, None),
            ("QPushButton", 293, 146, 50, 22, None),
            ("QPushButton ▸ text", 262, 150, 15, 15, "OK"),
            ("QPushButton ▸ text", 301, 150, 34, 15, "Cancel"),
        ),
    },
    "D11": {   # Code snippet - New Snippet and Edit; a node's code saves through D09
        "frame": (638, 516),
        "nodes": (
            ("header band", 0, 0, 638, 30, None),
            ("QLabel", 18, 7, 82, 15, "[name of asset] "),
            ("QLineEdit", 70, 49, 245, 22, None),
            ("QComboBox", 385, 49, 245, 22, None),
            ("QLabel", 33, 53, 30, 15, "Name"),
            ("QLineEdit ▸ text", 75, 53, 33, 15, "helper"),
            ("QLabel", 333, 53, 45, 15, "Category"),
            ("QComboBox ▸ text", 390, 53, 28, 15, "Metal"),
            ("QComboBox", 70, 75, 245, 22, None),
            ("QLineEdit", 385, 75, 245, 22, None),
            ("QLabel", 14, 79, 49, 15, "Language"),
            ("QComboBox ▸ text", 75, 79, 19, 15, "VEX"),
            ("QLabel", 355, 79, 23, 15, "Tags"),
            ("CodeEditor", 18, 109, 612, 364, None),
            ("QLabel", 37, 109, 26, 15, "Code"),
            ("_LineNumberArea", 19, 110, 28, 362, None),
            ("QPushButton", 541, 481, 31, 22, None),
            ("QPushButton", 580, 481, 50, 22, None),
            ("QPushButton ▸ text", 549, 485, 15, 15, "OK"),
            ("QPushButton ▸ text", 588, 485, 34, 15, "Cancel"),
        ),
    },
    "D13": {   # Name Input
        "frame": (350, 72),
        "nodes": (
            ("QLineEdit", 67, 11, 276, 22, None),
            ("QLabel", 30, 15, 30, 15, "Name"),
            ("QLineEdit ▸ text", 72, 15, 30, 15, "Warm"),
            ("QPushButton", 254, 39, 31, 22, None),
            ("QPushButton", 293, 39, 50, 22, None),
            ("QPushButton ▸ text", 262, 43, 15, 15, "OK"),
            ("QPushButton ▸ text", 301, 43, 34, 15, "Cancel"),
        ),
    },
    "D14": {   # User Picker - who is using this library, on first open
        "frame": (369, 100),
        "nodes": (
            ("QPushButton", 273, 69, 31, 22, None),
            ("QPushButton ▸ text", 281, 73, 15, 15, "OK"),
            ("QPushButton", 312, 69, 50, 22, None),
            ("QPushButton ▸ text", 320, 73, 34, 15, "Cancel"),
            ("QLabel", 10, 15, 69, 15, "Existing Users"),
            ("QComboBox", 86, 11, 276, 22, None),
            ("QComboBox ▸ text", 91, 15, 27, 15, "Plum"),
            ("QLabel", 31, 41, 48, 15, "New User"),
            ("QLineEdit", 86, 37, 276, 22, None),
        ),
    },
    "T01": {   # the grid tile, drawn at TILE_DRAWN_SIZE - its spacing is what the delegate paints
        "frame": (138, 177),
        "nodes": (
            ("tile card", 4, 4, 130, 173, None),
            ("thumbnail", 4, 4, 130, 130, None),
            ("badge open (top-left) ▸ badge_open", 6, 6, 22, 22, None),
            ("badge favourite (top-right) ▸ badge_favourite", 110, 6, 22, 22, None),
            ("badge versions (lower-left) ▸ badge_versions", 6, 110, 22, 22, None),
            ("badge comment (lower-right) ▸ badge_comment", 110, 110, 22, 22, None),
            ("tile name", 9, 142, 74, 15, "brushed_steel"),
            ("tile subtitle", 9, 157, 34, 15, "Karma"),
        ),
    },
    "T05": {   # the code tile on its generic face: Run in the middle, Edit where Versions is elsewhere
        "frame": (138, 177),
        "nodes": (
            ("tile card", 4, 4, 130, 173, None),
            ("thumbnail", 4, 4, 130, 130, None),
            ("face ▸ face_code.svg", 4, 4, 130, 130, None),
            ("tile name", 9, 142, 52, 15, "Mtxl to RS"),
            ("tile subtitle", 9, 157, 37, 15, "Python"),
            ("badge favourite (top-right) ▸ badge_favourite", 110, 6, 22, 22, None),
            ("badge edit (lower-left) ▸ badge_edit", 6, 110, 22, 22, None),
            ("badge comment (lower-right) ▸ badge_comment", 110, 110, 22, 22, None),
            ("badge execute (centre) ▸ badge_execute", 51, 55, 36, 36, None),
        ),
    },
    "L01": {   # the list table from the live panel - its header, widths and ticks are read
        "frame": (1542, 96),
        "nodes": (
            ("column ▸ name", 0, 0, 176, 20, None),
            ("divider ▸ name", 175, 0, 1, 20, None),
            ("heading ▸ name", 5, 2.5, 30, 15, "Name"),
            ("sort arrow ▸ name (Qt's own, traced)", 155, 2, 16, 16, None),
            ("column ▸ type", 176, 0, 59, 20, None),
            ("divider ▸ type", 234, 0, 1, 20, None),
            ("heading ▸ type", 181, 2.5, 25, 15, "Type"),
            ("column ▸ category", 235, 0, 76, 20, None),
            ("divider ▸ category", 310, 0, 1, 20, None),
            ("heading ▸ category", 240, 2.5, 45, 15, "Category"),
            ("column ▸ favorite", 311, 0, 69, 20, None),
            ("divider ▸ favorite", 379, 0, 1, 20, None),
            ("heading ▸ favorite", 316, 2.5, 41, 15, "Favorite"),
            ("column ▸ version", 380, 0, 66, 20, None),
            ("divider ▸ version", 445, 0, 1, 20, None),
            ("heading ▸ version", 385, 2.5, 38, 15, "Version"),
            ("column ▸ open", 446, 0, 54, 20, None),
            ("divider ▸ open", 499, 0, 1, 20, None),
            ("heading ▸ open", 451, 2.5, 28, 15, "Open"),
            ("column ▸ comments", 500, 0, 85, 20, None),
            ("divider ▸ comments", 584, 0, 1, 20, None),
            ("heading ▸ comments", 505, 2.5, 55, 15, "Comments"),
            ("column ▸ tags", 585, 0, 300, 20, None),
            ("divider ▸ tags", 884, 0, 1, 20, None),
            ("heading ▸ tags", 590, 2.5, 23, 15, "Tags"),
            ("column ▸ license", 885, 0, 287, 20, None),
            ("divider ▸ license", 1171, 0, 1, 20, None),
            ("heading ▸ license", 890, 2.5, 38, 15, "License"),
            ("column ▸ date", 1172, 0, 130, 20, None),
            ("divider ▸ date", 1301, 0, 1, 20, None),
            ("heading ▸ date", 1177, 2.5, 24, 15, "Date"),
            ("column ▸ id", 1302, 0, 240, 20, None),
            ("divider ▸ id", 1541, 0, 1, 20, None),
            ("heading ▸ id", 1307, 2.5, 11, 15, "ID"),
            ("row ▸ plain", 0, 20, 1542, 19, None),
            ("cell ▸ name", 5, 22, 72, 15, "brushed_steel"),
            ("cell ▸ type", 181, 22, 48, 15, "USD Re…"),
            ("cell ▸ category", 240, 22, 28, 15, "Metal"),
            ("cell ▸ version", 385, 22, 46, 15, "Version 2"),
            ("cell ▸ tags", 590, 22, 55, 15, "steel, worn"),
            ("cell ▸ license", 890, 22, 20, 15, "CC0"),
            ("cell ▸ date", 1177, 22, 100, 15, "2026-09-04 01:51:48"),
            ("cell ▸ id", 1307, 22, 188, 15, "8f3c2a71d4e94b0c9a6e1f5b2d7c3e90"),
            ("tick box ▸ favorite", 316, 20, 12, 19, None),
            ("tick box ▸ comments", 505, 20, 12, 19, None),
            ("row ▸ plain", 0, 39, 1542, 19, None),
            ("cell ▸ name", 5, 41, 58, 15, "oak_planks"),
            ("cell ▸ type", 181, 41, 48, 15, "USD Re…"),
            ("cell ▸ category", 240, 41, 30, 15, "Wood"),
            ("cell ▸ date", 1177, 41, 100, 15, "2026-08-21 14:02:10"),
            ("cell ▸ id", 1307, 41, 189, 15, "1b7e9d0c3a5f4e2b8c6d9a0f7e3b5c1d"),
            ("row ▸ selected", 0, 58, 1542, 19, None),
            ("cell ▸ name", 5, 60, 33, 15, "rocks1"),
            ("cell ▸ type", 181, 60, 48, 15, "USD Re…"),
            ("cell ▸ category", 240, 60, 30, 15, "Stone"),
            ("cell ▸ tags", 590, 60, 64, 15, "rock, ground"),
            ("cell ▸ license", 890, 60, 94, 15, "MIT Public Domain"),
            ("cell ▸ date", 1177, 60, 100, 15, "2026-10-12 22:41:05"),
            ("cell ▸ id", 1307, 60, 189, 15, "c4d2e8f1a9b3470d8e6f2a5c1b9d7e30"),
            ("tick box ▸ favorite", 316, 58, 12, 19, None),
            ("tick box ▸ open", 451, 58, 12, 19, None),
            ("row ▸ plain", 0, 77, 1542, 19, None),
            ("cell ▸ name", 5, 79, 53, 15, "red_velvet"),
            ("cell ▸ type", 181, 79, 48, 15, "USD Re…"),
            ("cell ▸ category", 240, 79, 31, 15, "Fabric"),
            ("cell ▸ date", 1177, 79, 100, 15, "2026-07-30 09:15:33"),
            ("cell ▸ id", 1307, 79, 188, 15, "e5a1c7b3d9f2468a0c4e8b2d6f1a3c57"),
            ("tick box ▸ comments", 505, 77, 12, 19, None),
        ),
    },
    "B01": {   # the toolbar from the live panel - its height, edges, gaps and control sizes are read
        "frame": (1510, 30),
        "nodes": (
            ("bottom border", 0, 29, 1510, 1, None),
            ("button ▸ btn_categories", 2, 3, 24, 24, None),
            ("button ▸ btn_menu_view", 28, 3, 24, 24, None),
            ("button ▸ btn_menu_filter", 54, 3, 24, 24, None),
            ("button ▸ btn_online", 80, 3, 24, 24, None),
            ("button ▸ btn_notes", 106, 3, 24, 24, None),
            ("button ▸ cb_viewmode", 132, 3, 24, 24, None),
            ("button ▸ cb_favsonly", 158, 3, 24, 24, None),
            ("slider ▸ click_slider (disabled)", 202, 3, 200, 23, None),
            ("label ▸ filter_label", 422, 0, 40, 30, None),
            ("text ▸ filter_label", 424, 7, 35, 15, "Search"),
            ("field ▸ line_filter", 474, 5, 200, 20, None),
            ("button ▸ btn_prefs", 1484, 3, 24, 24, None),
            ("icon ▸ btn_categories ▸ icon_categories.svg", 6, 7, 16, 16, None),
            ("icon ▸ btn_menu_view ▸ icon_renderer.svg", 31, 6, 18, 18, None),
            ("icon ▸ btn_menu_filter ▸ icon_view.svg", 57, 6, 18, 18, None),
            ("icon ▸ btn_online ▸ icon_online.svg", 84, 7, 16, 16, None),
            ("icon ▸ btn_notes ▸ icon_comments.svg", 110, 7, 16, 16, None),
            ("icon ▸ cb_viewmode ▸ list.svg", 136, 7, 16, 16, None),
            ("icon ▸ cb_favsonly ▸ favourite_on.svg", 162, 7, 15, 15, None),
            ("icon ▸ line_filter ▸ icon_search.svg", 478, 8, 13, 13, None),
            ("icon ▸ btn_prefs ▸ icon_library.svg", 1487, 6, 18, 18, None),
        ),
    },
    "S01": {   # the section tab strip from the live panel - its height, tray and chip spacing are read
        "frame": (1510, 28),
        "nodes": (
            ("tray", 3, 5, 230, 23, None),
            ("chip ▸ material", 6, 8, 56, 17, None),
            ("chip ▸ gradient", 64.5, 8, 42, 17, None),
            ("chip ▸ cop", 109, 8, 42, 17, None),
            ("chip ▸ code", 153.5, 8, 41, 17, None),
            ("chip ▸ file", 197, 8, 33, 17, None),
            ("text box ▸ material", 13.5, 9, 41, 15, None),
            ("label ▸ material", 13.5, 9, 41, 15, "Material"),
            ("text box ▸ gradient", 72, 9, 27, 15, None),
            ("label ▸ gradient", 71.5, 9, 28, 15, "Color"),
            ("text box ▸ cop", 116.5, 9, 27, 15, None),
            ("label ▸ cop", 116.5, 9, 27, 15, "Node"),
            ("text box ▸ code", 161, 9, 26, 15, None),
            ("label ▸ code", 161, 9, 26, 15, "Code"),
            ("text box ▸ file", 204.5, 9, 18, 15, None),
            ("label ▸ file", 204.5, 9, 18, 15, "File"),
        ),
    },
    "G01": {   # the sidebar at its design width - its width, colour bar and splitter handle are read
        "frame": (226, 190),
        "nodes": (
            ("list", 0, 0, 220, 190, None),
            ("row ▸ selected", 0, 0, 220, 19, None),
            ("text ▸ All", 13, 2, 44, 15, "All (128)"),
            ("row ▸ plain", 0, 19, 220, 19, None),
            ("bar ▸ Metal", 3, 21, 4, 15, None),
            ("text ▸ Metal", 13, 21, 50, 15, "Metal (12)"),
            ("row ▸ plain", 0, 38, 220, 19, None),
            ("bar ▸ Wood", 3, 40, 4, 15, None),
            ("text ▸ Wood", 13, 40, 45, 15, "Wood (9)"),
            ("row ▸ plain", 0, 57, 220, 19, None),
            ("text ▸ Stone", 13, 59, 45, 15, "Stone (4)"),
            ("row ▸ plain", 0, 76, 220, 19, None),
            ("bar ▸ Fabric", 3, 78, 4, 15, None),
            ("text ▸ Fabric", 13, 78, 53, 15, "Fabric (21)"),
            ("row ▸ plain", 0, 95, 220, 19, None),
            ("text ▸ Glass", 13, 97, 43, 15, "Glass (6)"),
            ("row ▸ plain", 0, 114, 220, 19, None),
            ("text ▸ Plastic", 13, 116, 55, 15, "Plastic (17)"),
            ("row ▸ plain", 0, 133, 220, 19, None),
            ("bar ▸ Paint", 3, 135, 4, 15, None),
            ("text ▸ Paint", 13, 135, 48, 15, "Paint (11)"),
            ("splitter handle", 220, 0, 6, 190, None),
            ("grip ▸ Houdini's own, traced", 221.5, 89, 3, 2.5, None),
            ("grip ▸ Houdini's own, traced", 221.5, 94, 3, 2.5, None),
            ("grip ▸ Houdini's own, traced", 221.5, 98.5, 3, 2.5, None),
        ),
    },
    "N01": {   # the comments pane over an invented comment - its spacing and glyph sizes are read
        "frame": (450, 210),
        "nodes": (
            ("header", 0, 0, 450, 30, None),
            ("body", 0, 30, 450, 180, None),
            ("text ▸ name", 36, 7, 76, 15, "brushed_steel"),
            ("text ▸ type", 118, 7, 57, 15, "USD Karma"),
            ("button ▸ add", 419, 1, 28, 27, None),
            ("menu marker ▸ Houdini's own, traced", 440, 21, 4.5, 4.5, None),
            ("line ▸ 1", 12, 42, 185.36, 16, None),
            ("text ▸ 1", 12, 42.5, 186, 15, "The rust reads too orange in daylight."),
            ("line ▸ 2", 36, 68, 109.41, 16, None),
            ("text ▸ 2", 36, 68.5, 109, 15, "Darken the edge wear"),
            ("line ▸ 3", 36, 94, 122.56, 16, None),
            ("text ▸ 3", 36, 94.5, 123, 15, "Render a new thumbnail"),
            ("line ▸ 4", 12, 120, 151.94, 16, None),
            ("text ▸ 4", 12, 120.5, 153, 15, "The scale is right at one metre."),
            ("icon ▸ header ▸ icon_comments.svg", 10, 5, 20, 20, None),
            ("icon ▸ add ▸ icon_comments_add.svg", 424, 6, 18, 18, None),
            ("glyph ▸ 2 ▸ circle.svg", 16, 69, 14, 14, None),
            ("glyph ▸ 3 ▸ check-circle.svg", 16, 95, 14, 14, None),
        ),
    },
    "N01B": {   # the same pane with nothing selected - its labels and arts dim, nothing moves
        "frame": (450, 210),
        "nodes": (
            ("header", 0, 0, 450, 30, None),
            ("body", 0, 30, 450, 180, None),
            ("text ▸ name", 36, 7, 91, 15, "Nothing Selected"),
            ("text ▸ type", 133, 7, 25, 15, "Type"),
            ("button ▸ add", 419, 1, 28, 27, None),
            ("menu marker ▸ Houdini's own, traced", 440, 21, 4.5, 4.5, None),
            ("icon ▸ header ▸ icon_comments.svg", 10, 5, 20, 20, None),
            ("icon ▸ add ▸ icon_comments_add.svg", 424, 6, 18, 18, None),
        ),
    },
}

_NODE_MARK = " ▸ "       # what separates a node's kind from the note after it
_TEXT_SUFFIX = _NODE_MARK + "text"
_DRAWN_BOXES: dict = {}
_DRAWN_REPEATS: dict = {}


def drawn_boxes(frame_key: str) -> dict:
    """One frame's boxes keyed for a call site, derived from `DIALOG_LAYOUT` alone: `(kind, text)` is the plain `<Kind>` rect ENCLOSING that `<Kind> ▸ text` node - or, for a node that carries its own text, that node's OWN rect, since a label IS its box - and `(kind, None)` is every plain `<Kind>` rect in document order. An unknown frame answers `{}`; a label drawn beside its rect rather than inside it (the toggle pills) pairs with nothing. Cached and SHARED - read it, never edit it."""
    cached = _DRAWN_BOXES.get(frame_key)
    if cached is not None:
        return cached
    nodes = (DIALOG_LAYOUT.get(frame_key) or {}).get("nodes", ())
    rects: dict = {}
    for kind, x, y, w, h, text in nodes:
        if text is None and _NODE_MARK not in kind:   # PLAIN, so a `QWidget ▸ group divider` or a tab chip is not a box anything pins from
            rects.setdefault(kind, []).append((x, y, w, h))
    boxes = {(kind, None): tuple(found) for kind, found in rects.items()}
    for kind, x, y, w, h, text in nodes:
        if text is not None and _NODE_MARK not in kind:   # a drawn QLabel: nothing encloses it, so its own rect is what a widget pins from
            boxes.setdefault((kind, text), (x, y, w, h))
    repeats: dict = {}
    for kind, x, y, w, h, text in nodes:
        if text is None or not kind.endswith(_TEXT_SUFFIX):
            continue
        plain = kind[:-len(_TEXT_SUFFIX)]
        holding = [box for box in rects.get(plain, ())
                   if box[0] <= x and box[1] <= y
                   and box[0] + box[2] >= x + w
                   and box[1] + box[3] >= y + h]
        if holding:
            repeats.setdefault((plain, text), []).append(   # SMALLEST of the rects around THIS node: D05 draws `256` in three rows, so a repeated label must answer one box per drawing of it and always the same one
                min(holding, key=lambda box: box[2] * box[3]))
            boxes.setdefault((plain, text), repeats[(plain, text)][0])
    _DRAWN_BOXES[frame_key] = boxes
    _DRAWN_REPEATS[frame_key] = {key: tuple(found)
                                 for key, found in repeats.items()}
    return boxes


def drawn_repeats(frame_key: str, kind: str, text) -> tuple:
    """Every box a call site may pin from for `(kind, text)`, in DRAWN order: one per `<kind> ▸ <text>` node, since a frame may draw a label twice - D04 draws the `...` browse button at two places - or, for `text=None`, every plain `<kind>` rect down the frame. `drawn_boxes` answers the first of them."""
    boxes = drawn_boxes(frame_key)
    if text is None:
        return tuple(sorted(boxes.get((kind, None), ()),
                            key=lambda box: (box[1], box[0])))
    found = _DRAWN_REPEATS[frame_key].get((kind, text))
    if found is not None:
        return found
    box = boxes.get((kind, text))
    return () if box is None else (box,)


def forget_drawn_boxes() -> None:
    """Drop the derived-box cache - the NAMED test seam, so no test reaches into the module dict and pins its spelling."""
    _DRAWN_BOXES.clear()
    _DRAWN_REPEATS.clear()


def drawn_name(node) -> list:
    """A node's name as its `▸` parts, each without its `(note)`: kind, owner, art."""
    return [part.split(" (")[0] for part in node[0].split(_NODE_MARK)]


def drawn_nodes(frame_key: str, kind: str, owner=None) -> list:
    """A frame's `kind` nodes in drawn order, or only `owner`'s - THE lookup every reader shares."""
    return [n for n in DIALOG_LAYOUT[frame_key]["nodes"]
            if drawn_name(n)[0] == kind and (owner is None or drawn_name(n)[1:2] == [owner])]


def drawn_node(frame_key: str, kind: str, owner=None) -> tuple:
    """The first of `drawn_nodes`."""
    return drawn_nodes(frame_key, kind, owner)[0]


def drawn_by_owner(frame_key: str, kind: str) -> dict:
    """{owner: node} for a frame's `kind` nodes; a later drawing of one owner wins."""
    return {drawn_name(n)[1]: n for n in drawn_nodes(frame_key, kind)}


_FORM_FIELDS = ("QLineEdit", "QComboBox")


def drawn_form(frame_key: str) -> dict:
    """A form frame's margins and gaps, read off its drawn nodes; {} if it draws no form."""
    layout = DIALOG_LAYOUT.get(frame_key) or {}
    nodes = layout.get("nodes", ())
    fields = sorted((n for n in nodes if n[0] in _FORM_FIELDS and n[5] is None),
                    key=lambda n: n[2])
    buttons = [n for n in nodes if n[0] == "QPushButton" and n[5] is None]
    labels = [n for n in nodes if n[0] == "QLabel" and n[5]]
    if not (fields and buttons and labels and layout.get("frame")):
        return {}
    width, height = layout["frame"]
    first, last = fields[0], fields[-1]
    button_top = min(b[2] for b in buttons)
    right = width - max(n[1] + n[3] for n in fields + buttons)
    return {
        "top": first[2],
        "left": min([right] + [n[1] for n in labels]),    # labels right-align: the longest must fit
        "right": right,
        "bottom": height - max(b[2] + b[4] for b in buttons),
        "row_gap": fields[1][2] - (first[2] + first[4]) if len(fields) > 1 else 0,
        "label_gap": first[1] - max(n[1] + n[3] for n in labels),
        "button_gap": button_top - (last[2] + last[4]),
    }


TILE_DRAWN_SIZE = 128    # the size-slider value the T frames are drawn at


def drawn_tile(frame_key: str = "T01") -> dict:
    """The grid tile's spacing, read off its frame drawn at TILE_DRAWN_SIZE. ▸r/tile-from-frame"""
    layout = DIALOG_LAYOUT[frame_key]
    thumb, name, sub = (drawn_node(frame_key, kind)
                        for kind in ("thumbnail", "tile name", "tile subtitle"))
    return {
        "pad": thumb[1],
        "width_extra": layout["frame"][0] - TILE_DRAWN_SIZE,
        "img_text_gap": name[2] - (thumb[2] + thumb[4]),
        "text_inset": name[1] - thumb[1],
        "bottom_pad": layout["frame"][1] - (sub[2] + sub[4]),
        "thumb": thumb[3],
    }


def drawn_badges() -> dict:
    """{badge: (edge x, inset x, edge y, inset y, side)} off every T frame; a badge drawn twice agrees."""
    out = {}
    for key, layout in DIALOG_LAYOUT.items():
        if not key.startswith("T"):
            continue
        thumb = drawn_node(key, "thumbnail")
        for node in layout["nodes"]:
            kind, x, y, w = drawn_name(node)[0], node[1], node[2], node[3]
            if not kind.startswith("badge "):
                continue
            place = (_badge_edge(x, w, thumb[1], thumb[3])
                     + _badge_edge(y, w, thumb[2], thumb[4]) + (w,))
            badge = kind[len("badge "):]
            if out.setdefault(badge, place) != place:
                raise ValueError("badge %s is drawn in two places" % badge)
    return out


def _badge_edge(at, size, start, span):
    """("start"|"end", inset from that edge), or ("centre", its middle's offset) if it straddles."""
    middle = start + span / 2
    if at < middle < at + size:
        return "centre", at + size / 2 - middle
    if at + size / 2 > middle:
        return "end", start + span - at - size
    return "start", at - start


def drawn_list(frame_key: str = "L01") -> dict:
    """The list's header, widths, text inset and tick box, off its frame. ▸r/list-from-frame"""
    columns, headings, cells = (drawn_by_owner(frame_key, kind)
                                for kind in ("column", "heading", "cell"))
    tick = drawn_node(frame_key, "tick box")
    first = next(iter(columns))
    return {
        "header_h": columns[first][4],
        "cell_pad": headings[first][1] - columns[first][1],
        "text_inset": cells[first][1] - columns[first][1],
        "widths": {key: n[3] for key, n in columns.items()},
        "tick_pad": tick[1] - columns[drawn_name(tick)[1]][1],
        "tick_side": tick[3],
    }


def drawn_toolbar(frame_key: str = "B01") -> dict:
    """The toolbar's height, edges, gaps and control sizes, off its frame. ▸r/toolbar-from-frame"""
    layout = DIALOG_LAYOUT[frame_key]

    def node(kind, owner):
        return drawn_node(frame_key, kind, owner)

    def right(n):
        return n[1] + n[3]

    first, second = node("button", "btn_categories"), node("button", "btn_menu_view")
    slider, label = node("slider", "click_slider"), node("label", "filter_label")
    field, search = node("field", "line_filter"), node("icon", "line_filter")
    icons = {owner: n[3] for owner, n in drawn_by_owner(frame_key, "icon").items()}
    return {
        "height": layout["frame"][1],
        "edge": first[1],
        "gap": second[1] - right(first),
        "slider_gap": slider[1] - right(node("button", "cb_favsonly")),
        "label_gap": field[1] - right(label),
        "button": first[3],
        "icons": icons,    # each button's own drawn icon, by its object name
        "chip_icon": icons["btn_categories"],    # a toggle the frame does not draw
        "menu_icon": icons["btn_menu_view"],     # a menu button the frame does not draw
        "slider_w": slider[3],
        "slider_h": slider[4],
        "field_w": field[3],
        "field_h": field[4],
        "search_icon": search[3],
        "search_pad": search[1] - field[1],
    }


def drawn_tabs(frame_key: str = "S01") -> dict:
    """The section strip's height, tray and chip spacing, read off its frame. ▸r/tabs-from-frame"""
    layout = DIALOG_LAYOUT[frame_key]
    tray = drawn_node(frame_key, "tray")
    chips = sorted(drawn_nodes(frame_key, "chip"), key=lambda n: n[1])
    box = drawn_node(frame_key, "text box", drawn_name(chips[0])[1])
    return {
        "height": layout["frame"][1],
        "tray_left": tray[1],
        "tray_height": layout["frame"][1] - tray[2],
        "chip_height": chips[0][4],
        "chip_inset": chips[0][1] - tray[1],
        "chip_gap": chips[1][1] - (chips[0][1] + chips[0][3]),
        "chip_pad": box[1] - chips[0][1],
    }


def drawn_sidebar(frame_key: str = "G01") -> dict:
    """The sidebar's width, colour bar and splitter handle, off its frame. ▸r/sidebar-from-frame"""
    return {"width": drawn_node(frame_key, "list")[3], "bar": drawn_node(frame_key, "bar")[3],
            "handle": drawn_node(frame_key, "splitter handle")[3]}


def drawn_comments(frame_key: str = "N01") -> dict:
    """The comments pane's width, header, margins and glyphs, off its frame. ▸r/comments-from-frame"""
    width = DIALOG_LAYOUT[frame_key]["frame"][0]

    def node(kind, owner=None):
        return drawn_node(frame_key, kind, owner)

    header, icon, name = node("header"), node("icon", "header"), node("text", "name")
    add, glyph = node("button", "add"), node("glyph", "2")
    plain, todo = node("line", "1"), node("line", "2")
    return {
        "width": width,
        "header": header[4],
        "pad": icon[1] - header[1],
        "gap": name[1] - (icon[1] + icon[3]),
        "icon": icon[3],
        "add": (add[3], add[4]),
        "add_pad": width - (add[1] + add[3]),
        "plus": node("icon", "add")[3],
        "doc_margin": plain[1] - node("body")[1],
        "todo_indent": todo[1] - plain[1],
        "todo_pad": todo[2] - (plain[2] + plain[4]),
        "glyph": glyph[3],
        "glyph_inset": glyph[1] - plain[1],
    }
