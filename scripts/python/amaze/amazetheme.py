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
D02_SECTION_GAP = 37     # the switch pair to the Custom Color row - with PRESET_GAP it makes the stack exactly the preview's 150
D02_PRESET_GAP = 10      # the current-colour chip to the preset row
D02_TOP_GAP = 11         # the Tags row to the preview block
D02_BUTTON_GAP = 8       # grid to the button row
D02_GRID_SPACING = 2     # the chooser grid's cell gap, UNSCALED: D02_COLUMNS is the count the drawn 319 column fits at exactly this gap
D02_CHOOSER_RADIUS = 3   # an icon button's corner, UNSCALED - a stylesheet px, like the two below
D02_CHECKED_BORDER = 2   # the ring on the chosen icon, UNSCALED
D02_SWATCH_BORDER = 1    # the preset chips and the current-colour chip, UNSCALED

SAVE_WIDTH = 350         # ▸ the save family D09, D13, D14: every one is this wide, whatever its labels. D10/D12 retired 2026-08-30 - one save engine, D09 is THE save dialog
SAVE_FIELD_WIDTH = 276   # the drawn field width inside it
SAVE_FRAME_H = {"D09": 125, "D13": 72, "D14": 100}   # each frame's drawn height; the row count is the only difference between them
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

PREFS_FRAME = (490, 451)    # ▸ D04-D08 Preferences, the one tabbed window - the drawn frame, every tab
PREFS_FORM_WIDTH = 490   # the frame's width, kept under its old name because call sites use it
PREFS_INSET = 20         # content to the frame edge, both sides: rows span 20..470
PREFS_DIALOG_MARGIN = 12  # the tabbed window's own margin, outside the tab strip
PREFS_PAGE_MARGIN = 8    # each tab page's margin, inside it: 12 + 8 is the drawn 20
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

COMMENT_INK = "#5cc9f5"        # ▸ the Comments pane: its OWN colour, not the accent, so button, header icon and to-do glyphs read as one thing
COMMENT_HEADER_BG = "#22232b"
COMMENT_PAGE_BG = "#2b2c34"

LIST_HEADER_BG = "#2a2a2a"       # ▸ list mode's header strip: a QHeaderView picks up none of these, so the strip states them
LIST_HEADER_DIVIDER = "#454545"
LIST_HEADER_HEIGHT = 20

