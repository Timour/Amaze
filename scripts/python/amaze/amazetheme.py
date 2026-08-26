"""THE DESIGN, in ONE document: every colour, size, placement and word the DESIGNS fix and Houdini's theme does NOT own, so a Figma change is one edit. `helpers/theme.py` holds what FOLLOWS Houdini's live theme; sizes here are the design's number HALVED and go through `theme.ui_px` AT THE CALL SITE. ▸p/one-design-document"""

from __future__ import annotations

D01_FRAME = (256, 158)      # ▸ D01 Versions, no header block: the name rides the window title. The design's 512 x 316
D01_INSET = 18              # 35, both sides, leaving a 220-wide column
D01_FIRST_FIELD_Y = 15      # 30, the first field's top
D01_FIELD_H = 30            # 60
D01_BUTTON = (101, 21)      # 202 x 42
D01_BUTTON_GAP = 19         # 38
D01_RADIUS = 5              # 10
D01_LABEL_PX = 10
D01_BUTTON_PX = 12
D01_LABEL_INK = "#93b9e7"   # the accent-blue field label, e.g. Change Name

D02_CELL = 34            # ▸ D02 Customize (Tile Icon): one icon button in the chooser grid
D02_COLUMNS = 10         # how wide the grid runs before wrapping
D02_SIDE_WIDTH = 150     # preview, swatches and buttons all measure this

SAVE_WIDTH = 350         # ▸ the save family D09, D10, D12, D13: every one is this wide, whatever its labels
SAVE_FIELD_WIDTH = 276   # the drawn field width inside it

D11_FORM_WIDTH = 638     # ▸ D11 Save Code: a FLOOR, not a pin - the only dialog that resizes, because it carries an editor. Its field column follows from this width, so there is no second number for it
D11_EDITOR_H = 320       # the editor's minimum HEIGHT; its width is the field column above
D11_DESC_H = 56          # the Description box, drawn in no Figma frame yet ▸p/one-design-document

PREFS_FORM_WIDTH = 480   # ▸ D04-D08 Preferences, the one tabbed window
PREFS_HEADROOM = 50      # rendered px added to the natural content height

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
BTN_REMOVE = "Remove"
BTN_CUSTOM_COLOR = "Custom Color..."
BTN_ADD_FOLDER = "Add Folder"
BTN_CLEAR_SEARCH = "Clear Search"
BTN_SHOW_ALL = "Show All"
BTN_LOCATE = "Locate"
BTN_NEW_FILE = "New File"

LABEL_CHANGE_NAME = "Change Name"       # ▸ field labels and placeholders
LABEL_ICON_COLOR = "Icon Color"
LABEL_TAGS = "Tags"
LABEL_NAME = "Name"
PLACEHOLDER_TAGS = "metal, rough"
PLACEHOLDER_VERSION_NAME = "Rename this version"

TITLE_TILE_ICON = "Tile Icon"    # what D02 says when the selection has no ONE name to show

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
