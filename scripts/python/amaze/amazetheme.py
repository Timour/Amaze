"""THE DESIGN, in ONE document: every colour, size, placement and word the DESIGNS fix and Houdini's theme does NOT own, so a Figma change is one edit. `helpers/theme.py` holds what FOLLOWS Houdini's live theme; sizes here are the design's number HALVED and go through `theme.ui_px` AT THE CALL SITE. ▸p/one-design-document"""

from __future__ import annotations

HEADER_BAND_H = 30       # ▸ THE DRAWN HEADER: a full-width strip carrying the asset's own name, on D01, D02 and D11 and nowhere else. Its fill and ink follow Houdini (`surface_low`, `text_bright`), so only the geometry is here
HEADER_BAND_INSET = 18   # where the name starts
HEADER_BAND_TEXT_PX = 12
HEADER_BAND_TEXT_BOLD = True    # the drawn weight on D01, D02 and D11

HOUSE_MARGIN = 5         # ▸ the content margin every compact form dialog wears; a dialog records its reason at the call to differ

D01_SELECTED_INK = "#755400"   # ▸ D01 Versions: the picked version's row

D02_MARGINS = (8, 14, 8, 12)   # ▸ D02 Customize (Tile Icon): left, top-under-band, right, bottom
D02_CELL = 34            # one icon button in the chooser grid
D02_COLUMNS = 8          # what the drawn 319 grid column fits at 2px spacing
D02_FIELD_H = 22         # every field, the search and both buttons
D02_SWATCH_GAP = 6
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

SAVE_LABEL_RIGHT = 60    # ▸ the save family D09 and D13: a D09 label ends here, right-aligned
SAVE_FIELD_H = 22
SAVE_BUTTON_H = 22       # the OK / Cancel pair, drawn flush right
SAVE_BUTTON_W = (35, 65)  # OK, Cancel, for a dialog that draws no pair of its own
SAVE_BUTTON_GAP = 6

CODE_FONT = ("SideFX Source Code Pro", 14)    # ▸ D11's code: Houdini's Fixed face ▸r/houdini-code-look
CODE_RADIUS = 3                    # the editor's corners, the current line's, the tab's top ones
CODE_LINE_NUMBER_INK = "#b0b0b0"
CODE_BAND = "#282828"              # ▸ D11's band, and an unselected version tab on it
CODE_TAB = "#373838"               # the selected version tab
CODE_TAB_INK = "#dddcdd"           # a tab's name
CODE_TAB_MAX_W = 200               # a tab is as wide as its name and its ×, up to this
CODE_SYNTAX = {    # ▸ token kind: Houdini's own colour name, and its value in UIDark.hcs headless
    "plain": ("ParmSyntaxPlainColor", "#bcbec3"),
    "comment": ("ParmSyntaxCommentColor", "#7b7e84"),
    "string": ("ParmSyntaxStringColor", "#79a978"),
    "attrib": ("ParmSyntaxVarColor", "#c892ca"),       # @P, v@center
    "number": ("ParmSyntaxNumberColor", "#ebb845"),
    "keyword": ("ParmSyntaxKeywordColor", "#6799c0"),  # if, for, return
    "type": ("ParmSyntaxTypeColor", "#93d4eb"),        # vector, int, float
    "function": ("ParmSyntaxFuncColor", "#8888c1"),    # point, addpoint
}

PREFS_FORM_WIDTH = 490   # ▸ P01-P06 Preferences: the drawn frame less Qt's 8 for a tab widget ▸r/tabwidget-adds-eight
PREFS_INSET = 20         # content to the frame edge, both sides: rows span 20..470
PREFS_DIALOG_MARGIN = 12  # the tabbed window's own margin, outside the tab strip
PREFS_PAGE_MARGIN = 8    # each tab page's margin, inside it: 12 + 8 is the drawn 20
PREFS_CONTENT_WIDTH = 450  # the drawn content column, spanned by every row and divider: 20..470. PINNED, because the page is handed more than this - Qt makes the window 8 wider than the tab widget needs and then lets the page use all of it ▸r/tabwidget-adds-eight
PREFS_TAB_BAR = (12, 12, 466, 22)   # x, y, w, h - the strip above every page
PREFS_SUBTAB_BAR = (12, 44, 129, 22)   # x, y, w, h - Show/Hide's Renderer and Sections strip
PREFS_LABEL_RIGHT = 140  # a form label is RIGHT-aligned and ends here
PREFS_LABEL_COL = 120    # the label column itself, from the inset to LABEL_RIGHT
PREFS_LABEL_GAP = 8      # a label to its field: FIELD_X less LABEL_RIGHT
PREFS_FIELD_X = 148      # every field, button and toggle column starts here
PREFS_FIELD_H = 22       # a line edit, combo or button
PREFS_SPIN_H = 24        # a spin box is 2 taller, its inner line edit inset 1
PREFS_ROW_GAP = 6        # between rows inside one group
PREFS_BUTTON_GAP = 8     # between two controls sharing one row, and a spin box to its slider
PREFS_BROWSE_W = 28      # the `...` button that opens a file dialog
PREFS_DIVIDER_INK = "#434343"   # the 1px group divider; groups carry no title, like Houdini's own parameter panes
PREFS_PAGE_LINE_INK = "#262626"    # ▸ P03a and P03b: the lines along the sub-tab page's top and right
PREFS_DIVIDER_H = 1
UPDATE_WARNING_FILL = "#e0523a"    # ▸ P06: Install Update when the update also updates the library
P05_ROW_PITCH = 101    # ▸ P05: a following row's divider to the next one's, as drawn (139, 240, 341)
P05_LIST_TO_BUTTON = 10    # ▸ P05: the list's bottom to the button's top, as drawn (738 to 748)
P05_DIM_INK = "#7d7d7d"    # ▸ P05: the version and author lines under each picture
P05_TEXT_INK = "#a6a6a6"   # ▸ P05: each row's short description
P01_WARNING_INK = UPDATE_WARNING_FILL    # ▸ P01: the Format line and the line beside Apply, warning
P01_FORMAT_INK = "#80dddddd"    # the Format line otherwise: text at half opacity, as #AARRGGBB
D15_SELECTED_INK = UPDATE_WARNING_FILL   # ▸ D15 Manage Libraries: a row picked for removal
D15_DIM_INK = "#787878"        # a library that cannot be reached: its name and `not connected`
D15_DIM_PATH_INK = "#646464"   # and its path
PREFS_DIVIDER_ABOVE = 8  # inside the divider's own row box
PREFS_DIVIDER_BELOW = 6  # so a divider costs ROW_GAP + ABOVE + H + BELOW + ROW_GAP = 27

