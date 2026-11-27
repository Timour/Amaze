"""The design's fixed values; sizes are halved, scaled by `theme.ui_px`. ▸p/one-design-document"""

from __future__ import annotations

HEADER_BAND_H = 30       # ▸ THE DRAWN HEADER: the strip D11 shows; fill and text colour follow Houdini
HEADER_BAND_INSET = 18   # where the name starts
HEADER_BAND_TEXT_PX = 12
HEADER_BAND_TEXT_BOLD = True    # the drawn weight on D11

FORM_DIALOG_MARGIN = 5        # ▸ the content margin every compact form dialog uses


D02_MARGINS = (8, 12, 8, 12)   # ▸ D02 Customize (Tile Icon): left, top, right, bottom
D02_CELL = 34            # one icon button in the chooser grid
D02_COLUMNS = 8          # what the drawn 319 grid column fits at 2px spacing
D02_FIELD_H = 22         # every field, the search and both buttons
D02_SWATCH_GAP = 6
D02_CHIP_W = 35          # the current-colour chip beside the Custom Color label, swatch-sized
D02_STACK_GAP = 13       # preview to the switch stack, and its label column to its fields
D02_ROW_GAP = 9          # between the stacked field rows, and the column rhythm below them
D02_LABEL_GAP = 8        # a label to its field in the top form
D02_FACE_GAP = 6         # the Image label to its menu
D02_GRID_GAP = 6         # search to the grid
D02_SECTION_GAP = 37     # the Image menu's row to the Light Icons row
D02_PRESET_GAP = 10      # the current-colour chip to the preset row
D02_TOP_GAP = 9          # the Tags row to the Image menu
D02_PREVIEW_DROP = 2     # the Image menu's top to the preview square's
D02_BUTTON_GAP = 8       # grid to the button row
D02_GRID_SPACING = 2     # the chooser grid's cell gap, unscaled; D02_COLUMNS assumes it
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
CODE_LINE_NUMBER_TEXT_COLOR = "#b0b0b0"
CODE_BAND = "#272727"              # ▸ D11's band, and an unselected version tab on it
CODE_TAB = "#383838"               # the selected version tab
CODE_BACKGROUND = "#383838"            # the window behind the form and the editor, which the selected tab joins
CODE_TAB_TEXT_COLOR = "#dddddd"           # a tab's name
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

P01_LIGHT_IDLE = "#787878"      # ▸ P01's Check Database light before a check, filled, no stroke
P01_LIGHT_CLEAN = "#3fc28a"     # the check found nothing
P01_LIGHT_FOUND = "#ff3600"     # the check found something
P01_LIGHT_UNCHECKED = "#ffae00"  # a part could not be checked now

MENU_CHIP = (4, 3, 16, 16)     # ▸ the chip submenus (C02b, C09c): x, y, w, h of a chip in its row

LABEL_COLOURS = (              # ▸ the sidebar's Label submenu (C09c): its four chips
    ("Red", "#e0693e"),
    ("Yellow", "#f6ca6d"),
    ("Blue", "#93b9e7"),
    ("Green", "#a4c18a"),
)

COMMENT_ICON_COLOR = "#765d99"   # ▸ the Comments pane (N01): its header icon, and its toolbar button while open
COMMENT_ICON_ART_COLOR = "#5d7abd"    # the colour icon_comments.svg is drawn in; COMMENT_ICON_COLOR replaces it
COMMENT_DONE_COLOR = "#4af2a1"   # a done to-do
COMMENT_OPEN_COLOR = "#ff7760"   # an open to-do
COMMENT_ADD_COLOR = "#dddddd"    # the + art's colour
COMMENT_HEADER_BG = "#272727"
COMMENT_PAGE_BG = "#2d2d2d"
SIDE_PANE_BAND_BG = "#1b1b1b"    # the QML side pane's header band, as N01 and N02 draw it
COMMENT_DIM_NAME = "Nothing Selected"   # ▸ nothing selected (N01B): the header's two labels,
COMMENT_DIM_TYPE = "Type"
COMMENT_DIM_TEXT_OPACITY = 0.5          # drawn at half their usual opacity
COMMENT_DIM_ICON_OPACITY = 0.25         # the speech bubble,
COMMENT_DIM_ICON_COLOR = "#ffffff"        # in white
COMMENT_DIM_ADD_COLOR = "#565656"         # the + art; Houdini's menu triangle keeps its colour

ONLINE_ICON_COLOR = "#598c76"    # ▸ the toolbar's Online button while the online world is open
ABOUT_REPO = {"row": 55, "mark": {"x": 6, "y": 15, "w": 26, "h": 25}, "gap": 10, "text": "#979797"}    # ▸ P06: GitHub's mark, its address
TOOLBAR_ON = {"fill": "#393939", "border": "#a3abc5", "ring": "#364269"}    # ▸ B01c: a button on or open
TOOLBAR_SEARCH_END_GAP = 6    # the least space between the Search box and the right-end buttons, narrow
TOOLBAR_FIELD_TEXT = 20    # the Search box's text inset, past its magnifier; an empty box shows none of it
INFO_ICON_COLOR = "#b69c51"      # ▸ the info pane (N02): its header icon, and its toolbar button while open
INFO_ICON_ART_COLOR = "#5d7abd"  # the colour icon_info.svg is drawn in; INFO_ICON_COLOR replaces it
INFO_HIDE_PREVIEW = "Hide Preview"    # the header button's tooltip while the picture is shown
INFO_SHOW_PREVIEW = "Show Preview"    # and while it is hidden
INFO_PREVIEW_LEAST = 38             # px: the lowest the drag line takes the picture area, two rows
DRAG_LINE_COLOR = "#202020"         # the line under the picture; dragging it sets the picture area's height
DRAG_LINE_GRAB = 3                  # px above and below the line that also take the drag
INFO_DIVIDER_WEIGHT = 2             # px: the stroke of N02's divider line, which its node box omits


TILE_TEXT = "#cdc8bc"           # ▸ the tile and list delegates
TILE_SUBTITLE = "#5d7abd"       # the sidebar's drag highlight until the panel applies the accent
CODE_TEXT_OPACITY = 0.5         # T05B: a code tile's text at half strength, under its run button
TILE_GROUND = "#1b1b1b"             # T01's tile card, and under every generic icon (T05-T13)
GRID_BACK = "#272726"               # the QML grid headless; with an interface, Houdini's own
BADGE_REST_OPACITY = 0.75       # every button badge's icon at rest; the backdrop stays as drawn
BADGE_HOVER_OPACITY = 1.0       # and the icon under the pointer
BADGE_LEAST = 12                # px: a corner badge is never smaller, at any tile size
BADGE_PART = 4                  # a corner badge grows to this part of the picture's side, to its drawn size
RENDERER_ICON_BLEED = 4         # px painted around a renderer icon's own box, for its shadow
TILE_SIZES = (64, 128, 192, 256, 320, 384, 448, 512)    # the slider's steps; a tile below 64 is smaller than its badges
LIST_TILE_SIZE = 16             # list mode's one size; `thumbsize_list` is still written, never read
MENU_ICON = 16                  # ▸ C13: a menu entry's icon box, the size Houdini draws it ▸r/menu-checked-look
LIST_TEXT_COLOR = "#d8d6d4"            # a table is read down its columns, so every column is drawn in this except Category
LIST_SELECTED_TEXT = "#000000"  # every column of a selected row

