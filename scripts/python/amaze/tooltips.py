"""Every hover text Amaze shows, in ONE document - one edit here rewords the control wherever it is built. ▸p/messages-need-one-home"""

from __future__ import annotations


PREFS_LIBRARY_PATH = 'Where your library is saved.'   # ▸ Preferences - Library tab (D04)

PREFS_CLEAN_UP_LIBRARY = 'Finds files that no longer belong and moves them aside for 30 days. Nothing you can see in the panel is removed.'

PREFS_RELOAD_LIBRARY = 'Reload the library from disk.'

PREFS_OPEN_LIBRARY_FOLDER = 'Open the library folder.'

PREFS_MATERIAL_VERSIONS = "When on, saving over a material asks if you want to keep the old one as a version. When off, saving always adds a new material. This setting is stored in the library, so it applies to everyone who uses it."

PREFS_LIBRARY_USER = "Who you are in this library. Your favorites and folders follow your name, so the same person on another machine sees the same items, and two people sharing one library keep their things separate. Your name also signs the versions you save. It is never guessed from your machine name."

PREFS_RENAME_USER = 'Change the name shown for this user. Only the name changes; your favorites and folders stay yours.'

PREFS_DELETE_USER = 'Remove this user, their favorites, and their folders. You will be asked to confirm.'

PREFS_CACHE_PATH = 'Where preview copies are kept on this machine.'

PREFS_DEFAULT_CACHE = 'Move the preview cache back to its default location. Nothing is deleted; previews are rebuilt at the new location as you browse.'

PREFS_DELETE_LOCAL_CACHE = 'Delete the preview copies. They rebuild as you browse; your library is not touched.'

PREFS_RENDER_SIZE = 'Thumbnail size in pixels. Bigger looks sharper but takes longer to render.'   # ▸ Preferences - Render tab (D05)

PREFS_SAMPLES_REDSHIFT = 'Render quality for Redshift thumbnails.'

PREFS_SAMPLES_KARMA = 'Render quality for Karma thumbnails. 9 is the Karma default.'

PREFS_RAM_CACHE = 'Memory used to keep thumbnails ready. More memory means smoother scrolling.'

PREFS_GEOMETRY_SHADING = 'How geometry thumbnails are drawn: shaded, wireframe, or both.'

PREFS_GEOMETRY_BACKGROUND = 'The background behind geometry thumbnails.'

PREFS_RENDER_ON_IMPORT = 'Render thumbnails as soon as you import materials. Turn off to render them later with Update Preview.'

PREFS_CONVERSION_THREADS = 'How many textures (EXR/HDR) are turned into thumbnails at the same time.'

PREFS_DOWNLOAD_RESOLUTION = 'The texture size to download. If that size is not available, the largest one available is used.'

PREFS_PARALLEL_DOWNLOADS = 'How many previews download at the same time. More is faster because these wait on network delay, not your bandwidth.'

PREFS_RENDERER_SWITCH = 'Which renderers Amaze offers. Hide the ones you do not use.'   # ▸ Preferences - Show/Hide tab (D06)

PREFS_SECTION_SWITCH = 'Which sections the panel shows. Hiding a section keeps everything in it; its tab is just hidden.'

PREFS_SIDEBAR_COUNTS = 'Show how many items each category has.'   # ▸ Preferences - Look tab (D07)

PREFS_HIDE_EMPTY_CATEGORIES = 'Hide categories that have no items. They come back when you add items.'

PREFS_SHOW_UNKNOWN_FILES = 'Show files Amaze cannot preview, using their system icon. Each location can turn this off in its right-click menu.'

PREFS_WRITE_PATHS_AS = 'How Amaze writes paths in Copy Path and the File section. A variable is used when the path is inside it; otherwise the path is written as is.'

PREFS_TILE_ICON_LINE = 'Line weight of the tile icons: thin or regular.'