MENU_CHIP = (4, 3, 16, 16)     # ▸ the chip submenus (C02b, C09c): x, y, w, h of a chip in its row

LABEL_COLOURS = (              # ▸ the sidebar's Label submenu (C09c): its four chips
    ("Red", "#e0693e"),
    ("Yellow", "#f6ca6d"),
    ("Blue", "#93b9e7"),
    ("Green", "#a4c18a"),
)

COMMENT_INK = "#a05dfe"        # ▸ the Comments pane (N01): the header icon's art colour
COMMENT_DONE_INK = "#4af2a1"   # a done to-do
COMMENT_OPEN_INK = "#ff7760"   # an open to-do
COMMENT_ADD_INK = "#a05dfe"    # the + art's colour
COMMENT_HEADER_BG = "#262626"
COMMENT_PAGE_BG = "#2d2d2d"
COMMENT_DIM_NAME = "Nothing Selected"   # ▸ nothing selected (N01B): the header's two labels,
COMMENT_DIM_TYPE = "Type"
COMMENT_DIM_TEXT_OPACITY = 0.5          # drawn at half their usual ink
COMMENT_DIM_ICON_OPACITY = 0.25         # the speech bubble,
COMMENT_DIM_ICON_INK = "#ffffff"        # in white
COMMENT_DIM_ADD_INK = "#565656"         # the + art; Houdini's menu triangle keeps its colour

LIST_HEADER_BG = "#2a2a2a"       # ▸ list mode's header strip: a QHeaderView picks up none of these, so the strip states them
LIST_HEADER_DIVIDER = "#454545"

TILE_TEXT = "#cdc8bc"           # ▸ the tile and list delegates
TILE_SUBTITLE = "#5d7abd"       # the sidebar's drag highlight until the panel applies the accent
CODE_TEXT_OPACITY = 0.5         # T05B: a code tile's text at half strength, under its run button
CODE_TILE_GROUND = "#1b1b1b"    # and the ground under it, the one the default tile faces have
BADGE_REST_OPACITY = 0.75       # every button badge at rest, ground and icon alike
BADGE_HOVER_OPACITY = 1.0       # and under the pointer
MENU_ICON = 16                  # ▸ C13: a menu entry's icon box, the size Houdini draws it ▸r/menu-checked-look
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
BTN_REMOVE_FROM_LIST = "Remove from List"
BTN_SELECT = "Select"

LABEL_TAGS = "Tags"                 # ▸ field labels and placeholders
LABEL_CATEGORY = "Category"
LABEL_ICON = "Icon"                 # the D02 menu choosing the tile's face
FACE_LABELS = ("Render", "Capture", "Generic", "Custom")    # its items, in `tile_icons.FACES` order
LABEL_LIGHT_ICON = "Light Icon"     # the D02 toggle that replaced the Lines dropdown: OFF = dark lines, ON = light
LABEL_NAME = "Name"
PLACEHOLDER_SEARCH_ICONS = "Search"     # D02 drew the count in it; it does not any more
LABEL_NOT_CONNECTED = "not connected"    # D15: a listed library whose folder cannot be reached
LABEL_CURRENT_LIBRARY = "Current Library: %s"    # D15's band: the open library's name
LABEL_CURRENT_VERSION = "Current Version: %s"    # D01's band: the active version's name
LABEL_LIBRARY_FORMAT = "Format: v%d"     # ▸ P01, under the library's buttons
LABEL_UPGRADES_LIBRARY = "Apply/Accept will upgrade your library to v%d"    # beside Apply
LABEL_LIBRARY_TOO_NEW = "You need to update Amaze to use this library"
LABEL_LIBRARY_UNREACHABLE = "Amaze cannot reach this library"
LABEL_PICK_USER = "Pick or create a user"    # the User list with nobody picked

TITLE_TILE_ICON = "Tile Icon"    # what D02 says when the selection has no ONE name to show
TITLE_MANAGE_LIBRARIES = "Manage Libraries"
BAND_UNTITLED = "Untitled"       # what D11's band says for a snippet that has no name yet
MENU_NEW_VERSION = "New Version"    # D11's + menu, above the snippet's versions
LABEL_VERSIONS = "Versions"         # P01's switch: versions of materials and of code

