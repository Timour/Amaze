"""THE DESIGN, in ONE document: every colour, size, placement and word the DESIGNS fix and Houdini's theme does NOT own, so a Figma change is one edit. `helpers/theme.py` holds what FOLLOWS Houdini's live theme; sizes here are the design's number HALVED and go through `theme.ui_px` AT THE CALL SITE. ▸p/one-design-document"""

from __future__ import annotations

HEADER_BAND_H = 30       # ▸ THE DRAWN HEADER: a full-width strip carrying the asset's own name, on D01, D02 and D11 and nowhere else. Its fill and ink follow Houdini (`surface_low`, `text_bright`), so only the geometry is here
HEADER_BAND_INSET = 18   # where the name starts
HEADER_BAND_TEXT_PX = 12
HEADER_BAND_TEXT_BOLD = True    # the drawn weight on D01, D02 and D11

D01_FRAME = (256, 185)      # ▸ D01 Versions, header band included
D01_INSET = 18              # 35, both sides, leaving a 220-wide column
D01_FIRST_FIELD_Y = 15      # 30, the first field's top
D01_FIELD_H = 30            # 60
D01_BUTTON = (101, 21)      # 202 x 42
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
D02_PREVIEW = 150        # the preview square, left of the switch stack
D02_FIELD_H = 22         # every field, the search and both buttons
D02_SWATCH_H = 28        # the preset chips AND the current-colour chip
D02_SWATCH_GAP = 6
D02_BUTTON_W = 72        # Apply and Accept, drawn flush right - they do NOT span the column
D02_CHIP_W = 75          # the current-colour chip beside the Custom Color label; clicking it IS the picker
D02_STACK_GAP = 13       # preview to the switch stack, and its label column to its fields
D02_ROW_GAP = 9          # between the stacked field rows, and the column rhythm below them
D02_LABEL_GAP = 8        # a label to its field in the top form
D02_GRID_GAP = 6         # search to the grid
D02_SECTION_GAP = 37     # the switch pair to the Custom Color row - with PRESET_GAP it makes the stack exactly the preview's 150
D02_PRESET_GAP = 10      # the current-colour chip to the preset row
D02_TOP_GAP = 11         # the Tags row to the preview block
D02_BUTTON_GAP = 8       # grid to the button row

SAVE_WIDTH = 350         # ▸ the save family D09, D10, D12, D13: every one is this wide, whatever its labels
SAVE_FIELD_WIDTH = 276   # the drawn field width inside it

D11_FORM_WIDTH = 638     # ▸ D11 Save Code: a FLOOR, not a pin - the only dialog that resizes, because it carries an editor
D11_EDITOR_H = 364       # the editor's minimum HEIGHT; it spans the full content width, under the two-column form
D11_MARGINS = (18, 19, 8, 13)  # left, top-under-band, right, bottom
D11_FIELD_H = 22         # every field and button in the frame
D11_ROW_GAP = 4          # between the two form rows
D11_LABEL_GAP = 7        # label to its field
D11_HALF_GAP = 18        # between the two form halves
D11_STACK_GAP = 12       # fields to the editor
D11_BUTTON_GAP = 8       # editor to the OK/Cancel row

PREFS_FORM_WIDTH = 490   # ▸ D04-D08 Preferences, the one tabbed window
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