SLIDER_LEFT = "#5d7abd"         # ▸ the slider, tabs and icon-menu button; the default accent
SLIDER_HANDLE = "#777f95"
SLIDER_TRACK = "#1a1a1a"        # the progress track's OWN colour, never the slider's, so one tweak cannot recolour both
MENU_IDLE_BODY = "#5d7abd"
MENU_HOVER_BODY = "#cccdcd"
MENU_IDLE_TRIANGLE = "#7f807f"
MENU_HOVER_TRIANGLE = "#a5b3d4"
MENU_CUTOUT = "#2d2d2d"
MENU_OPEN_CUTOUT = "#2d4075"
MENU_HOVER_CUTOUT = "#424142"
MENU_CHIP_FILL = "#2d4075"
MENU_CHIP_BORDER = "#1e2c50"
MENU_CHIP_RING = "#707ca3"
MENU_HOVER_CHIP_FILL = "#424142"
MENU_HOVER_CHIP_RING = "#555455"
MENU_TEXT = "#e6e6e6"


SIDEBAR_PICKER_START = "#4af2a1"    # the colour picker's starting colour for a row that has none

BTN_APPLY = "Apply"                 # ▸ THE WORDS, from here down. Buttons first
BTN_CANCEL = "Cancel"
BTN_ACCEPT = "Accept"               # commits and CLOSES; Apply commits and stays open - Houdini's own pair (ref ▸ windows/optype)
LABEL_CUSTOM_COLOR = "Custom Color"      # a LABEL since the 2026-08-27 overhaul: the chip beside it is the button
BTN_CLEAR_SEARCH = "Clear Search"
BTN_SHOW_ALL = "Show All"
BTN_LOCATE = "Locate"
BTN_REMOVE_FROM_LIST = "Remove from List"
BTN_SELECT = "Select"

LABEL_TAGS = "Tags"                 # ▸ field labels and placeholders
LABEL_CATEGORY = "Category"
LABEL_ICON = "Image"                # the D02 menu choosing the tile's face
FACE_LABELS = ("Image", "Generic Icon", "Custom Icon")    # its items, in `tile_icons.FACES` order
LABEL_LIGHT_ICON = "Light Icons"    # the D02 toggle that replaced the Lines dropdown: OFF = dark lines, ON = light
LABEL_NAME = "Name"
PLACEHOLDER_SEARCH_ICONS = "Search"     # D02 drew the count in it; it does not any more
LABEL_NOT_CONNECTED = "not connected"    # D15: a listed library whose folder cannot be reached
LABEL_LIBRARY_FORMAT = "Current Library Format: %s"    # ▸ P01, beside Check
LABEL_UPGRADES_LIBRARY ="Apply/Accept will upgrade your library to v%s"   # beside Apply
LABEL_LIBRARY_TOO_NEW = "You need to update Amaze to use this library"
LABEL_LIBRARY_UNREACHABLE = "Amaze cannot reach this library"
BTN_CHECK = "Check"                 # the row's button, until a check finds what can be fixed
BTN_REPAIR = "Repair"
BTN_FIX = "Fix"                     # when the light fixes alone put right what the check found

TITLE_TILE_ICON = "Tile Icon"    # what D02 shows when the selection has no ONE name to show
TITLE_MANAGE_LIBRARIES = "Manage Libraries"
BAND_UNTITLED = "Untitled"       # what D11's band shows for a snippet that has no name yet
MENU_NEW_VERSION = "New Version"    # D11's + menu, above the snippet's versions