TILE_TEXT = "#cdc8bc"           # ▸ the tile and list delegates
TILE_SUBTITLE = "#5d7abd"       # the accent DEFAULT only - overwritten per instance from `prefs.accent_color`
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
LABEL_CUSTOM_ICON = "Custom Icon"   # the D02 toggle: OFF = the tile's own thumbnail, ON = the chooser applies
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
        "Click the star on a tile to favorite it.",
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
            ("ToggleSwitch", 171, 132, 23, 15, None),
            ("QLabel", 8, 131, 150, 150, None),
            ("ToggleSwitch ▸ text", 202, 132, 63, 15, "Custom Icon"),
            ("QLabel", 202, 160, 50, 15, "Light Icon"),
            ("ToggleSwitch", 171, 160, 23, 15, None),
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
        "frame": (490, 451),
        "nodes": (
            ("QTabBar", 12, 12, 466, 22, None),
            ("QTabBar::tab ▸ Library (selected)", 12, 12, 64, 22, None),
            ("QTabBar::tab ▸ Library", 26, 16, 37, 15, "Library"),
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
        "frame": (490, 451),
        "nodes": (
            ("QTabBar", 12, 12, 466, 22, None),
            ("QTabBar::tab ▸ Render (selected)", 76, 12, 65, 22, None),
            ("QTabBar::tab ▸ Library", 26, 16, 36, 15, "Library"),
            ("QTabBar::tab ▸ Render", 90, 16, 38, 15, "Render"),
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
        "frame": (490, 451),
        "nodes": (
            ("QTabBar", 12, 12, 466, 22, None),
            ("QTabBar::tab ▸ Show/Hide (selected)", 141, 12, 84, 22, None),
            ("QTabBar::tab ▸ Library", 26, 16, 36, 15, "Library"),
            ("QTabBar::tab ▸ Render", 91, 16, 36, 15, "Render"),
            ("QTabBar::tab ▸ Show/Hide", 155, 16, 57, 15, "Show/Hide"),
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
        "frame": (490, 451),
        "nodes": (
            ("QTabBar", 12, 12, 466, 22, None),
            ("QTabBar::tab ▸ Look (selected)", 225, 12, 53, 22, None),
            ("QTabBar::tab ▸ Library", 26, 16, 36, 15, "Library"),
            ("QTabBar::tab ▸ Render", 91, 16, 36, 15, "Render"),
            ("QTabBar::tab ▸ Show/Hide", 155, 16, 56, 15, "Show/Hide"),
            ("QTabBar::tab ▸ Look", 239, 16, 26, 15, "Look"),
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
        "frame": (490, 451),
        "nodes": (
            ("QTabBar", 12, 12, 466, 22, None),
            ("QTabBar::tab ▸ About (selected)", 278, 12, 59, 22, None),
            ("QTabBar::tab ▸ Library", 26, 16, 36, 15, "Library"),
            ("QTabBar::tab ▸ Render", 91, 16, 36, 15, "Render"),
            ("QTabBar::tab ▸ Show/Hide", 155, 16, 56, 15, "Show/Hide"),
            ("QTabBar::tab ▸ Look", 239, 16, 25, 15, "Look"),
            ("QTabBar::tab ▸ About", 292, 16, 32, 15, "About"),
            ("QTextBrowser", 20, 42, 450, 227, None),
            ("QScrollBar", 454, 42, 16, 227, None),
            ("QLabel", 148, 278, 322, 15, "Amaze version 1.0.31"),
            ("QPushButton", 148, 303, 108, 22, None),
            ("QPushButton", 264, 303, 90, 22, None),
            ("QPushButton ▸ text", 156, 307, 92, 15, "Check for Updates"),
            ("QPushButton ▸ text", 272, 307, 74, 15, "Report a Bug..."),
            ("QPushButton", 260, 335, 64, 22, None),
            ("QPushButton", 332, 335, 70, 22, None),
            ("QPushButton", 408, 335, 62, 22, None),
            ("ToggleSwitch", 148, 338, 23, 15, None),
            ("ToggleSwitch ▸ text", 179,338, 63, 15, "Debug Mode"),
            ("QPushButton ▸ text", 268, 339, 48, 15, "Open Log"),
            ("QPushButton ▸ text", 340, 339, 54, 15, "Save Log..."),
            ("QPushButton ▸ text", 416, 339, 47, 15, "Clear Log"),
            ("QWidget ▸ group divider", 20, 369, 450, 1, None),
            ("ToggleSwitch", 148, 386, 23, 15, None),
            ("ToggleSwitch ▸ text", 179,386, 59, 15, "Test Library"),
            ("QLineEdit", 148, 409, 292, 22, None),
            ("QPushButton", 442, 409, 28, 22, None),
            ("QLabel", 85, 412, 55, 15, "Test Folder"),
            ("QPushButton ▸ text", 452, 413, 9, 15, "..."),
        ),
    },
    "D09": {   # Save to Amaze - Node
        "frame": (350, 125),
        "nodes": (
            ("QLineEdit", 67, 11, 276, 22, None),
            ("QLabel", 30, 15, 30, 15, "Name"),
            ("QLineEdit ▸ text", 72, 15, 33, 15, "rocks1"),
            ("QComboBox", 67, 37, 276, 22, None),
            ("QLabel", 15, 41, 45, 15, "Category"),
            ("QComboBox ▸ text", 72, 41, 28, 15, "Metal"),
            ("QLineEdit", 67, 63, 276, 22, None),
            ("QLabel", 37, 67, 23, 15, "Tags"),
            ("QPushButton", 254, 94, 31, 22, None),
            ("QPushButton", 293, 94, 50, 22, None),
            ("QPushButton ▸ text", 262, 98, 15, 15, "OK"),
            ("QPushButton ▸ text", 301, 98, 34, 15, "Cancel"),
        ),
    },
    "D11": {   # Save Code to Amaze
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
        "frame": (350, 100),
        "nodes": (
            ("QLabel", 23, 15, 37, 15, "You are"),
            ("QComboBox", 67, 11, 276, 22, None),
            ("QComboBox ▸ text", 72, 15, 27, 15, "Plum"),
            ("QLabel", 6, 41, 54, 15, "New name"),
            ("QLineEdit", 67, 37, 276, 22, None),
            ("QPushButton", 254, 69, 31, 22, None),
            ("QPushButton", 293, 69, 50, 22, None),
            ("QPushButton ▸ text", 262, 73, 15, 15, "OK"),
            ("QPushButton ▸ text", 301, 73, 34, 15, "Cancel"),
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