EMPTY_SHARED = {    # ▸ E06 E08 E09, the blanks every section shares, read by `empty_state.words_for`
    "nothing-matches": (
        'Nothing matches "%s"',
        "No saved %s has that in its name, tags or category.",
        BTN_CLEAR_SEARCH, "clear_filter_box"),
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
    "D01": {   # Versions: a material's versions, newest first
        "frame": (269, 364),
        "nodes": (
            ("header band", 0, 0, 269, 22, None),
            ("QLabel", 8, 3, 253, 15, "Current Version: [name of version] "),
            ("QListWidget", 8, 32, 253, 286, None),
            ("QListWidget ▸ item ▸ selected", 14, 58, 241, 22, None),
            ("QListWidget ▸ item", 19, 38, 90, 15, "Version 2 with red "),
            ("QListWidget ▸ item ▸ path", 194, 38, 56, 15, "2026-10-23"),
            ("QListWidget ▸ item", 19, 62, 168, 15, "Johns version more saturated w..."),
            ("QListWidget ▸ item ▸ path", 194, 62, 56, 15, "2026-10-22"),
            ("QListWidget ▸ item", 19, 86, 116, 15, "Look Development test"),
            ("QListWidget ▸ item ▸ path", 195, 86, 56, 15, "2026-10-22"),
            ("QPushButton", 130, 331, 60, 21, None),
            ("QPushButton", 196, 331, 65, 21, None),
            ("QPushButton ▸ text", 145, 334, 31, 15, "Select"),
            ("QPushButton ▸ text", 211, 334, 34, 15, "Cancel"),
        ),
    },
    "D02": {   # Customize (Tile Icon)
        "frame": (335, 610),
        "nodes": (
            ("header band", 0, 0, 335, 22, None),
            ("QLabel", 8, 3, 82, 15, "[name of asset] "),
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
            ("QPushButton", 184, 576, 65, 22, None),
            ("QPushButton", 255, 576, 72, 22, None),
            ("QPushButton ▸ text", 202, 579, 29, 15, "Apply"),
            ("QPushButton ▸ text", 274, 579, 34, 15, "Accept"),
        ),
    },
    "P01": {   # Preferences - Library
        "frame": (498, 451),
        "nodes": (
            ("QTabBar", 12, 12, 466, 22, None),
            ("QTabBar::tab ▸ Library (selected)", 12, 12, 64, 22, None),
            ("QTabBar::tab ▸ Library", 26, 16, 36, 15, "Library"),
            ("QTabBar::tab ▸ Render", 91, 16, 36, 15, "Render"),
            ("QTabBar::tab ▸ Show/Hide", 155, 16, 56, 15, "Show/Hide"),
            ("QTabBar::tab ▸ Look", 239, 16, 25, 15, "Look"),
            ("QTabBar::tab ▸ Add-On", 292, 16, 39, 15, "Add-On"),
            ("QTabBar::tab ▸ About", 359, 16, 31, 15, "About"),
            ("QComboBox", 148, 42, 260, 22, None),
            ("QPushButton", 414, 42, 56, 22, None),
            ("QLabel", 104, 46, 36, 15, "Library"),
            ("QComboBox ▸ text", 153, 46, 99, 15, "Library folder name"),
            ("QPushButton ▸ text", 432, 46, 20, 15, "Add"),
            ("QPushButton", 148, 70, 63, 22, None),
            ("QPushButton ▸ text", 156, 74, 46, 15, "Clean Up"),
            ("QPushButton", 217, 70, 48, 22, None),
            ("QPushButton ▸ text", 224, 74, 35, 15, "Reload"),
            ("QPushButton", 271, 70, 76, 22, None),
            ("QPushButton ▸ text", 278, 74, 63, 15, "Show Folder"),
            ("QPushButton", 353, 70, 58, 22, None),
            ("QPushButton ▸ text", 362, 74, 40, 15, "Manage"),
            ("QLabel", 148, 98, 320, 15, "Format: v1"),
            ("QWidget ▸ group divider", 20, 127, 450, 1, None),
            ("ToggleSwitch", 148, 142, 23, 15, None),
            ("ToggleSwitch ▸ text", 179, 142, 43, 15, "Versions"),
            ("QComboBox", 148, 165, 196, 22, None),
            ("QPushButton", 352, 165, 56, 22, None),
            ("QPushButton", 414, 165, 56, 22, None),
            ("QLabel", 117, 169, 23, 15, "User"),
            ("QComboBox ▸ text", 153, 169, 27, 15, "Plum"),
            ("QPushButton ▸ text", 360, 169, 42, 15, "Rename"),
            ("QPushButton ▸ text", 422, 169, 33, 15, "Delete"),
            ("QWidget ▸ group divider", 20, 201, 450, 1, None),
            ("QLineEdit", 148, 214, 236, 22, None),
            ("QPushButton", 388, 214, 28, 22, None),
            ("QPushButton", 418, 214, 52, 22, None),
            ("QLabel", 83, 218, 57, 15, "Cache Path"),
            ("QLineEdit ▸ text", 153, 218, 35, 15, "<path>"),
            ("QPushButton ▸ text", 398, 218, 9, 15, "..."),
            ("QPushButton ▸ text", 426, 218, 37, 15, "Default"),
            ("QPushButton", 148, 242, 110, 22, None),
            ("QPushButton ▸ text", 156, 246, 95, 15, "Delete Local Cache"),
            ("QWidget ▸ group divider", 20, 276, 450, 1, None),
            ("QLabel", 20, 292, 301, 15, "Apply/Accept will upgrade your library to v3"),
            ("QPushButton", 327, 289, 65, 22, None),
            ("QPushButton", 398, 289, 72, 22, None),
            ("QPushButton ▸ text", 345, 292, 29, 15, "Apply"),
            ("QPushButton ▸ text", 417, 292, 34, 15, "Accept"),
        ),
    },
    "P02": {   # Preferences - Render
        "frame": (498, 451),
        "nodes": (
            ("QTabBar", 12, 12, 466, 22, None),
            ("QTabBar::tab ▸ Render (selected)", 76, 12, 65, 22, None),
            ("QTabBar::tab ▸ Library", 26, 16, 36, 15, "Library"),
            ("QTabBar::tab ▸ Render", 91, 16, 36, 15, "Render"),
            ("QTabBar::tab ▸ Show/Hide", 155, 16, 56, 15, "Show/Hide"),
            ("QTabBar::tab ▸ Look", 239, 16, 25, 15, "Look"),
            ("QTabBar::tab ▸ Add-On", 292, 16, 39, 15, "Add-On"),
            ("QTabBar::tab ▸ About", 359, 16, 31, 15, "About"),
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
            ("QLabel", 51, 137, 89, 15, "Samples (Octane)"),
            ("QSpinBox ▸ text", 153, 137, 18, 15, "256"),
            ("QLineEdit ▸ text", 154, 137, 18, 15, "256"),
            ("QSpinBox", 148, 162, 64, 24, None),
            ("QLineEdit", 149, 163, 62, 22, None),
            ("ClickSlider", 220, 163, 250, 22, None),
            ("QLabel", 59, 167, 81, 15, "RAM Cache (MB)"),
            ("QSpinBox ▸ text", 153, 167, 18, 15, "256"),
            ("QLineEdit ▸ text", 154, 167, 18, 15, "256"),
            ("QComboBox", 148, 192, 165, 22, None),
            ("QLabel", 46, 196, 94, 15, "Geometry Shading"),
            ("QComboBox ▸ text", 153, 196, 93, 15, "Hidden Line Ghost"),
            ("QComboBox", 148, 220, 165, 22, None),
            ("QLabel", 27, 224, 113, 15, "Geometry Background"),
            ("QComboBox ▸ text", 153, 224, 28, 15, "Black"),
            ("ToggleSwitch", 148, 250, 23, 15, None),
            ("ToggleSwitch ▸ text", 179,250, 132, 15, "Render Thumbs on Import"),
            ("QWidget ▸ group divider", 20, 281, 450, 1, None),
            ("QSpinBox", 148, 294, 64, 24, None),
            ("QLineEdit", 149, 295, 62, 22, None),
            ("ClickSlider", 220, 295, 250, 22, None),
            ("QLabel", 40, 299, 100, 15, "Conversion Threads"),
            ("QSpinBox ▸ text", 153, 299, 6, 15, "4"),
            ("QLineEdit ▸ text", 154, 299, 6, 15, "4"),
            ("QWidget ▸ group divider", 20, 332, 450, 1, None),
            ("QComboBox", 148, 345, 72, 22, None),
            ("QLabel", 32, 349, 108, 15, "Download Resolution"),
            ("QComboBox ▸ text", 153, 349, 12, 15, "2k"),
            ("QSpinBox", 148, 373, 64, 24, None),
            ("QLineEdit", 149, 374, 62, 22, None),
            ("ClickSlider", 220, 374, 250, 22, None),
            ("QLabel", 44, 378, 96, 15, "Parallel Downloads"),
            ("QSpinBox ▸ text", 153, 378, 6, 15, "8"),
            ("QLineEdit ▸ text", 154, 378, 6, 15, "8"),
        ),
    },
    "P03a": {   # Preferences - Show/Hide ▸ Renderer
        "frame": (498, 451),
        "nodes": (
            ("QTabBar", 12, 12, 466, 22, None),
            ("QTabBar::tab ▸ Show/Hide (selected)", 141, 12, 84, 22, None),
            ("QTabBar::tab ▸ Library", 26, 16, 36, 15, "Library"),
            ("QTabBar::tab ▸ Render", 91, 16, 36, 15, "Render"),
            ("QTabBar::tab ▸ Show/Hide", 155, 16, 56, 15, "Show/Hide"),
            ("QTabBar::tab ▸ Look", 239, 16, 25, 15, "Look"),
            ("QTabBar::tab ▸ Add-On", 292, 16, 39, 15, "Add-On"),
            ("QTabBar::tab ▸ About", 359, 16, 31, 15, "About"),
            ("QTabBar", 12, 44, 129, 22, None),
            ("QTabBar::tab ▸ Renderer (selected)", 12, 44, 71, 22, None),
            ("QTabBar::tab ▸ Renderer", 26, 48, 46, 15, "Renderer"),
            ("QTabBar::tab ▸ Sections", 91, 48, 43, 15, "Sections"),
            ("ToggleSwitch", 148, 76, 23, 15, None),
            ("ToggleSwitch ▸ text", 179, 76, 47, 15, "MaterialX"),
            ("ToggleSwitch", 148, 101, 23, 15, None),
            ("ToggleSwitch ▸ text", 179, 101, 41, 15, "Redshift"),
            ("ToggleSwitch", 148, 126, 23, 15, None),
            ("ToggleSwitch ▸ text", 179, 126, 36, 15, "Octane"),
            ("Line 1", 12, 67, 474, 0, None),
            ("Line 2", 486, 66, 0, 373, None),
        ),
    },
    "P03b": {   # Preferences - Show/Hide ▸ Sections
        "frame": (498, 451),
        "nodes": (
            ("QTabBar", 12, 12, 466, 22, None),
            ("QTabBar::tab ▸ Show/Hide (selected)", 141, 12, 84, 22, None),
            ("QTabBar::tab ▸ Library", 26, 16, 36, 15, "Library"),
            ("QTabBar::tab ▸ Render", 91, 16, 36, 15, "Render"),
            ("QTabBar::tab ▸ Show/Hide", 155, 16, 56, 15, "Show/Hide"),
            ("QTabBar::tab ▸ Look", 239, 16, 25, 15, "Look"),
            ("QTabBar::tab ▸ Add-On", 292, 16, 39, 15, "Add-On"),
            ("QTabBar::tab ▸ About", 359, 16, 31, 15, "About"),
            ("QTabBar", 12, 44, 129, 22, None),
            ("QTabBar::tab ▸ Sections (selected)", 81, 44, 60, 22, None),
            ("QTabBar::tab ▸ Renderer", 26, 48, 46, 15, "Renderer"),
            ("QTabBar::tab ▸ Sections", 91, 48, 43, 15, "Sections"),
            ("ToggleSwitch", 148, 76, 23, 15, None),
            ("ToggleSwitch ▸ text", 179, 76, 41, 15, "Material"),
            ("ToggleSwitch", 148, 101, 23, 15, None),
            ("ToggleSwitch ▸ text", 179, 101, 28, 15, "Color"),
            ("ToggleSwitch", 148, 126, 23, 15, None),
            ("ToggleSwitch ▸ text", 179, 126, 27, 15, "Node"),
            ("ToggleSwitch", 148, 151, 23, 15, None),
            ("ToggleSwitch ▸ text", 179, 151, 26, 15, "Code"),
            ("ToggleSwitch", 148, 176, 23, 15, None),
            ("ToggleSwitch ▸ text", 179, 176, 18, 15, "File"),
            ("Line 1", 12, 67, 474, 0, None),
            ("Line 2", 486, 66, 0, 373, None),
        ),
    },
    "P04": {   # Preferences - Look
        "frame": (498, 451),
        "nodes": (
            ("QTabBar", 12, 12, 466, 22, None),
            ("QTabBar::tab ▸ Look (selected)", 225, 12, 53, 22, None),
            ("QTabBar::tab ▸ Library", 26, 16, 36, 15, "Library"),
            ("QTabBar::tab ▸ Render", 91, 16, 36, 15, "Render"),
            ("QTabBar::tab ▸ Show/Hide", 155, 16, 56, 15, "Show/Hide"),
            ("QTabBar::tab ▸ Look", 239, 16, 25, 15, "Look"),
            ("QTabBar::tab ▸ Add-On", 292, 16, 39, 15, "Add-On"),
            ("QTabBar::tab ▸ About", 359, 16, 31, 15, "About"),
            ("ToggleSwitch", 148, 44, 23, 15, None),
            ("ToggleSwitch ▸ text", 179,44, 137, 15, "Show Counts on Categories"),
            ("ToggleSwitch", 148, 69, 23, 15, None),
            ("ToggleSwitch ▸ text", 179,69, 114, 15, "Hide Empty Categories"),
            ("ToggleSwitch", 148, 94, 23, 15, None),
            ("ToggleSwitch ▸ text", 179,94, 46, 15, "Step Size"),
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
    "P05": {   # Preferences - Add-On: drawn 885 tall in FIGMA ONLY; the app opens at PREFS_FRAME
        "frame": (498, 885),
        "nodes": (
            ("QTabBar", 12, 12, 466, 22, None),
            ("QTabBar::tab ▸ Add-On (selected)", 278, 12, 67, 22, None),
            ("QTabBar::tab ▸ Library", 26, 16, 36, 15, "Library"),
            ("QTabBar::tab ▸ Render", 84, 16, 36, 15, "Render"),
            ("QTabBar::tab ▸ Show/Hide", 155, 16, 56, 15, "Show/Hide"),
            ("QTabBar::tab ▸ Look", 239, 16, 25, 15, "Look"),
            ("QTabBar::tab ▸ Add-On", 292, 16, 39, 15, "Add-On"),
            ("QTabBar::tab ▸ About", 359, 16, 31, 15, "About"),
            ("QTextBrowser", 20, 38, 450, 801, None),
            ("QScrollBar", 454, 38, 16, 801, None),
            ("add-on picture", 20, 38, 54, 54, None),
            ("ToggleSwitch", 118, 57, 23, 15, None),
            ("ToggleSwitch ▸ text", 149, 57, 79, 15, None),
            ("add-on version", 20, 94, 63, 15, None),
            ("add-on author", 20, 109, 87, 15, None),
            ("add-on short description", 284, 38, 165, 94, None),
            ("QWidget ▸ group divider", 20, 139, 434, 1, None),
            ("add-on picture", 20, 147, 54, 54, None),
            ("ToggleSwitch", 118, 167, 23, 15, None),
            ("ToggleSwitch ▸ text", 149, 167, 103, 15, None),
            ("add-on version", 20, 203, 63, 15, None),
            ("add-on author", 20, 218, 87, 15, None),
            ("add-on short description", 284, 147, 165, 86, None),
            ("QPushButton", 118, 849, 108, 22, None),
            ("QPushButton ▸ text", 126, 853, 92, 15, "Check for Updates"),
            ("QLabel", 239, 853, 231, 15, None),
        ),
    },
    "P06": {   # Preferences - About
        "frame": (498, 451),
        "nodes": (
            ("QTabBar", 12, 12, 466, 22, None),
            ("QTabBar::tab ▸ About (selected)", 345, 12, 59, 22, None),
            ("QTabBar::tab ▸ Library", 26, 16, 36, 15, "Library"),
            ("QTabBar::tab ▸ Render", 91, 16, 36, 15, "Render"),
            ("QTabBar::tab ▸ Show/Hide", 155, 16, 56, 15, "Show/Hide"),
            ("QTabBar::tab ▸ Look", 239, 16, 25, 15, "Look"),
            ("QTabBar::tab ▸ Add-On", 292, 16, 39, 15, "Add-On"),
            ("QTabBar::tab ▸ About", 359, 16, 31, 15, "About"),
            ("QTextBrowser", 20, 42, 450, 227, None),
            ("QScrollBar", 454, 42, 16, 227, None),
            ("QLabel", 148, 274, 322, 15, "Amaze v x.x.x is available. The library will be updated to v x"),
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
            ("QLineEdit", 260, 371, 180, 22, None),
            ("QPushButton", 442, 371, 28, 22, None),
            ("QPushButton ▸ text", 452, 375, 9, 15, "..."),
            ("ToggleSwitch", 148, 403, 23, 15, None),
            ("ToggleSwitch ▸ text", 179, 403, 107, 15, "Add-On beta versions"),
        ),
    },
    "D09": {   # Save to Amaze - the Section row picks where the save lands
        "frame": (293, 185),
        "nodes": (
            ("QComboBox", 67, 14, 218, 22, None),
            ("QLabel", 22, 18, 38, 15, "Section"),
            ("QComboBox ▸ text", 72, 18, 41, 15, "Material"),
            ("QLineEdit", 67, 40, 218, 22, None),
            ("QLabel", 30, 44, 30, 15, "Name"),
            ("QLineEdit ▸ text", 72, 44, 33, 15, "rocks1"),
            ("QComboBox", 67, 66, 218, 22, None),
            ("QLabel", 15, 69.5, 45, 15, "Category"),
            ("QComboBox ▸ text", 72, 69.5, 28, 15, "Metal"),
            ("QComboBox", 67, 92, 218, 22, None),
            ("QLabel", 11, 96, 49, 15, "Language"),
            ("QComboBox ▸ text", 72, 96, 19, 15, "VEX"),
            ("QLineEdit", 67, 118, 218, 22, None),
            ("QLabel", 37, 121.5, 23, 15, "Tags"),
            ("QPushButton", 179, 151, 35, 22, None),
            ("QPushButton", 220, 151, 65, 22, None),
            ("QPushButton ▸ text", 189, 154, 15, 15, "OK"),
            ("QPushButton ▸ text", 236, 154, 34, 15, "Cancel"),
        ),
    },
    "D11": {   # Code snippet - New Snippet and Edit; a node's code saves through D09
        "frame": (638, 516),
        "nodes": (
            ("header band", 0, 0, 638, 22, None),
            ("header band ▸ tab", 0, 0, 128, 22, None),
            ("header band ▸ tab", 129, 0, 128, 22, None),    # drawn selected
            ("QLabel", 13, 3, 93, 15, "[name of Version] "),
            ("QLabel", 142, 3, 93, 15, "[name of Version] "),
            ("icon ▸ close ▸ icon_tab_close.svg", 108, 0, 22, 22, None),
            ("icon ▸ close ▸ icon_tab_close.svg", 235, 0, 22, 22, None),
            ("icon ▸ add ▸ icon_version_add.svg", 257, 0, 22, 22, None),
            ("QLineEdit", 70, 36, 245, 22, None),
            ("QComboBox", 385, 36, 245, 22, None),
            ("QLabel", 33, 36.5, 30, 15, "Name"),
            ("QLineEdit ▸ text", 75, 36.5, 33, 15, "helper"),
            ("QLabel", 333, 39.5, 45, 15, "Category"),
            ("QComboBox ▸ text", 390, 40, 28, 15, "Metal"),
            ("QComboBox", 70, 67, 245, 22, None),
            ("QLineEdit", 385, 67, 245, 22, None),
            ("QLabel", 14, 70.5, 49, 15, "Language"),
            ("QComboBox ▸ text", 75, 70.5, 19, 15, "VEX"),
            ("QLabel", 355, 70.5, 23, 15, "Tags"),
            ("CodeEditor", 8, 109, 622, 364, None),
            ("CodeEditor ▸ line numbers", 11, 109, 22, 363, "1\n2\n3\n4\n5\n6"),
            ("CodeEditor ▸ text", 33, 109, 548, 253,
             "// Facing ratio toward the camera\n"
             "vector camP = point(1, \"P\", 0);            // 2nd input: a single cam point,\n"
             "if (@numpt < 0) camP = getbbox_center(0);  // or wire nothing and edit here\n"
             "vector toCam = normalize(camP - @P);\n"
             "f@facing = fit(abs(dot(normalize(@N), toCam)), 0, 1, 0, 1);\n"
             "@Cd = f@facing;"),
            ("CodeEditor ▸ current line", 14, 129, 610, 16, None),
            ("QPushButton", 494, 482, 65, 22, None),
            ("QPushButton", 565, 482, 65, 22, None),
            ("QPushButton ▸ text", 512, 485, 29, 15, "Apply"),
            ("QPushButton ▸ text", 581, 485, 34, 15, "Cancel"),
        ),
    },
    "D13": {   # Name Input
        "frame": (293, 81),
        "nodes": (
            ("QLineEdit", 57, 14, 228, 22, None),
            ("QLabel", 20, 17.5, 30, 15, "Name"),
            ("QLineEdit ▸ text", 62, 17.5, 30, 15, "Warm"),
            ("QPushButton", 179, 47, 35, 22, None),
            ("QPushButton", 220, 47, 65, 22, None),
            ("QPushButton ▸ text", 189, 50, 15, 15, "OK"),
            ("QPushButton ▸ text", 236, 50, 34, 15, "Cancel"),
        ),
    },
    "D15": {   # Manage Libraries - the Library list, opened from Preferences ▸ Library
        "frame": (420, 247),
        "nodes": (
            ("header band", 0, 0, 420, 22, None),
            ("QLabel", 8, 3, 206, 15, "Current Library: [current library name]"),
            ("QListWidget", 8, 32, 404, 170, None),
            ("QListWidget ▸ item", 19, 38, 71, 15, "Studio Library"),
            ("QListWidget ▸ item ▸ path", 130, 38, 158, 15, "/Volumes/Server/Amaze/Studio"),
            ("QListWidget ▸ item ▸ selected", 14, 58, 392, 22, None),
            ("QListWidget ▸ item", 19, 62, 69, 15, "Client Archive"),
            ("QListWidget ▸ item ▸ path", 130, 62, 170, 15, "/Volumes/Projects/Archive/Amaze"),
            ("QListWidget ▸ item", 19, 86, 95, 15, "Look Development"),
            ("QListWidget ▸ item ▸ path", 130, 86, 91, 15, "~/Amaze/LookDev"),
            ("QListWidget ▸ item", 19, 110, 56, 15, "Old Library"),
            ("QListWidget ▸ item ▸ path", 130, 110, 148, 15, "/Volumes/Backup/Amaze/Old"),
            ("QListWidget ▸ item ▸ not connected", 328, 110, 72, 15, "not connected"),
            ("QPushButton", 237, 213, 104, 22, None),
            ("QPushButton", 347, 213, 65, 22, None),
            ("QPushButton ▸ text", 245, 217, 88, 15, "Remove from List"),
            ("QPushButton ▸ text", 363, 216, 34, 15, "Cancel"),
        ),
    },
    "T01": {   # the grid tile, drawn at TILE_DRAWN_SIZE - its spacing is what the delegate paints
        "frame": (138, 177),
        "nodes": (
            ("tile card", 4, 4, 130, 173, None),
            ("thumbnail", 4, 4, 130, 130, None),
            ("badge renderer (lower-right) ▸ badge_renderer", 110, 110, 22, 22, None),
            ("badge favourite (top-right) ▸ badge_favourite", 110, 6, 22, 22, None),
            ("badge versions (lower-left) ▸ badge_versions", 6, 110, 22, 22, None),
            ("badge comment (lower-right) ▸ badge_comment", 6, 6, 22, 22, None),
            ("tile name", 9, 142, 74, 15, "brushed_steel"),
            ("tile subtitle", 9, 157, 49, 15, "MaterialX"),
        ),
    },
    "T08": {   # a scene file's tile on its default face, with the open badge
        "frame": (138, 177),
        "nodes": (
            ("tile card", 4, 4, 130, 173, None),
            ("thumbnail", 4, 4, 130, 130, None),
            ("face ▸ icon_hip.svg", 4, 4, 130, 130, None),
            ("tile name", 9, 142, 47, 15, "shot_010"),
            ("tile subtitle", 9, 157, 18, 15, "HIP"),
            ("badge favourite (top-right) ▸ badge_favourite", 110, 6, 22, 22, None),
            ("badge open (top-left) ▸ badge_open", 110, 110, 22, 22, None),
        ),
    },
    "T05": {   # the code tile on its generic face: Run in the middle, Versions and Edit below
        "frame": (138, 177),
        "nodes": (
            ("tile card", 4, 4, 130, 173, None),
            ("thumbnail", 4, 4, 130, 130, None),
            ("face ▸ face_code.svg", 4, 4, 130, 130, None),
            ("tile name", 9, 142, 52, 15, "Mtxl to RS"),
            ("tile subtitle", 9, 157, 37, 15, "Python"),
            ("badge favourite (top-right) ▸ badge_favourite", 110, 6, 22, 22, None),
            ("badge edit (lower-left) ▸ badge_edit", 110, 110, 22, 22, None),
            ("badge comment (lower-right) ▸ badge_comment", 6, 6, 22, 22, None),
            ("badge execute (centre) ▸ badge_execute", 46, 46, 45, 45, None),
            ("badge versions (lower-left) ▸ badge_versions", 6, 110, 22, 22, None),
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
            ("button ▸ btn_hip_capture", 1458, 3, 24, 24, None),
            ("button ▸ btn_prefs", 1484, 3, 24, 24, None),
            ("icon ▸ btn_categories ▸ icon_categories.svg", 6, 7, 16, 16, None),
            ("icon ▸ btn_menu_view ▸ icon_renderer.svg", 31, 6, 18, 18, None),
            ("icon ▸ btn_menu_filter ▸ icon_view.svg", 57, 6, 18, 18, None),
            ("icon ▸ btn_online ▸ icon_online.svg", 84, 7, 16, 16, None),
            ("icon ▸ btn_notes ▸ icon_comments.svg", 110, 7, 16, 16, None),
            ("icon ▸ cb_viewmode ▸ list.svg", 136, 7, 16, 16, None),
            ("icon ▸ cb_favsonly ▸ favourite_on.svg", 162, 7, 15, 15, None),
            ("icon ▸ line_filter ▸ icon_search.svg", 478, 8, 13, 13, None),
            ("icon ▸ btn_hip_capture ▸ icon_screenshot.svg", 1461, 6, 18, 18, None),
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
            ("text ▸ type", 118, 7, 71, 15, "USD MaterialX"),
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

D01_FRAME = DIALOG_LAYOUT["D01"]["frame"]    # ▸ the frame sizes call sites name, read from the drawing
D02_FORM_WIDTH, D02_FRAME_H = DIALOG_LAYOUT["D02"]["frame"]    # the OPENING size; the grid grows
SAVE_WIDTH = DIALOG_LAYOUT["D09"]["frame"][0]    # D09 and D13 alike, whatever their labels
SAVE_FIELD_WIDTH = next(n[3] for n in DIALOG_LAYOUT["D09"]["nodes"] if n[0] == "QLineEdit")
NAME_FIELD_WIDTH = next(n[3] for n in DIALOG_LAYOUT["D13"]["nodes"] if n[0] == "QLineEdit")
D15_WIDTH = DIALOG_LAYOUT["D15"]["frame"][0]
D11_FORM_WIDTH = DIALOG_LAYOUT["D11"]["frame"][0]    # a FLOOR: D11 resizes around its editor
PREFS_FRAME = DIALOG_LAYOUT["P01"]["frame"]    # every Preferences tab, P01-P06

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
            repeats.setdefault((plain, text), []).append(   # SMALLEST of the rects around THIS node: P02 draws `256` in three rows, so a repeated label must answer one box per drawing of it and always the same one
                min(holding, key=lambda box: box[2] * box[3]))
            boxes.setdefault((plain, text), repeats[(plain, text)][0])
    _DRAWN_BOXES[frame_key] = boxes
    _DRAWN_REPEATS[frame_key] = {key: tuple(found)
                                 for key, found in repeats.items()}
    return boxes


def drawn_repeats(frame_key: str, kind: str, text) -> tuple:
    """Every box a call site may pin from for `(kind, text)`, in DRAWN order: one per `<kind> ▸ <text>` node, since a frame may draw a label twice - P01 draws the `...` browse button at two places - or, for `text=None`, every plain `<kind>` rect down the frame. `drawn_boxes` answers the first of them."""
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


def drawn_pair_gap(frame_key: str):
    """The drawn gap between a frame's two buttons, left to right; None unless it draws two."""
    nodes = (DIALOG_LAYOUT.get(frame_key) or {}).get("nodes", ())
    pair = sorted((n for n in nodes if n[0] == "QPushButton" and n[5] is None),
                  key=lambda n: n[1])
    if len(pair) != 2:
        return None
    return pair[1][1] - (pair[0][1] + pair[0][3])


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


def drawn_band(frame_key: str) -> tuple:
    """(height, text inset) of the frame's header band; the house band's for a frame without one."""
    nodes = (DIALOG_LAYOUT.get(frame_key) or {}).get("nodes", ())
    band = next((n for n in nodes if n[0] == "header band"), None)
    if band is None:
        return HEADER_BAND_H, HEADER_BAND_INSET
    label = next((n for n in nodes if n[0] == "QLabel" and n[2] < band[2] + band[4]), None)
    return band[4], (label[1] - band[1]) if label else HEADER_BAND_INSET


def drawn_code_dialog(frame_key: str = "D11") -> dict:
    """The code dialog's margins and gaps, its two label columns, and the editor's own figures."""
    layout = DIALOG_LAYOUT[frame_key]
    width, height = layout["frame"]
    nodes = layout["nodes"]

    def one(name):
        found, = (n for n in nodes if n[0] == name)
        return found

    band, editor = one("header band"), one("CodeEditor")
    tabs = sorted((n for n in nodes if n[0] == "header band ▸ tab"), key=lambda n: n[1])
    tab = tabs[-1]    # the selected one: its × ends flush with it
    close = max((n for n in nodes if n[0] == "icon ▸ close ▸ icon_tab_close.svg"),
                key=lambda n: n[1])
    plus = one("icon ▸ add ▸ icon_version_add.svg")
    numbers, text = one("CodeEditor ▸ line numbers"), one("CodeEditor ▸ text")
    line = one("CodeEditor ▸ current line")
    fields = sorted((n for n in nodes if n[0] in ("QLineEdit", "QComboBox")),
                    key=lambda n: (n[2], n[1]))
    left, below = fields[0], fields[2]    # row one's first field, row two's first
    button = min((n for n in nodes if n[0] == "QPushButton"), key=lambda n: n[1])
    labels = [n for n in nodes if n[0] == "QLabel" and n[2] >= band[4]]
    label_end = max(n[1] + n[3] for n in labels if n[1] + n[3] <= left[1])
    right = [n for n in labels if n[1] >= left[1] + left[3]]
    right_end, right_column = max(n[1] + n[3] for n in right), max(n[3] for n in right)
    return {
        "margins": (editor[1], left[2] - band[4], width - editor[1] - editor[3],
                    height - button[2] - button[4]),
        "row_gap": below[2] - left[2] - left[4],
        "stack_gap": editor[2] - below[2] - below[4],
        "button_gap": button[2] - editor[2] - editor[4],
        "field": (left[3], left[4]),
        "label_gap": left[1] - label_end,
        "label_columns": (label_end - editor[1], right_column),
        "half_gap": right_end - right_column - left[1] - left[3],
        "editor": (editor[3], editor[4]),
        "gutter": (numbers[1] - editor[1], numbers[3]),
        "text_x": text[1] - editor[1],
        "current_line": (line[1] - editor[1], editor[1] + editor[3] - line[1] - line[3],
                         line[4]),
        "tab": (tab[3], tab[4]),
        "tab_gap": tab[1] - tabs[-2][1] - tabs[-2][3] if len(tabs) > 1 else 0,
        "tab_text": next((n[1] - tab[1], n[2], n[4]) for n in nodes    # x in the tab, y, height
                         if n[0] == "QLabel" and n[2] < band[4] and n[1] >= tab[1]),
        "tab_close": (close[3], close[4], tab[1] + tab[3] - close[1] - close[3]),    # w, h, inset
        "plus": plus[1:5],
        "plus_gap": plus[1] - tab[1] - tab[3],
    }


def drawn_list_rows(frame_key: str = "D15") -> dict:
    """A drawn list's margins, its row pitch, the painted row box and where each text sits in it."""
    layout = DIALOG_LAYOUT[frame_key]

    def named(name):
        return sorted((n for n in layout["nodes"] if n[0] == name),
                      key=lambda n: (n[2], n[1]))

    view, = named("QListWidget")
    names, paths = named("QListWidget ▸ item"), named("QListWidget ▸ item ▸ path")
    box, = named("QListWidget ▸ item ▸ selected")
    flag = (named("QListWidget ▸ item ▸ not connected") or paths)[0]    # D01 draws no flag
    buttons = named("QPushButton")
    pitch = names[1][2] - names[0][2]
    width, height = layout["frame"]
    return {
        "margins": (view[1], view[2] - drawn_band(frame_key)[0],    # left, top under the band,
                    width - (view[1] + view[3]),                      # right, bottom
                    height - (buttons[0][2] + buttons[0][4])),
        "view": (view[3], view[4]),
        "button_top": buttons[0][2] - (view[2] + view[4]),    # the list's bottom to the buttons
        "button_gap": buttons[1][1] - (buttons[0][1] + buttons[0][3]),
        "pitch": pitch,
        "box_x": box[1] - view[1],
        "box_y": (box[2] - view[2]) % pitch,
        "box_h": box[4],
        "text_y": next(n[2] for n in names if box[2] <= n[2] < box[2] + box[4]) - box[2],
        "text_h": names[0][4],
        "name_x": names[0][1] - box[1],
        "path_x": paths[0][1] - box[1],
        "flag_right": box[1] + box[3] - (flag[1] + flag[3]),
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