EMPTY_SHARED = {    # ▸ E06 E08 E09, the empty states every section shares, read by `EmptyState.words`
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

DIALOG_LAYOUT = {    # ▸ every drawn figure: (kind, x, y, w, h, text) per node, per frame ▸p/one-design-document
    "D01": {   # Versions: a material's versions, newest first
        "frame": (269, 344),
        "nodes": (
            ("QListWidget", 8, 12, 253, 286, None),
            ("QListWidget ▸ row ▸ 2", 8, 31, 253, 19, None),
            ("QListWidget ▸ row ▸ 4", 8, 69, 253, 19, None),
            ("QListWidget ▸ row ▸ 6", 8, 107, 253, 19, None),
            ("QListWidget ▸ row ▸ 8", 8, 145, 253, 19, None),
            ("QListWidget ▸ row ▸ 10", 8, 183, 253, 19, None),
            ("QListWidget ▸ row ▸ 12", 8, 221, 253, 19, None),
            ("QListWidget ▸ row ▸ 14", 8, 259, 253, 19, None),
            ("QListWidget ▸ row ▸ 16", 8, 297, 253, 19, None),
            ("QListWidget ▸ item ▸ selected", 8, 31, 253, 19, None),
            ("QPushButton", 130, 311, 60, 21, None),
            ("QPushButton", 196, 311, 65, 21, None),
            ("QListWidget ▸ item", 19, 14, 90, 15, "Version 2 with red "),
            ("QListWidget ▸ item ▸ path", 194, 14, 56, 15, "2026-10-23"),
            ("QListWidget ▸ item ▸ path", 194, 33, 56, 15, "2026-10-22"),
            ("QListWidget ▸ item ▸ path", 194, 52, 56, 15, "2026-10-22"),
            ("QListWidget ▸ item", 19, 33, 168, 15, "Johns version more saturated w..."),
            ("QListWidget ▸ item", 19, 52, 116, 15, "Look Development test"),
            ("QPushButton ▸ text", 211, 314, 34, 15, "Cancel"),
            ("QPushButton ▸ text", 145, 314, 31, 15, "Select"),
        ),
    },
    "QML D01": {   # the QML Versions window: Select, Delete and Cancel under the list
        "frame": (269, 344),
        "nodes": (
            ("QListWidget", 8, 12, 253, 286, None),
            ("QListWidget ▸ row ▸ 2", 8, 31, 253, 19, None),
            ("QListWidget ▸ row ▸ 4", 8, 69, 253, 19, None),
            ("QListWidget ▸ row ▸ 6", 8, 107, 253, 19, None),
            ("QListWidget ▸ row ▸ 8", 8, 145, 253, 19, None),
            ("QListWidget ▸ row ▸ 10", 8, 183, 253, 19, None),
            ("QListWidget ▸ row ▸ 12", 8, 221, 253, 19, None),
            ("QListWidget ▸ row ▸ 14", 8, 259, 253, 19, None),
            ("QListWidget ▸ row ▸ 16", 8, 297, 253, 19, None),
            ("QListWidget ▸ item ▸ selected", 8, 31, 253, 19, None),
            ("QPushButton", 130, 311, 60, 21, None),
            ("QPushButton", 64, 311, 60, 21, None),
            ("QPushButton", 196, 311, 65, 21, None),
            ("QListWidget ▸ item", 19, 14, 90, 15, "Version 2 with red "),
            ("QListWidget ▸ item ▸ path", 194, 14, 56, 15, "2026-10-23"),
            ("QListWidget ▸ item ▸ path", 194, 33, 56, 15, "2026-10-22"),
            ("QListWidget ▸ item ▸ path", 194, 52, 56, 15, "2026-10-22"),
            ("QListWidget ▸ item", 19, 33, 168, 15, "Johns version more saturated w..."),
            ("QListWidget ▸ item", 19, 52, 116, 15, "Look Development test"),
            ("QPushButton ▸ text", 144, 314, 33, 15, "Delete"),
            ("QPushButton ▸ text", 211, 314, 34, 15, "Cancel"),
            ("QPushButton ▸ text", 79, 314, 31, 15, "Select"),
        ),
    },
    "D02": {   # Customize (Tile Icon)
        "frame": (335, 586),
        "nodes": (
            ("QLineEdit", 71, 12, 256, 22, None),
            ("QLabel", 33, 16, 30, 15, "Name"),
            ("QLineEdit ▸ text", 76, 16, 72, 15, "brushed_steel"),
            ("QComboBox", 71, 43, 255, 22, None),
            ("QLabel", 18, 47, 45, 15, "Category"),
            ("QLineEdit", 71, 74, 255, 22, None),
            ("QLabel", 40, 77, 23, 15, "Tags"),
            ("QLabel", 8, 107, 150, 150, None),
            ("QLabel", 171, 109, 31, 15, "Image"),
            ("QComboBox", 208, 105, 118, 22, None),
            ("QLabel", 202, 165, 55, 15, "Light Icons"),
            ("ToggleSwitch", 171, 165, 23, 15, None),
            ("QToolButton", 171, 190, 35, 28, None),
            ("QLabel", 212, 196, 68, 15, "Custom Color"),
            ("QToolButton", 171, 228, 35, 28, None),
            ("QToolButton", 212, 228, 34, 28, None),
            ("QToolButton", 252, 228, 35, 28, None),
            ("QToolButton", 293, 228, 34, 28, None),
            ("QLineEdit", 8, 266, 319, 22, None),
            ("QLineEdit ▸ text", 14, 270, 35, 15, "Search"),
            ("icon grid ▸ 287 cells (collapsed)", 8, 294, 319, 250, None),
            ("QScrollBar", 311, 299, 16, 240, None),
            ("icon grid ▸ note", 16, 381, 136, 11, "287 icon cells, 34×34 — scrolls"),
            ("QPushButton", 184, 552, 65, 22, None),
            ("QPushButton", 255, 552, 72, 22, None),
            ("QPushButton ▸ text", 202, 555, 29, 15, "Apply"),
            ("QPushButton ▸ text", 274, 555, 34, 15, "Accept"),
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
            ("QComboBox", 148, 42, 199, 22, None),
            ("QPushButton", 353, 42, 58, 22, None),
            ("QPushButton", 417, 42, 56, 22, None),
            ("QLabel", 104, 46, 36, 15, "Library"),
            ("QComboBox ▸ text", 153, 46, 99, 15, "Library folder name"),
            ("QPushButton ▸ text", 362, 46, 40, 15, "Manage"),
            ("QPushButton ▸ text", 435, 46, 20, 15, "Add"),
            ("QPushButton", 148, 70, 48, 22, None),
            ("QPushButton ▸ text", 155, 74, 35, 15, "Reload"),
            ("QPushButton", 202, 70, 76, 22, None),
            ("QPushButton ▸ text", 209, 74, 63, 15, "Show Folder"),
            ("QLabel", 20, 74, 120, 15, "Format: v1"),
            ("QLabel", 83, 102, 31, 15, "Errors"),
            ("QLabel", 130, 102, 23, 15, "Files"),
            ("QLabel", 170, 102, 17, 15, "Ref"),
            ("QLabel", 25, 124, 52, 15, "Databases"),
            ("CheckLight", 94, 127, 9, 9, None),
            ("QLabel", 108, 124, 6, 15, "0"),
            ("CheckLight", 132, 127, 9, 9, None),
            ("QLabel", 147, 124, 6, 15, "8"),
            ("CheckLight", 171, 127, 9, 9, None),
            ("QLabel", 186, 124, 4, 15, "-"),
            ("QLabel", 207, 124, 172, 15, "Info box maximum info you can ss"),
            ("QPushButton", 398, 121, 75, 22, None),
            ("QPushButton ▸ text", 422, 124, 31, 15, "Check"),
            ("QWidget ▸ group divider", 20, 155, 450, 1, None),
            ("QComboBox", 148, 168, 196, 22, None),
            ("QPushButton", 352, 168, 56, 22, None),
            ("QPushButton", 414, 168, 56, 22, None),
            ("QLabel", 117, 172, 23, 15, "User"),
            ("QComboBox ▸ text", 153, 172, 27, 15, "Plum"),
            ("QPushButton ▸ text", 360, 172, 42, 15, "Rename"),
            ("QPushButton ▸ text", 422, 172, 33, 15, "Delete"),
            ("QWidget ▸ group divider", 21, 202, 450, 1, None),
            ("QLineEdit", 148, 215, 180, 22, None),
            ("QPushButton", 336, 215, 28, 22, None),
            ("QPushButton", 366, 215, 52, 22, None),
            ("QPushButton", 424, 215, 46, 22, None),
            ("QLabel", 83, 219, 57, 15, "Cache Path"),
            ("QLineEdit ▸ text", 153, 219, 35, 15, "<path>"),
            ("QPushButton ▸ text", 346, 219, 9, 15, "..."),
            ("QPushButton ▸ text", 374, 219, 37, 15, "Default"),
            ("QPushButton ▸ text", 432, 219, 33, 15, "Delete"),
            ("QWidget ▸ group divider", 20, 249, 450, 1, None),
            ("ToggleSwitch", 148, 262, 23, 15, None),
            ("ToggleSwitch ▸ text", 179, 262, 43, 15, "Versions"),
            ("QLabel", 20, 415, 301, 15, "Apply/Accept will upgrade your library to v3"),
            ("QPushButton", 327, 412, 65, 22, None),
            ("QPushButton", 398, 412, 72, 22, None),
            ("QPushButton ▸ text", 345, 415, 29, 15, "Apply"),
            ("QPushButton ▸ text", 417, 415, 34, 15, "Accept"),
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
            ("ToggleSwitch", 148, 119, 23, 15, None),
            ("ToggleSwitch ▸ text", 179, 119, 83, 15, "Render RAT Files"),
            ("ToggleSwitch", 148, 144, 23, 15, None),
            ("ToggleSwitch ▸ text", 179, 144, 86, 15, "System File Icons"),
            ("QComboBox", 148, 167, 105, 22, None),
            ("QLabel", 69, 171, 71, 15, "Write Paths As"),
            ("QComboBox ▸ text", 153, 171, 37, 15, "$HOME"),
            ("QComboBox", 148, 195, 145, 22, None),
            ("QLabel", 74, 199, 66, 15, "Tile Icon Line"),
            ("QComboBox ▸ text", 153, 199, 23, 15, "Thin"),
            ("QSpinBox", 148, 223, 64, 24, None),
            ("QLineEdit", 149, 224, 62, 22, None),
            ("ClickSlider", 220, 224, 250, 22, None),
            ("QLabel", 57, 228, 83, 15, "Scroll Speed (%)"),
            ("QSpinBox ▸ text", 153, 228, 12, 15, "75"),
            ("QLineEdit ▸ text", 154, 228, 12, 15, "75"),
        ),
    },
    "P05": {   # Preferences - Add-On: drawn 885 tall in FIGMA ONLY
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
            ("QTextBrowser", 20, 38, 446, 801, None),
            ("QScrollBar", 466, 38, 16, 801, None),    # right of the list, not over it
            ("add-on picture", 20, 38, 54, 54, None),
            ("ToggleSwitch", 118, 57, 23, 15, None),
            ("ToggleSwitch ▸ text", 149, 57, 79, 15, None),
            ("add-on version", 20, 94, 63, 15, None),
            ("add-on author", 20, 109, 87, 15, None),
            ("add-on short description", 280, 38, 165, 94, None),
            ("QWidget ▸ group divider", 20, 139, 434, 1, None),
            ("add-on picture", 20, 147, 54, 54, None),
            ("ToggleSwitch", 118, 167, 23, 15, None),
            ("ToggleSwitch ▸ text", 149, 167, 103, 15, None),
            ("add-on version", 20, 203, 63, 15, None),
            ("add-on author", 20, 218, 87, 15, None),
            ("add-on short description", 280, 147, 165, 86, None),
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
            ("QPushButton", 362, 295, 108, 22, None),
            ("QPushButton ▸ text", 374, 299, 84, 15, "Convert pre-1.40"),
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
            ("ToggleSwitch ▸ text", 179, 374, 107, 15, "Add-On beta versions"),
        ),
    },
    "D09": {   # Save to Amaze - the Section row picks the section saved to
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
            ("icon ▸ close ▸ icon_tab_close.svg", 106, 0, 22, 22, None),
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
        "frame": (420, 227),
        "nodes": (
            ("QListWidget", 8, 12, 404, 171, None),
            ("QListWidget ▸ row ▸ 2", 8, 31, 404, 19, None),
            ("QListWidget ▸ row ▸ 4", 8, 69, 404, 19, None),
            ("QListWidget ▸ row ▸ 6", 8, 107, 404, 19, None),
            ("QListWidget ▸ row ▸ 8", 8, 145, 404, 19, None),
            ("QListWidget ▸ item ▸ selected", 8, 31, 404, 19, None),
            ("QListWidget ▸ item", 19, 14, 71, 15, "Studio Library"),
            ("QListWidget ▸ item ▸ path", 130, 14, 158, 15, "/Volumes/Server/Amaze/Studio"),
            ("QListWidget ▸ item", 19, 33, 69, 15, "Client Archive"),
            ("QListWidget ▸ item ▸ path", 130, 33, 170, 15, "/Volumes/Projects/Archive/Amaze"),
            ("QListWidget ▸ item", 19, 52, 95, 15, "Look Development"),
            ("QListWidget ▸ item ▸ path", 130, 52, 91, 15, "~/Amaze/LookDev"),
            ("QListWidget ▸ item", 19, 71, 56, 15, "Old Library"),
            ("QListWidget ▸ item ▸ path", 130, 71, 148, 15, "/Volumes/Backup/Amaze/Old"),
            ("QListWidget ▸ item ▸ not connected", 327, 71, 72, 15, "not connected"),
            ("QPushButton", 237, 193, 104, 22, None),
            ("QPushButton", 347, 193, 65, 22, None),
            ("QPushButton ▸ text", 363, 196, 34, 15, "Cancel"),
            ("QPushButton ▸ text", 245, 197, 88, 15, "Remove from List"),
        ),
    },
    "T01": {   # the grid tile, drawn at TILE_DRAWN_SIZE - its spacing is what the delegate paints
        "frame": (138, 177),
        "nodes": (
            ("tile card", 4, 4, 130, 173, None),
            ("thumbnail", 4, 4, 130, 130, None),
            ("tile name", 9, 139, 74, 15, "brushed_steel"),
            ("tile subtitle", 9, 157, 49, 15, "MaterialX"),
        ),
    },
    "T08": {   # a scene file's tile on its default face
        "frame": (138, 177),
        "nodes": (
            ("tile card", 4, 4, 130, 173, None),
            ("thumbnail", 4, 4, 130, 130, None),
            ("face ▸ icon_hip.svg", 4, 4, 130, 130, None),
            ("tile name", 9, 139, 47, 15, "shot_010"),
            ("tile subtitle", 9, 157, 18, 15, "HIP"),
        ),
    },
    "T05": {   # the code tile on its generic face
        "frame": (138, 177),
        "nodes": (
            ("tile card", 4, 4, 130, 173, None),
            ("thumbnail", 4, 4, 130, 130, None),
            ("face ▸ face_code.svg", 4, 4, 130, 130, None),
            ("tile name", 9, 139, 52, 15, "Mtxl to RS"),
            ("tile subtitle", 9, 157, 37, 15, "Python"),
        ),
    },
    "T20": {   # the button badges at rest, each in its corner: favourite, comment, versions, Run
        "frame": (138, 177),
        "nodes": (
            ("tile card", 4, 4, 130, 173, None),
            ("thumbnail", 4, 4, 130, 130, None),
            ("tile name", 9, 139, 38, 15, "Badges"),
            ("tile subtitle", 9, 157, 20, 15, "rest"),
            ("badge favourite (top-right) ▸ badge_favourite_off", 110, 6, 22, 22, None),
            ("badge comment (lower-right) ▸ badge_comment", 6, 6, 22, 22, None),
            ("badge versions (lower-left) ▸ badge_versions", 6, 110, 22, 22, None),
            ("badge execute (lower-right) ▸ badge_execute", 110, 110, 22, 22, None),
            ("category strip (example colour)", 4, 134, 130, 4, None),
        ),
    },
    "T23": {   # the badges that show a state: a favourite, a comment, the open scene
        "frame": (138, 177),
        "nodes": (
            ("tile card", 4, 4, 130, 173, None),
            ("thumbnail", 4, 4, 130, 130, None),
            ("tile name", 9, 139, 38, 15, "Badges"),
            ("tile subtitle", 9, 157, 14, 15, "on"),
            ("badge favourite (top-right) ▸ badge_favourite", 110, 6, 22, 22, None),
            ("badge comment (lower-right) ▸ badge_comment", 6, 6, 22, 22, None),
            ("badge open (top-left) ▸ badge_open", 110, 110, 22, 22, None),
        ),
    },
    "T24": {   # a material's renderer icon, at the right end of the subtitle's line
        "frame": (138, 177),
        "nodes": (
            ("tile card", 4, 4, 130, 173, None),
            ("thumbnail", 4, 4, 130, 130, None),
            ("tile name", 9, 139, 120, 15, "Badges, long name te..."),
            ("tile subtitle", 9, 157, 49, 15, "MaterialX"),
            ("renderer icon ▸ renderer_materialx", 107, 157, 23, 13, None),
        ),
    },
    "T25": {   # the Redshift icon: its own size and place on the subtitle's line
        "frame": (138, 177),
        "nodes": (
            ("tile card", 4, 4, 130, 173, None),
            ("thumbnail", 4, 4, 130, 130, None),
            ("tile name", 9, 139, 120, 15, "Badges, long name te..."),
            ("tile subtitle", 9, 157, 43, 15, "Redshift"),
            ("renderer icon ▸ renderer_redshift", 112, 155, 16, 18, None),
        ),
    },
    "T26": {   # the Octane icon
        "frame": (138, 177),
        "nodes": (
            ("tile card", 4, 4, 130, 173, None),
            ("thumbnail", 4, 4, 130, 130, None),
            ("tile name", 9, 139, 120, 15, "Badges, long name te..."),
            ("tile subtitle", 9, 157, 37, 15, "Octane"),
            ("renderer icon ▸ renderer_octane", 112, 156, 16, 16, None),
        ),
    },
    "QML T08": {   # the QML tile's frames from here; T01-T26 above go with the old panel. A scene, open
        "frame": (138, 177),
        "nodes": (
            ("tile card", 4, 4, 130, 173, None),
            ("CheckCircle", 113, 155, 16, 16, None),
            ("thumbnail", 4, 4, 130, 130, None),
            ("face ▸ icon_hip.svg", 4, 4, 130, 130, None),
            ("tile name", 9, 139, 47, 15, "shot_010"),
            ("tile subtitle", 9, 157, 18, 15, "HIP"),
        ),
    },
    "QML T08b": {   # the same tile, the scene not open: the check circle in dark grey
        "frame": (138, 177),
        "nodes": (
            ("tile card", 4, 4, 130, 173, None),
            ("CheckCircle", 113, 155, 16, 16, None),
            ("thumbnail", 4, 4, 130, 130, None),
            ("face ▸ icon_hip.svg", 4, 4, 130, 130, None),
            ("tile name", 9, 139, 47, 15, "shot_010"),
            ("tile subtitle", 9, 157, 18, 15, "HIP"),
        ),
    },
    "QML T05": {   # a Python snippet at rest: the running mark in dark grey (layer named CheckCircle)
        "frame": (138, 177),
        "nodes": (
            ("tile card", 4, 4, 130, 173, None),
            ("thumbnail", 4, 4, 130, 130, None),
            ("face ▸ face_code.svg", 4, 4, 130, 130, None),
            ("tile name", 9, 139, 52, 15, "Mtxl to RS"),
            ("tile subtitle", 9, 157, 37, 15, "Python"),
            ("CheckCircle", 113, 155, 16, 16, None),
        ),
    },
    "QML T05B": {   # the same snippet while it runs: the running mark in green, the code under the pointer
        "frame": (138, 177),
        "nodes": (
            ("tile card", 4, 4, 130, 173, None),
            ("thumbnail", 4, 4, 130, 130, None),
            ("bg", 4, 4, 130, 130, None),
            ("tile name", 9, 139, 52, 15, "Mtxl to RS"),
            ("tile subtitle", 9, 157, 37, 15, "Python"),
            ("code preview ▸ Amaze's painter, text at 50%", 4, 4, 130, 130, None),
            ("CheckCircle", 113, 155, 16, 16, None),
        ),
    },
    "QML T20": {   # the buttons on the picture at rest: Favorite in its corner, Run in the middle
        "frame": (138, 177),
        "nodes": (
            ("tile card", 4, 4, 130, 173, None),
            ("thumbnail", 4, 4, 130, 130, None),
            ("badge favourite (top-right) ▸ badge_favourite", 95, 4, 39, 36, None),
            ("tile name", 9, 139, 38, 15, "Badges"),
            ("tile subtitle", 9, 157, 20, 15, "rest"),
            ("badge execute (lower-right) ▸ badge_execute", 43, 42, 52, 52, None),
            ("category strip (example colour)", 4, 134, 130, 4, None),
            ("CheckCircle", 113, 155, 16, 16, None),
        ),
    },
    "QML T23": {   # a favourite, and the comment mark left of the renderer icon
        "frame": (138, 177),
        "nodes": (
            ("tile card", 4, 4, 130, 173, None),
            ("thumbnail", 4, 4, 130, 130, None),
            ("tile name", 9, 139, 38, 15, "Badges"),
            ("tile subtitle", 9, 157, 14, 15, "on"),
            ("icon ▸ filter_materialx.svg", 109, 159, 19, 13, None),
            ("message-circle", 90, 160, 11, 11, None),
            ("badge favourite (top-right) ▸ badge_favourite", 95, 4, 39, 36, None),
        ),
    },
    "QML T24": {   # the MaterialX icon at the subtitle's right end
        "frame": (138, 177),
        "nodes": (
            ("tile card", 4, 4, 130, 173, None),
            ("thumbnail", 4, 4, 130, 130, None),
            ("tile name", 9, 139, 120, 15, "Badges, long name te..."),
            ("tile subtitle", 9, 157, 49, 15, "MaterialX"),
            ("icon ▸ filter_materialx.svg", 109, 159, 19, 13, None),
        ),
    },
    "QML T25": {   # the Redshift icon
        "frame": (138, 177),
        "nodes": (
            ("tile card", 4, 4, 130, 173, None),
            ("thumbnail", 4, 4, 130, 130, None),
            ("tile name", 9, 139, 120, 15, "Badges, long name te..."),
            ("tile subtitle", 9, 157, 43, 15, "Redshift"),
            ("icon ▸ filter_redshift.svg", 113, 155, 15, 17, None),
        ),
    },
    "QML T26": {   # the Octane icon
        "frame": (138, 177),
        "nodes": (
            ("tile card", 4, 4, 130, 173, None),
            ("thumbnail", 4, 4, 130, 130, None),
            ("tile name", 9, 139, 120, 15, "Badges, long name te..."),
            ("tile subtitle", 9, 157, 37, 15, "Octane"),
            ("renderer icon ▸ renderer_octane", 112, 156, 16, 16, None),
        ),
    },
    "L01": {   # the list table from the live panel - its header, widths and ticks are read
        "frame": (1542, 96),
        "nodes": (
            ("column ▸ name", 0, 0, 176, 20, None),
            ("divider ▸ name", 175, 0, 2, 20, None),
            ("heading ▸ name", 5, 2.5, 30, 15, "Name"),
            ("sort arrow ▸ name (Qt's own, traced)", 155, 2, 16, 16, None),
            ("column ▸ type", 176, 0, 59, 20, None),
            ("divider ▸ type", 234, 0, 2, 20, None),
            ("heading ▸ type", 181, 2.5, 25, 15, "Type"),
            ("column ▸ category", 235, 0, 76, 20, None),
            ("divider ▸ category", 310, 0, 2, 20, None),
            ("heading ▸ category", 240, 2.5, 45, 15, "Category"),
            ("column ▸ favorite", 311, 0, 69, 20, None),
            ("divider ▸ favorite", 379, 0, 2, 20, None),
            ("heading ▸ favorite", 316, 2.5, 41, 15, "Favorite"),
            ("column ▸ version", 380, 0, 66, 20, None),
            ("divider ▸ version", 445, 0, 2, 20, None),
            ("heading ▸ version", 385, 2.5, 38, 15, "Version"),
            ("column ▸ open", 446, 0, 54, 20, None),
            ("divider ▸ open", 499, 0, 2, 20, None),
            ("heading ▸ open", 451, 2.5, 28, 15, "Open"),
            ("column ▸ comments", 500, 0, 85, 20, None),
            ("divider ▸ comments", 584, 0, 2, 20, None),
            ("heading ▸ comments", 505, 2.5, 55, 15, "Comments"),
            ("column ▸ tags", 585, 0, 300, 20, None),
            ("divider ▸ tags", 884, 0, 2, 20, None),
            ("heading ▸ tags", 590, 2.5, 23, 15, "Tags"),
            ("column ▸ license", 885, 0, 287, 20, None),
            ("divider ▸ license", 1171, 0, 2, 20, None),
            ("heading ▸ license", 890, 2.5, 38, 15, "License"),
            ("column ▸ date", 1172, 0, 130, 20, None),
            ("divider ▸ date", 1301, 0, 2, 20, None),
            ("heading ▸ date", 1177, 2.5, 24, 15, "Date"),
            ("column ▸ id", 1302, 0, 240, 20, None),
            ("divider ▸ id", 1541, 0, 2, 20, None),
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
    "B01": {   # the toolbar, the QML frame (list mode, at rest) - its height, edges, gaps and sizes are read
        "frame": (840, 30),
        "nodes": (
            ("bottom border", 0, 29, 840, 1, None),
            ("button ▸ btn_categories", 2, 3, 24, 24, None),
            ("button ▸ btn_menu_view", 28, 3, 24, 24, None),
            ("button ▸ btn_menu_filter", 54, 3, 24, 24, None),
            ("button ▸ btn_online", 80, 3, 24, 24, None),
            ("button ▸ btn_info", 106, 3, 24, 24, None),
            ("button ▸ btn_notes", 132, 3, 24, 24, None),
            ("button ▸ cb_favsonly", 158, 3, 24, 24, None),
            ("buttons list-grid ▸ cb_viewmode", 184, 3, 50, 24, None),    # Houdini's button strip
            ("segment 1 ▸ cb_viewmode", 184, 3, 24, 24, None),
            ("segment 3 ▸ cb_viewmode", 210, 3, 24, 24, None),
            ("slider ▸ click_slider (disabled)", 249, 3, 200, 23, None),
            ("groove ▸ click_slider", 249, 13, 200, 3, None),
            ("handle ▸ click_slider", 249, 9, 11, 11, None),
            ("snap mark ▸ click_slider", 280, 13, 3, 3, None),    # one at every inner step, 27 apart
            ("snap mark ▸ click_slider", 307, 13, 3, 3, None),
            ("snap mark ▸ click_slider", 334, 13, 3, 3, None),
            ("snap mark ▸ click_slider", 361, 13, 3, 3, None),
            ("snap mark ▸ click_slider", 388, 13, 3, 3, None),
            ("snap mark ▸ click_slider", 415, 13, 3, 3, None),
            ("label ▸ filter_label", 469, 0, 40, 30, None),
            ("text ▸ filter_label", 471, 7, 35, 15, "Search"),
            ("field ▸ line_filter", 521, 5, 200, 20, None),
            ("button ▸ btn_prefs", 814, 3, 24, 24, None),
            ("icon ▸ btn_categories ▸ icon_categories.svg", 6, 7, 16, 16, None),
            ("icon ▸ btn_menu_view ▸ icon_renderer.svg", 31, 6, 18, 18, None),
            ("icon ▸ btn_menu_filter ▸ icon_view.svg", 57, 6, 18, 18, None),
            ("icon ▸ btn_online ▸ icon_online.svg", 84, 7, 16, 16, None),
            ("icon ▸ btn_info ▸ icon_info.svg", 109, 6, 18, 18, None),
            ("icon ▸ btn_notes ▸ icon_comments.svg", 135, 6, 18, 18, None),
            ("icon ▸ cb_favsonly ▸ favourite_on.svg", 162.5, 7, 15, 15, None),
            ("icon ▸ cb_viewmode ▸ list.svg", 188, 7, 16, 16, None),
            ("icon ▸ cb_viewmode ▸ grid.svg", 214, 7, 16, 16, None),
            ("icon ▸ line_filter ▸ icon_search.svg", 525, 8, 13, 13, None),
            ("icon ▸ btn_prefs ▸ icon_library.svg", 817, 6, 18, 18, None),
        ),
    },
    "S01": {   # the section tab strip - its height and tab icons are read
        "frame": (840, 29),
        "nodes": (
            ("tray", 3, 5, 305, 23, None),
            ("chip ▸ material", 6, 8, 72, 17, None),
            ("chip ▸ gradient", 78, 8, 61, 17, None),
            ("chip ▸ cop", 139, 8, 60, 17, None),
            ("chip ▸ code", 199, 8, 59, 17, None),
            ("chip ▸ file", 258, 8, 47, 17, None),
            ("text box ▸ material", 29, 9, 41, 15, None),
            ("text box ▸ gradient", 103, 9, 28, 15, None),
            ("text box ▸ cop", 164, 9, 27, 15, None),
            ("text box ▸ code", 224, 9, 26, 15, None),
            ("text box ▸ file", 279, 9, 18, 15, None),
            ("Line 3", 0, 28.5, 840, 0, None),
            ("label ▸ file", 279, 9, 18, 15, "File"),
            ("icon ▸ file ▸ tab_file.svg", 266, 10, 10, 12, None),
            ("label ▸ material", 29, 9, 41, 15, "Material"),
            ("icon ▸ material ▸ tab_material.svg", 14, 10, 13, 13, None),
            ("label ▸ code", 224, 9, 26, 15, "Code"),
            ("icon ▸ code ▸ tab_code.svg", 207, 10, 15, 13, None),
            ("label ▸ gradient", 103, 9, 28, 15, "Color"),
            ("icon ▸ gradient ▸ tab_color.svg", 86, 10, 15, 13, None),
            ("label ▸ cop", 164, 9, 27, 15, "Node"),
            ("icon ▸ cop ▸ tab_cop.svg", 147, 10, 15, 13, None),
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
    "N01B": {   # the same pane with nothing selected - its labels and icons dim, nothing moves
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
    "N02": {   # the info pane over an image file: header, preview, rows, columns and divider
        "frame": (450, 621),
        "nodes": (
            ("header", 0, 0, 450, 30, None),
            ("icon ▸ preview ▸ icon_preview_hide.svg", 427, 7, 15, 15, None),
            ("body", 0, 330, 450, 291, None),
            ("row ▸ 2", 0, 349, 450, 19, None),
            ("row ▸ 4", 0, 387, 450, 19, None),
            ("row ▸ 6", 0, 425, 450, 19, None),
            ("row ▸ 8", 0, 463, 450, 19, None),
            ("row ▸ 10", 0, 501, 450, 19, None),
            ("row ▸ 12", 0, 539, 450, 19, None),
            ("row ▸ 14", 0, 577, 450, 19, None),
            ("row ▸ 16", 0, 615, 450, 19, None),
            ("text ▸ name", 36, 7, 37, 15, "Flower"),
            ("text ▸ type", 79, 7, 20, 15, "JPG"),
            ("label ▸ 1", 12, 332, 30, 15, "Name"),
            ("value ▸ 1", 109, 332, 112, 15, "Name of selected item"),
            ("label ▸ 2", 12, 351, 40, 15, "Created"),
            ("value ▸ 2", 109, 351, 56, 15, "2021-08-10"),
            ("label ▸ 3", 12, 370, 44, 15, "Modified"),
            ("value ▸ 3", 109, 370, 56, 15, "2024-03-02"),
            ("label ▸ 4", 12, 389, 21, 15, "Size"),
            ("label ▸ 5", 12, 408, 37, 15, "Format"),
            ("label ▸ 6", 12, 427, 59, 15, "Dimensions"),
            ("label ▸ 7", 12, 446, 60, 15, "Color Space"),
            ("value ▸ 4", 109, 389, 35, 15, "840 KB"),
            ("value ▸ 5", 109, 408, 20, 15, "EXR"),
            ("value ▸ 6", 109, 427, 58, 15, "2048 x 2048"),
            ("value ▸ 7", 109, 446, 32, 15, "Linear"),
            ("icon ▸ header ▸ icon_info.svg", 10, 5, 20, 20, None),
            ("divider", 100, 330, 0, 291, None),
            ("label ▸ 8", 12, 465, 47, 15, "Bit Depth"),
            ("value ▸ 8", 109, 465, 54, 15, "16 bit float"),
            ("label ▸ 9", 12, 484, 47, 15, "Channels"),
            ("value ▸ 9", 109, 484, 28, 15, "RGBA"),
            ("label ▸ 10", 12, 503, 67, 15, "Compression"),
            ("value ▸ 10", 109, 503, 17, 15, "ZIP"),
            ("label ▸ 11", 12, 522, 48, 15, "MIP Maps"),
            ("value ▸ 11", 109, 522, 17, 15, "Yes"),
            ("label ▸ 12", 12, 541, 33, 15, "Folder"),
            ("value ▸ 12", 109, 541, 160, 15, "/Projects/library/textures/metal"),
            ("preview", 125, 30, 199, 298, None),
            ("line ▸ drag", 0, 328, 450, 2, None),
        ),
    },
}

D01_FRAME =DIALOG_LAYOUT["D01"]["frame"]    # ▸ the frame sizes call sites name, read from the drawing
D02_FORM_WIDTH, D02_FRAME_H = DIALOG_LAYOUT["D02"]["frame"]    # the OPENING size; the grid grows
SAVE_WIDTH = DIALOG_LAYOUT["D09"]["frame"][0]    # D09 and D13 alike, whatever their labels
SAVE_FIELD_WIDTH = next(n[3] for n in DIALOG_LAYOUT["D09"]["nodes"] if n[0] == "QLineEdit")
NAME_FIELD_WIDTH = next(n[3] for n in DIALOG_LAYOUT["D13"]["nodes"] if n[0] == "QLineEdit")
D15_WIDTH = DIALOG_LAYOUT["D15"]["frame"][0]
D11_FORM_WIDTH = DIALOG_LAYOUT["D11"]["frame"][0]    # a FLOOR: D11 resizes around its editor

_NODE_MARK = " ▸ "       # what separates a node's kind from the note after it
_TEXT_SUFFIX = _NODE_MARK + "text"
_DRAWN_BOXES: dict = {}
_DRAWN_REPEATS: dict = {}


def drawn_boxes(frame_key: str) -> dict:
    """A frame's boxes by `(kind, text)` or `(kind, None)`; `{}` if unknown. Shared: never edit it."""
    cached = _DRAWN_BOXES.get(frame_key)
    if cached is not None:
        return cached
    nodes = (DIALOG_LAYOUT.get(frame_key) or {}).get("nodes", ())
    rects: dict = {}
    for kind, x, y, w, h, text in nodes:
        if text is None and _NODE_MARK not in kind:   # PLAIN, so a `QWidget ▸ group divider` or a tab chip is not a box any widget is sized from
            rects.setdefault(kind, []).append((x, y, w, h))
    boxes = {(kind, None): tuple(found) for kind, found in rects.items()}
    for kind, x, y, w, h, text in nodes:
        if text is not None and _NODE_MARK not in kind:   # a drawn QLabel: nothing encloses it, so its own rect is what a widget is sized from
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
            repeats.setdefault((plain, text), []).append(   # the smallest rect around this node
                min(holding, key=lambda box: box[2] * box[3]))
            boxes.setdefault((plain, text), repeats[(plain, text)][0])
    _DRAWN_BOXES[frame_key] = boxes
    _DRAWN_REPEATS[frame_key] = {key: tuple(found)
                                 for key, found in repeats.items()}
    return boxes


def drawn_repeats(frame_key: str, kind: str, text) -> tuple:
    """Every box for `(kind, text)` in drawn order, one per drawing; `drawn_boxes` has the first."""
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
    """Clear the derived-box cache, for tests."""
    _DRAWN_BOXES.clear()
    _DRAWN_REPEATS.clear()


def drawn_name(node) -> list:
    """A node's name as its `▸` parts, each without its `(note)`: kind, owner, art."""
    return [part.split(" (")[0] for part in node[0].split(_NODE_MARK)]


def drawn_nodes(frame_key: str, kind: str, owner=None) -> list:
    """A frame's `kind` nodes in drawn order, or only `owner`'s - the lookup every reader uses."""
    return [n for n in DIALOG_LAYOUT[frame_key]["nodes"]
            if drawn_name(n)[0] == kind and (owner is None or drawn_name(n)[1:2] == [owner])]


def drawn_node(frame_key: str, kind: str, owner=None) -> tuple:
    """The first of `drawn_nodes`."""
    return drawn_nodes(frame_key, kind, owner)[0]


def drawn_by_owner(frame_key: str, kind: str) -> dict:
    """{owner: node} for a frame's `kind` nodes; for an owner drawn twice, the later node."""
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
        "line_gap": sub[2] - (name[2] + name[4]),
        "text_inset": name[1] - thumb[1],
        "bottom_pad": layout["frame"][1] - (sub[2] + sub[4]),
        "thumb": thumb[3],
    }


def drawn_category_strip(frame_key: str = "T20") -> int:
    """The height of the category colour's strip, drawn across the card under the thumbnail."""
    return drawn_node(frame_key, "category strip")[4]


def drawn_renderer_icon(frame_key: str = "T24") -> dict:
    """A material tile's renderer icon: its height, its inset from the card's right edge, its drop."""
    card, sub, icon = (drawn_node(frame_key, kind)
                       for kind in ("tile card", "tile subtitle", "renderer icon"))
    return {
        "height": icon[4],    # each renderer's art gives its own width
        "inset": card[1] + card[3] - (icon[1] + icon[3]),
        "below": icon[2] + icon[4] - (sub[2] + sub[4]),    # its bottom under the subtitle's bottom
    }


def drawn_renderer_icons() -> dict:
    """{art name: `drawn_renderer_icon` of its frame} for every frame that draws a renderer icon."""
    return {drawn_name(node)[1]: drawn_renderer_icon(key)
            for key, layout in DIALOG_LAYOUT.items() for node in layout["nodes"]
            if drawn_name(node)[0] == "renderer icon" and not key.startswith(QML_FRAME)}


def drawn_badges() -> dict:
    """{badge: (edge x, inset x, edge y, inset y, side)} off every T frame; repeats must match."""
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


QML_FRAME = "QML "    # what starts the key of a frame drawn in UI Design QML


def drawn_qml_buttons(frame_keys=("QML T20", "QML T23")) -> dict:
    """{button: place} on the QML tile's picture, each axis as `_badge_edge`; repeats must match."""
    out = {}
    for key in frame_keys:
        thumb = drawn_node(key, "thumbnail")
        for node in DIALOG_LAYOUT[key]["nodes"]:
            kind, x, y, w, h = drawn_name(node)[0], node[1], node[2], node[3], node[4]
            if not kind.startswith("badge "):
                continue
            (edge_x, inset_x), (edge_y, inset_y) = (_badge_edge(x, w, thumb[1], thumb[3]),
                                                    _badge_edge(y, h, thumb[2], thumb[4]))
            place = {"edgeX": edge_x, "insetX": inset_x, "edgeY": edge_y, "insetY": inset_y,
                     "width": w, "height": h, "picture": thumb[3]}
            if out.setdefault(kind[len("badge "):], place) != place:
                raise ValueError("button %s is drawn in two places" % kind)
    return out


def drawn_line_mark(frame_keys, kind) -> dict:
    """A mark on the QML tile's second line: its size, inset from the card's right edge and drop."""
    places = []
    for key in frame_keys:
        card, sub, mark = (drawn_node(key, part) for part in ("tile card", "tile subtitle", kind))
        places.append({"width": mark[3], "height": mark[4],
                       "inset": card[1] + card[3] - (mark[1] + mark[3]),
                       "below": mark[2] + mark[4] - (sub[2] + sub[4])})    # its bottom under the subtitle's
    if any(place != places[0] for place in places):
        raise ValueError("%s is drawn in two places" % kind)
    return places[0]


def drawn_mark_gap(frame_key: str, left: str, right: str):
    """The drawn gap between two marks side by side on the QML tile's second line."""
    first, second = drawn_node(frame_key, left), drawn_node(frame_key, right)
    return second[1] - (first[1] + first[3])


def drawn_list(frame_key: str = "L01") -> dict:
    """The list's header, widths, text inset and tick box, off its frame. ▸r/list-from-frame"""
    columns, cells = (drawn_by_owner(frame_key, kind) for kind in ("column", "cell"))
    tick = drawn_node(frame_key, "tick box")
    first = next(iter(columns))
    return {
        "header_h": columns[first][4],
        "text_inset": cells[first][1] - columns[first][1],
        "widths": {key: n[3] for key, n in columns.items()},
        "tick_pad": tick[1] - columns[drawn_name(tick)[1]][1],
        "tick_side": tick[3],
    }


def drawn_band(frame_key: str) -> tuple:
    """(height, text inset) of the frame's header band; HEADER_BAND_H and _INSET without one."""
    nodes = (DIALOG_LAYOUT.get(frame_key) or {}).get("nodes", ())
    band = next((n for n in nodes if n[0] == "header band"), None)
    if band is None:
        return HEADER_BAND_H, HEADER_BAND_INSET
    label = next((n for n in nodes if n[0] == "QLabel" and n[2] < band[2] + band[4]), None)
    return band[4], (label[1] - band[1]) if label else HEADER_BAND_INSET


def drawn_code_dialog(frame_key: str = "D11") -> dict:
    """The code dialog's margins and gaps, its two label columns, and the editor's own sizes."""
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
    """A dialog list's margins, its size, the gap to its buttons and where its second column starts."""
    layout = DIALOG_LAYOUT[frame_key]

    def named(name):
        return sorted((n for n in layout["nodes"] if n[0] == name),
                      key=lambda n: (n[2], n[1]))

    view, = named("QListWidget")
    paths = named("QListWidget ▸ item ▸ path")
    buttons = named("QPushButton")
    width, height = layout["frame"]
    return {
        "margins": (view[1], view[2],                    # left, top: neither list has a header band
                    width - (view[1] + view[3]),         # right, bottom
                    height - (buttons[0][2] + buttons[0][4])),
        "view": (view[3], view[4]),
        "button_top": buttons[0][2] - (view[2] + view[4]),    # the list's bottom to the buttons
        "button_gap": buttons[1][1] - (buttons[0][1] + buttons[0][3]),
        "button_widths": [n[3] for n in buttons],    # left to right
        "second_x": min(n[1] for n in paths) - view[1],    # the name column's width
    }


def drawn_toolbar(frame_key: str = "B01") -> dict:
    """The toolbar's height, edges, gaps and control sizes, off its frame. ▸r/toolbar-from-frame"""
    layout = DIALOG_LAYOUT[frame_key]

    def node(kind, owner=None):
        return drawn_node(frame_key, kind, owner)

    def right(n):
        return n[1] + n[3]

    slider, label = node("slider", "click_slider"), node("label", "filter_label")
    field, search = node("field", "line_filter"), node("icon", "line_filter")
    switch = node("buttons list-grid")    # grid and list: two segments, one control
    segments = (node("segment 1"), node("segment 3"))
    buttons = sorted(drawn_by_owner(frame_key, "button").items(), key=lambda item: item[1][1])
    controls = sorted(buttons + [(drawn_name(switch)[1], switch)], key=lambda item: item[1][1])
    left = [(owner, n) for owner, n in controls if n[1] < slider[1]]
    right_end = [(owner, n) for owner, n in controls if n[1] > field[1]]
    (_, first), (_, second) = left[0], left[1]
    icons = {owner: n[3] for owner, n in drawn_by_owner(frame_key, "icon").items()}
    placed = {owner: {"x": n[1] - dict(buttons)[owner][1], "y": n[2] - dict(buttons)[owner][2]}
              for owner, n in drawn_by_owner(frame_key, "icon").items() if owner in dict(buttons)}
    return {
        "left": tuple(owner for owner, _n in left),    # the controls left of the slider, in drawn order
        "right": tuple(owner for owner, _n in right_end),    # and those right of the search field
        "height": layout["frame"][1],
        "edge": first[1],
        "right_edge": layout["frame"][0] - right(right_end[-1][1]),
        "gap": second[1] - right(first),
        "segment": segments[0][3],    # each segment of the grid and list switch
        "segment_gap": segments[1][1] - right(segments[0]),
        "slider_gap": slider[1] - right(left[-1][1]),
        "slider_top": slider[2],    # B01 centres it above the bottom border, the buttons in the whole row
        "search_gap": label[1] - right(slider),
        "label_w": label[3],
        "label_inset": node("text", "filter_label")[1] - label[1],    # the word inside its label
        "label_gap": field[1] - right(label),
        "button": first[3],
        "icons": icons,    # each button's own drawn icon, by its object name
        "icon_at": placed,    # where each icon sits inside its button, as drawn
        "chip_icon": icons["btn_categories"],    # a toggle the frame does not draw
        "menu_icon": icons["btn_menu_view"],     # a menu button the frame does not draw
        "slider_w": slider[3],
        "slider_h": slider[4],
        "track": node("groove", "click_slider")[4],    # the groove's thickness
        "handle": node("handle", "click_slider")[3],
        "field_w": field[3],
        "field_h": field[4],
        "search_icon": search[3],
        "search_pad": search[1] - field[1],
    }


def drawn_tabs(frame_key: str = "S01") -> dict:
    """The section strip's height, left edge and tab icons' art and size, off S01. ▸r/tabs-from-frame"""
    icons = {key: (drawn_name(icon)[2], icon[3], icon[4])    # {section key: (art file, width, height)}
             for key, icon in drawn_by_owner(frame_key, "icon").items()}
    return {"height": DIALOG_LAYOUT[frame_key]["frame"][1], "left": drawn_node(frame_key, "tray")[1],
            "icons": icons}


def drawn_sidebar(frame_key: str = "G01") -> dict:
    """The sidebar's width, colour bar and splitter handle, off its frame. ▸r/sidebar-from-frame"""
    bar, row = drawn_node(frame_key, "bar"), drawn_node(frame_key, "row")
    return {"width": drawn_node(frame_key, "list")[3], "bar": bar[3],
            "bar_x": bar[1], "bar_inset": (row[4] - bar[4]) / 2,    # the bar's left edge, its gap above and below
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


def drawn_info(frame_key: str = "N02") -> dict:
    """The info pane's width, header, row height and label column, off its frame."""
    width = DIALOG_LAYOUT[frame_key]["frame"][0]

    def node(kind, owner=None):
        return drawn_node(frame_key, kind, owner)

    header, icon, name = node("header"), node("icon", "header"), node("text", "name")
    row = node("row", "2")
    button, preview = node("icon", "preview"), node("preview")
    return {
        "width": width,
        "header": header[4],
        "pad": icon[1] - header[1],
        "preview_button": button[3],
        "preview_button_pad": width - (button[1] + button[3]),    # its inset from the header's right
        "preview_button_top": button[2] - header[2],
        "preview_height": preview[4],    # the picture area until its line is dragged
        "drag_line": node("line", "drag")[4],
        "gap": name[1] - (icon[1] + icon[3]),
        "icon": icon[3],
        "row": row[4],
        "label_width": node("divider")[1] - row[1],    # the value column starts at the drawn divider
        "label_inset": node("label", "1")[1] - row[1],    # each column's text inside it
        "value_inset": node("value", "1")[1] - node("divider")[1],
        "divider": INFO_DIVIDER_WEIGHT,    # centred on the column edge, in the page colour
    }
