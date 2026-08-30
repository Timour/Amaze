"""Every hover text Amaze shows, in ONE document - one edit here rewords the control wherever it is built. ▸p/messages-need-one-home"""

from __future__ import annotations


PREFS_LIBRARY_PATH = 'The folder the library lives in.'   # ▸ Preferences - Library tab (D04)

PREFS_CLEAN_UP_LIBRARY = 'Tidy up: missing files are reported, leftovers are set aside for 30 days. Everything still showing in the panel stays.'

PREFS_RELOAD_LIBRARY = 'Read the library from disk again.'

PREFS_OPEN_LIBRARY_FOLDER = 'Open the library folder.'

PREFS_MATERIAL_VERSIONS = "Whether saving over an existing material creates a new VERSION of it. Stored in the library itself, not in your preferences - so it applies to everyone who opens this library, on every machine. ON: saving over an existing material offers Save Version - the old version is kept, and the tile's badge switches between them any time. OFF: saving always adds a separate new material, and existing ones are never touched."

PREFS_LIBRARY_USER = "Who you are in this library. Your favorites and your folders are saved under you, so the same user on another computer gives you the same things back - and two people sharing one library keep theirs apart. It also signs the versions you save. Never taken from your computer's user or machine name."

PREFS_RENAME_USER = 'Change the name shown for this user. Only the name changes - your favorites and folders stay yours.'

PREFS_DELETE_USER = 'Remove this user from the library, along with their favorites and registered folders. Asks first.'

PREFS_CACHE_PATH = 'Where the preview copies live on this machine.'

PREFS_DEFAULT_CACHE = 'Put the preview cache back where this machine keeps it. Nothing is deleted - previews at the old location stay where they are, and remake themselves at the new one as you browse.'

PREFS_DELETE_LOCAL_CACHE = 'Throw away the preview copies. They are remade as you browse, the library is untouched.'

PREFS_RENDER_SIZE = 'Thumbnail resolution in pixels. Bigger is sharper and slower.'   # ▸ Preferences - Render tab (D05)

PREFS_SAMPLES_REDSHIFT = 'Render quality for Redshift thumbnails.'

PREFS_SAMPLES_KARMA = "Render quality for Karma thumbnails, 9 is Karma's default."

PREFS_RAM_CACHE = 'Memory for keeping thumbnails ready. More scrolls smoother.'

PREFS_GEOMETRY_SHADING = 'How geometry thumbnails are drawn: shaded, wireframe or both.'

PREFS_GEOMETRY_BACKGROUND = 'The backdrop for geometry thumbnails.'

PREFS_RENDER_ON_IMPORT = 'Render thumbnails as soon as materials are imported. Off = render later with Update Preview.'

PREFS_CONVERSION_THREADS = 'How many texture conversions (EXR/HDR to thumbnail) run at once.'

PREFS_DOWNLOAD_RESOLUTION = 'Texture resolution to download. A floor, not a hard match: the next highest available is used, or the highest below.'

PREFS_PARALLEL_DOWNLOADS = 'Preview downloads at once. These wait on network latency rather than bandwidth, so more is markedly faster.'

PREFS_RENDERER_SWITCH = "Which renderers Amaze offers. Hide the ones you don't use."   # ▸ Preferences - Show/Hide tab (D06)

PREFS_SECTION_SWITCH = 'Which sections the panel shows. A hidden section keeps everything, the tab just goes away.'

PREFS_SIDEBAR_COUNTS = 'Show how many things each category holds.'   # ▸ Preferences - Look tab (D07)

PREFS_HIDE_EMPTY_CATEGORIES = 'Hide categories with nothing in them, they come back when something lands there.'

PREFS_SHOW_UNKNOWN_FILES = 'Show files Amaze has no preview for, using their system icon. Each location can override this in its own right-click menu.'

PREFS_WRITE_PATHS_AS = "How Amaze writes paths - Copy Path and the File section's location labels. A variable applies when the path lives under it; otherwise the path stays absolute."

PREFS_TILE_ICON_LINE = 'Line weight of the tile icons, thin or regular.'