PREFS_SCROLL_SPEED = 'How fast the grid scrolls. 100 is the default.'

PREFS_INSTALL_UPDATE = 'Download and install the new release. Your library and settings are not affected; Houdini must be restarted afterwards.'   # ▸ Preferences - About tab (D08)

PREFS_CHECK_FOR_UPDATES = 'Check if a newer Amaze is available. Nothing is downloaded or changed.'

PREFS_REPORT_A_BUG = 'Open the Amaze bug page with your Amaze, Houdini, and OS versions already filled in. Nothing is sent until you press Submit.'

PREFS_DEBUG_MODE = 'Write a session log to help diagnose problems. Off by default.'

PREFS_OPEN_LOG = 'Open the debug log.'

PREFS_SAVE_LOG = 'Copy the debug log to a folder you choose. The copy is named for this machine and Houdini version, and contains your file paths, asset, and material names.'

PREFS_CLEAR_LOG = 'Clear the log and start fresh.'

PREFS_TEST_LIBRARY = 'Try things out on a throwaway library instead of your real one. Point it at any folder: Amaze uses its lib/ folder as the library and creates it if it is missing. The preview cache is not moved. Your real library, cache, and folders are not touched and come back when you turn this off.'

PREFS_TEST_FOLDER = 'The folder that holds the test library.'

CUSTOMIZE_TILE_NAME = 'Rename this tile. The name drives the grid, the sidebar count, and every search.'   # ▸ Customize dialog (D02)

CUSTOMIZE_CATEGORY = 'Move to this category. Applies to every selected tile.'

CUSTOMIZE_TAGS_ONE_TILE = 'Tags for this tile, separated by commas.'

CUSTOMIZE_TAGS_MANY_TILES = 'Tags to add to every selected tile, separated by commas. Each tile keeps the tags it already has.'

CUSTOMIZE_CUSTOM_ICON = 'Off shows the tile own thumbnail; on uses the icon you choose.'

CUSTOMIZE_LIGHT_ICON = 'Draw the icon lines light for a dark background.'

CUSTOMIZE_CUSTOM_COLOR = 'The current background. Click to pick any color with Houdini color picker.'

SAVE_NAME = 'Name it, pick a category, and add tags so you can find it later.'   # ▸ Save dialogs (D09, D11)

CODE_NAME = 'Name it, pick a category, and add tags so you can find it later.'

PANEL_FAVORITES = 'Show favorites.'   # ▸ Panel toolbar

PANEL_COMMENTS = 'Comments - notes and to-dos for the selected tile.'

PANEL_ONLINE = 'Browse materials online.'

PANEL_VIEW_MENU = 'Import a gallery file, or generate a material.'

PANEL_KIND_FILTER = 'Show one kind of tile.'

PANEL_PREFERENCES = 'Open preferences.'

PANEL_CATEGORIES = 'Show the category sidebar.'

PANEL_CAPTURE = 'Capture a preview from the scene view pane.'

PANEL_VIEW_MODE = 'Switch between the thumbnail grid and the detail list.'

PANEL_SEARCH = 'Search for items. Put a colon first to search tags instead: :metal finds everything tagged metal.'   # ▸ Panel filter row

PANEL_TILE_SIZE = 'Tile size.'

PANEL_TILE_SIZE_LIST = 'Tile size - grid only. A list row is one text line, so it does not scale.'

PANEL_VERSION_ROW = 'Pick the active version in the list, or rename it in the field. Versions are made automatically when you save.'   # ▸ Versions dialog (D01)

BADGE_VERSIONS = 'Click to select a version.'   # ▸ Tile badges, on hover

BADGE_COMMENTS = 'Show comments.'

BADGE_FAVORITE_REMOVE = 'Remove from favorites.'

BADGE_FAVORITE_ADD = 'Add to favorites.'

NOTES_ADD_TODO = 'Add a to-do where the cursor is.'   # ▸ Comments pane