PREFS_SCROLL_SPEED = 'How fast the grid scrolls, 100 is normal.'

PREFS_INSTALL_UPDATE = 'Download the new release and put it in place. Your library and your settings are not touched, and Houdini must be restarted afterwards.'   # ▸ Preferences - About tab (D08)

PREFS_CHECK_FOR_UPDATES = 'Ask whether a newer Amaze has been released. Nothing is downloaded or changed by asking.'

PREFS_REPORT_A_BUG = 'Open the Amaze bug page in your browser with your Amaze, Houdini and OS versions already filled in. Nothing is sent until you press Submit there.'

PREFS_DEBUG_MODE = 'Write a structured session log for diagnosing problems. Off by default.'

PREFS_OPEN_LOG = 'Open the debug log.'

PREFS_SAVE_LOG = "Copy the debug log to a folder you choose, named for this\nmachine and Houdini version - so two machines' logs can sit\nside by side when a problem happens on only one of them.\n\nThe copy contains your file paths, asset and material names."

PREFS_CLEAR_LOG = 'Empty the log and start fresh.'

PREFS_TEST_LIBRARY = 'Work against a throwaway library instead of the real one. Point it at any folder: Amaze uses the lib folder inside it as the library and the cache folder as the preview cache, making either if it is missing. Your real Library Path, Cache Path and registered folders are left exactly as they are and come back when you switch this off.'

PREFS_TEST_FOLDER = 'The folder holding the test lib and cache folders.'

CUSTOMIZE_TILE_NAME = 'Rename this tile. The name is what the grid, the sidebar count and every search look at.'   # ▸ Customize dialog (D02)

CUSTOMIZE_CATEGORY = 'Move to this category. Applies to every tile you have selected.'

CUSTOMIZE_TAGS_ONE_TILE = 'Tags for this tile, separated by commas.'

CUSTOMIZE_TAGS_MANY_TILES = 'Tags to ADD to every tile you have selected, separated by commas. Each tile keeps the tags it already has.'

CUSTOMIZE_CUSTOM_ICON = "Off shows the tile's own thumbnail; on uses the icon chosen here."

CUSTOMIZE_LIGHT_ICON = "Draws the icon's lines light, for a dark background."

CUSTOMIZE_CUSTOM_COLOR = "The current background. Click to pick any color, with Houdini's color picker."

SAVE_NAME = 'Name it, pick a category, and add tags to find it again later.'   # ▸ Save dialogs (D09, D11)

CODE_NAME = 'Name it, pick a category, and add tags to find it again later.'

PANEL_FAVORITES = 'Show favorites.'   # ▸ Panel toolbar

PANEL_COMMENTS = 'Comments - a page of text and to-dos for the selected tile'

PANEL_ONLINE = 'Browse materials online.'

PANEL_VIEW_MENU = 'Import a gallery file, or generate a material.'

PANEL_KIND_FILTER = 'Show one kind of tile.'

PANEL_PREFERENCES = 'Open preferences.'

PANEL_CATEGORIES = 'Show the category sidebar.'

PANEL_CAPTURE = 'Captures a preview from "scene view" pane'

PANEL_VIEW_MODE = 'Switch between the thumbnail grid and the detail list.'

PANEL_SEARCH = 'Search for objects, a leading colon searches tags instead: :metal finds everything tagged metal.'   # ▸ Panel filter row

PANEL_TILE_SIZE = 'Tile size.'

PANEL_TILE_SIZE_LIST = 'Tile size - grid only. A list row is one text line, so it does not scale.'

PANEL_VERSION_ROW = 'Pick the active version in the list, rename it in the field. Versions are made automatically when you save.'   # ▸ Versions dialog (D01)

BADGE_VERSIONS = 'Click to select version'   # ▸ Tile badges, on hover

BADGE_COMMENTS = 'Show comments'

BADGE_FAVORITE_REMOVE = 'Remove from favorites'

BADGE_FAVORITE_ADD = 'Add to favorites'

NOTES_ADD_TODO = 'Add a to-do at the cursor'   # ▸ Comments pane
