"""Every dialog message; a button set puts the accepting one first. ▸p/messages-in-three-places"""

from __future__ import annotations

DATABASE_CORRUPT_READ_ONLY = "Your %s database is corrupt/unreadable, so Amaze has opened it read-only; changes made now stay in memory only. Restore a backup with Check in Preferences ▸ Library."
DATABASE_MISSING_READ_ONLY = "Your %s database is missing from the library folder, though Amaze can see it was there before. If the folder syncs, it may not have finished yet. Until it is back the database is read-only; if it does not come back, use Check in Preferences ▸ Library."
DATABASE_SHRUNK = "Your %s database holds %d %s, but its newest backup holds %d %s. If you did not remove them yourself, use Check in Preferences ▸ Library before you change anything - it can restore that backup."
LIBRARY_FORMAT_AHEAD_READ_ONLY = "This library was saved by a newer Amaze, so this machine opens it read-only to protect it. Update Amaze to work with it normally."
LIBRARY_WRITE_FAILED = "Amaze could not save the library: %s The change is kept in memory and is written with the next successful save, but it is lost if Houdini closes first."
PALETTE_NOT_DELETED = "\"%s\" was not deleted because the colors database is read-only right now. Use Check in Preferences ▸ Library, then try again."
ASSET_NOT_SAVED_DATABASE_REFUSED = "\"%s\" was not saved: its database is read-only right now, so neither its files nor its entry were written. Use Check in Preferences ▸ Library, then save again."
ASSET_NOT_DELETED_LIST_NOT_UPDATED = "\"%s\" was not deleted because its database could not be updated. Use Check in Preferences ▸ Library, then try again."
CHANGE_REFUSED_READ_ONLY = "The change was not made: your %s database is read-only right now. Use Check in Preferences ▸ Library, then try again."
EDIT_CONFLICT_KEPT_YOURS = "Someone else changed \"%s\" while you had it open.\n\nAmaze kept your version and discarded theirs."
EDIT_CONFLICT_KEPT_YOURS_BY = "%s changed \"%s\" while you had it open.\n\nAmaze kept your version and discarded theirs."
UNSAFE_ARCHIVE_PATHS_SKIPPED = "%d file(s) in this download tried to write outside your library folder and were skipped. Nothing outside the library was touched; the rest imported normally. If the material looks wrong, delete it and download again."
NO_LIBRARY_FOLDER_CONFIGURED = "Amaze has no library folder set. Pick one in Preferences (Amaze panel), then run Check Library again."
LIBRARY_FOLDER_UNREACHABLE = "Amaze can't reach its library folder:\n%s\nIf it's on a drive or in a synced folder, connect it and run Check Library again. If you moved the library, point Preferences at the new location."
NOTHING_CHANGED_REASON = 'Amaze changed nothing: %s.'
LIBRARY_CHANGED_SINCE_CHECK = "Something changed in the library since the check. Run Check Library again."

USER_DELETE_CONFIRM = "Delete user \"%s\" from this library?"
USER_NAME_TAKEN = "A user named \"%s\" already exists in this library. Choose another name."
NO_USER_PICKED = "No user is picked for this library. Open Preferences, pick or create your user, and press Apply."
MATERIAL_VERSIONS_TURN_ON_CONFIRM = "Turn on Material Versions for this library?"
LIBRARY_SETTING_NOT_WRITTEN = "The setting could not be written to the library folder, so it was not changed."
PICTURE_NOT_COPIED_TO_LIBRARY = "That picture could not be copied into the library, so it was not added."
PICTURE_COPIED_BUT_UNREADABLE = "That file was copied but couldn't be read as a picture, so it was not added."
LIBRARY_INDEX_UNREADABLE = "The library's Materials database is corrupt/unreadable."
DATABASE_STILL_UNREADABLE = "The Materials database cannot be read. Create a new Library or use Check Library on the Amaze shelf to restore a backup or rebuild it."
LIBRARY_INDEX_UNREADABLE_SWITCHING = "The library's Materials database is corrupt/unreadable."
DATABASE_STILL_UNREADABLE_SWITCHING = "The Materials database cannot be read."
LIBRARY_INDEX_READ_NOT_PERMITTED = 'this account is not allowed to read it:\n%s\n\nThe permissions on the file, or on a folder above it, have to let this account read it.'

LIBRARY_NOT_OPENED = 'The library could not be opened because %s\n\nAmaze will open without a library.'

LIBRARY_NOT_OPENED_SWITCHING = 'The library could not be opened because %s\n\nAmaze keeps the library you have open.'

LIBRARY_LIST_NOT_LOADED = 'one of its databases could not be loaded (%s).'

LIBRARY_FOLDER_NOT_EMPTY = "This folder is not empty. Pick an empty folder for a new library."
NO_FOLDER_SELECTED_TO_RELOCATE = "Select the registered folder to re-point first (\"All\" is not a real folder)."
RELOCATE_TARGET_NOT_A_FOLDER = "That location isn't a folder."
LOCATION_ALREADY_ADDED = "That location is already added."
REMOVE_LOCATION_CONFIRM = "Remove %s from the File section? The files stay on disk. Their comments, icons and favorites in Amaze are removed for every user."
NO_LIBRARY_CONFIGURED = "Set up a library first."
PACKAGE_IMPORT_SUMMARY = "Imported %d asset(s) and %d file(s) into the Import category."
PACKAGE_COMMENTS_NOT_WRITTEN = "The comments of %s could not be saved."
PACKAGE_EXPORTED = "Exported %d items to %s."
PACKAGE_EXPORTED_ONE = "Exported 1 item to %s."
PACKAGE_EXPORT_EMPTY = "Nothing to export. This category is empty."
PACKAGE_NOT_SAVED = "The package could not be saved: %s"
PACKAGE_NOT_READABLE ='"%s" is not a package Amaze can read.'
PACKAGE_TOO_LARGE = "This package unpacks to %s, more than the %s Amaze imports at once."
DOWNLOAD_TOO_LARGE = "This download is larger than the %s Amaze imports at once."
MATERIAL_PRESETS_FOUND = "No material presets found in: %s"
IMPORT_MATERIAL_PRESETS_FROM = "Import %d material presets from:\n%s\n\n%s\n\nPreviews aren't generated during import — select the new materials afterwards and use Render Image."
IMPORT_MATERIAL_PRESETS_FROM_RENDERING = 'Import %d material presets from:\n%s\n\n%s\n\nNote: Thumbnails are rendered in one batch once the import finishes.'

GALLERY_IMPORT_FINISHED_IMPORTED_SKIPPED = "Gallery import complete.\nImported: %d\nSkipped: %d\nFailed: %d\n\nSelect the new materials and use Render Image to render them."
GALLERY_IMPORT_FINISHED_RENDERING = 'Gallery import complete.\n\nImported: %d\nSkipped: %d\nFailed: %d\n\nTheir thumbnails are rendering now.'

GALLERY_IMPORT_INTERRUPTED = 'Gallery import stopped.\n\nImported: %d\nSkipped: %d\nFailed: %d\n\nTo render them, select the new materials and use Render Image.'
GALLERY_IMPORT_INTERRUPTED_RENDERING = 'Gallery import stopped.\n\nImported: %d\nSkipped: %d\nFailed: %d\n\nTheir thumbnails are rendering now.'
GALLERY_NOT_PUT_BACK = "Amaze read the gallery %s, but could not put it back in Houdini's gallery list."

NO_LIBRARY_OPEN = "Open a library first."
AMAZE_COULD_NOT = "%d of %d items could not be imported."
SCENE_BUILD_PARTIAL_FAILURE = "%d of %d could not be built."
TILE_ICON_SAVE_FAILED = "%d tile icon%s could not be saved - check that the library folder is writable."
CAPTURE_SELECT_ONE_TILE = "Select one tile to capture onto."
CAPTURE_NO_FILE = "No file was given for the capture."
CAPTURE_NO_ASSETUTILS = "This Houdini has no husd.assetutils (%s), so the viewport cannot be captured."
CAPTURE_NO_VIEWER = "No scene viewer is open - the capture needs a visible viewport to capture."
CAPTURE_VIEWPORT_UNMEASURED = "Could not measure the viewport: %s"
CAPTURE_VIEWPORT_ZERO = "The viewport reports a zero size - it may be hidden or collapsed."
CAPTURE_FOLDER_FAILED = "Could not create %s: %s"
CAPTURE_WRITE_FAILED = "Houdini could not write the thumbnail: %s: %s"
CAPTURE_WROTE_NOTHING = "Houdini reported the capture finished but no image was written.\n\nThe debug log has the viewport details - Preferences > Save Log... if you want to send them on."
CAPTURE_FLAT = "The captured frame was a single flat colour, so nothing was stored. The existing thumbnail is untouched."
CAPTURE_NOT_STORED = "The capture could not be stored in the library, so the existing thumbnail is untouched. The debug log says why."
CAPTURE_NO_SCENE = "No scene is open, so there is nothing to capture."
CAPTURE_OTHER_SCENE = "Houdini has a different scene open, so the capture would be filed under the wrong name.\n\nOpen this scene first."
CAPTURE_SCENE_UNSAVED = "This scene has not been saved yet, so there is nothing to file a thumbnail against.\n\nSave the scene first."
CAPTURE_VIEWPORT_RENDERING = "Please stop the viewport render before capturing."
CAPTURE_RENDERER_DETECTED = "\n\nDetected: %s"
NO_LIBRARY_CONFIGURED_2 = "Set up a library first: open Preferences, add one under Library, press Apply."
NO_NODE_TO_SAVE = "Right-click the node or network you want to save."
RESTART_TO_FINISH_UPDATE = "Amaze was updated while Houdini was running. Restart Houdini to finish."
NODE_CANNOT_BE_SAVED = "\"%s\" can't be saved — it's not a material, color ramp, code node or network."
NODE_SAVE_FAILED_WITH_REASON = "\"%s\" could not be saved: %s"
NODE_SAVE_FAILED = "\"%s\" could not be saved."
OBJECT_HAS_NO_MATERIAL_PARM = "\"%s\" has no material parameter, so nothing was imported."
DROP_CANCELED = 'The action was canceled.'

MOVE_DONE = 'Moved %s to %s.'

MOVE_BACK = 'Moved %s back.'

MOVE_ONE_FILE = '1 file'

MOVE_FILES = '%d files'

MOVE_PROGRESS = 'Moving %s to %s: %d%%'

MOVE_TAKEN = 'A file named %s is already in %s, so it was not moved.'

MOVE_TAKEN_MANY = 'Files named %s are already in %s, so they were not moved.'

MOVE_MORE = '%d more'

MOVE_FAILED = '%s could not be moved: %s.'

MOVE_KEPT_BOTH = 'the copy is in place, but the original could not be removed (%s)'

MOVE_OPEN_SCENE = '%s is the scene open in Houdini, so it was not moved.'

MOVE_BUSY = 'Another move is still running.'

PASTE_DONE = 'Pasted %s into %s.'

PASTE_PROGRESS = 'Pasting %s into %s: %d%%'

PASTE_TAKEN = 'A file named %s is already in %s, so it was not pasted.'

PASTE_TAKEN_MANY = 'Files named %s are already in %s, so they were not pasted.'

PASTE_FAILED = '%s could not be pasted: %s.'

PASTE_FOLDER = '%s is a folder, so it was not pasted.'

PASTE_ASK = 'A file named %s is already in %s.'

PASTE_ASK_MANY = 'Files named %s are already in %s.'

BUTTONS_OVERWRITE_OR_SKIP = ('Overwrite', 'Skip', 'Cancel')

STOCK_LOP_HELPERS_UNAVAILABLE = "Could not load Houdini's material-assignment helpers — material not imported."
NETWORK_REFUSED_MATERIAL_LIBRARY = "%s can't take a Material Library, so the material was not imported.\n\n%s"
MATERIAL_ASSIGN_FAILED = "Imported, but assigning failed: %s"
NO_MATERIAL_DESTINATION_NETWORK = "No place to create the material — dive into a Material Library or /mat first."
LOP_IMPORT_OUTSIDE_LIBRARY = 'A material goes into a Material Library. Dive into one and import again.'

IMPORTING_ONLINE_MATERIALS = 'Importing online materials'

SAVING_MATERIALS = 'Saving materials'

UPDATING_MATERIALS = 'Updating materials'

ONLINE_IMPORT_STOPPED = 'Import stopped after %d of %d.'

SAVE_STOPPED = 'Saving stopped after %d of %d.'

MATERIAL_GENERATION_FAILED = "Generation failed — see the debug log."
GENERATED_MATERIAL_MOVE_FAILED = "The generated material could not be moved into %s."
GENERATED_MATERIAL_NOT_REGISTERED = "\"%s\" was created in %s but is not on the library node's material list — check that list."
MATERIAL_GENERATION_ERROR = "Material generation failed (%s)."
NO_MATERIAL_SELECTED = "No material selected."
MATERIAL_UPDATED_LIBRARY_NOT_SAVED = "\"%s\" was updated, but the library could not be saved."
MATERIALS_UPDATED_LIBRARY_NOT_SAVED = "%d materials were updated, but the library could not be saved."
MATERIAL_NOT_UPDATED = "\"%s\" was not updated: %s"
MATERIALS_NOT_UPDATED = "Some materials were not updated."
MATERIAL_NOT_UPDATED_LINE = "\"%s\": %s"
UPDATE_REFUSED_GONE = "it is no longer in the library."
UPDATE_REFUSED_LIBRARY_UNREADABLE = "the Library database cannot be read."
UPDATE_REFUSED_NOT_KEPT = "its current state could not be kept as a version. Save it as a new material instead."
UPDATE_REFUSED_CHANGED_ON_DISK = "it was changed on disk since this session read it. Save it as a new material, or reopen the Amaze panel to load the other version first."
UPDATE_REFUSED_NOT_A_BUILDER = "the node is not a Material Builder."
SCENE_FILE_MISSING = "That scene file no longer exists: %s"
SCENE_OPEN_FAILED = "Could not open that scene: %s\n\n%s"
REVEAL_MISSING = "That file or folder no longer exists: %s"
REVEAL_FAILED = "Could not open the file browser: %s"
LIBRARY_PATH_INVALID = "Invalid path — try again."
LIBRARY_LIST_FULL = "The library list is full (%d). Remove one in Manage to add another."
TITLE_CHOOSE_LIBRARY_FOLDER = 'Choose a folder for your Amaze library'

IMPORTED_MATERIAL_MAY_NOT_APPEAR = "\"%s\" was imported into %s but may not appear as a material: %s."
MATERIAL_FAILED_TO_IMPORT = "\"%s\" failed to import."
NO_NODES_SELECTED_TO_SAVE = "No nodes selected — nothing to save."
NETWORK_EMPTY_NOTHING_TO_SAVE = "The network is empty — nothing to save."
OCIO_NOT_SET = "Set $OCIO first."
NODE_IS_NOT_A_MATERIAL_BUILDER = "The selected node is not a Material Builder."
PANEL_NOT_OPEN = "Open the %s panel first."
AMAZE_NOT_IMPORTABLE = "Amaze can't be imported in this session (%s).\n\nCheck that $AMAZE points at the install and that Houdini was restarted after it changed."
NO_RELEASE_TO_INSTALL = "No release to install — check for updates first."
INSTALL_LOCATION_UNKNOWN = "Amaze can't tell where it's installed, so it can't replace itself. Check that $AMAZE points at the install."
UPDATE_OFFER = "%s\n\nRestart Houdini after installing."
UPDATE_LIBRARY_AVAILABLE = "Amaze v%s is available. The library will be updated to v%s."
LIBRARY_UPDATE_WARNING = "The library will be updated and won't work with Amaze versions older than %s."
LIBRARY_NEEDS_NEWER_AMAZE = "This library is version %s and needs a newer Amaze. Update Amaze to open it."
LIBRARY_OLDER_THAN_2_0 = "it is older than version 2.0, which this Amaze cannot convert. Open it once in Amaze 1.48, which updates it to 2.0, then open it here."
LIBRARY_NEEDS_CONVERSION = ("This library is version 2.0. To open it, Amaze converts it to version 3.0: "
                            "each material and node gets its own folder with all its files, and the "
                            "matX folder goes to the library's trash. An older Amaze can't open it after that.")
LIBRARY_CONVERSION_FAILED = "The library couldn't be converted (%s). Amaze tries again the next time it opens."
UPDATE_INSTALLED = "Amaze %s installed. Restart Houdini to use it."
UPDATE_FAILED_UNEXPECTED = "The update couldn't be installed (%s)."
DOWNLOADING_UPDATE = 'Downloading the Amaze update'
DOWNLOADING_ADDONS = 'Downloading add-ons'
DOWNLOAD_STOPPED = 'The download was stopped.'
ADDONS_NONE = "No add-ons installed. Check for Updates finds them in the Amaze store."
ADDONS_UP_TO_DATE = "All add-ons are up to date."
ADDONS_AVAILABLE = "Available: %s."
ADDONS_INSTALLED = "Installed. Restart Houdini to load %s."
ADDONS_REST_STOPPED = "The download of the rest was stopped."
ADDONS_TURNED = "Restart Houdini to turn %s %s."
ADDONS_STORE_UNREACHABLE = "The Amaze store couldn't be reached (%s)."
ADDONS_LOCATION_UNKNOWN = "Amaze can't tell where it's installed, so it can't install add-ons. Check that $AMAZE points at the install."
ADDON_VERSION = 'version %s'
ADDON_FIELD_NOT_TEXT = '%s is not text'
ADDON_NODE_FIELD_NOT_TEXT = '%s: %s is not text'
ADDON_TOO_LARGE = 'it unpacks to %s, more than the %s an add-on may hold'
ADDON_FOLDER_TAKEN = "%s was not installed: its folder %s holds the add-on %s, which it may not replace."

ADDON_AUTHOR = 'author: %s'

CANNOT_LOAD_HERE = "This content can't be loaded into this context."
MATERIAL_ALREADY_IN_LIBRARY = '"%s" already exists in the library.'

MATERIALS_ALREADY_IN_LIBRARY = '%d of %d dropped materials already exist in the library.'

LIBRARY_UNREADABLE_SAVES_NEW = '\n\nThe Library database cannot be read, so the existing material stays as it is. Saving will add a new material.'

VERSIONS_OFF_KEEPS_NONE = '\n\nVersions is off for this library, so Overwrite keeps no version.'

SAVE_DID_NOT_COMPLETE_LINE = '"%s": the save did not complete'

CONVERSION_CRASHED_LINE = '"%s": crashed - %s'

MATX_RESOLUTION_SUBSTITUTED = '%s is not available for "%s"; %s was downloaded.'

MATX_NO_RESOLUTION_OFFERED = 'None of the downloads offered for "%s" names a resolution, so it was not imported.'

MATX_RESOLUTION_SETTING_UNREADABLE = 'The texture resolution set in Preferences, %s, is not a resolution, so "%s" was not imported.'

CONVERSION_NO_WIRED_SURFACE ='no shader is wired into the Surface input of the Redshift material'

ASSET_FAILED_TO_IMPORT_LINE = '"%s" failed to import: %s'

NAMELESS_NODE_ASSET = 'node asset'

NAMELESS_MATERIAL = 'material'

NO_LIBRARY_TO_IMPORT_INTO = 'No library to import into.'

ONLINE_SOURCE_UNKNOWN = 'Unknown source'

ONLINE_SOURCE_UNKNOWN_NAMED = 'Unknown source %s'

ONLINE_IMPORT_FAILED = 'Import failed.'

NO_DOWNLOADABLE_PACKAGE = '"%s" has no downloadable package.'

STORE_TILE_HAS_NO_ENTRY = 'the record carries no manifest entry'

STORE_TILE_NOT_IMPORTED = 'the tile could not be imported'

STORE_TILE_IMPORTED_NOTHING = 'nothing in this tile could be imported'

STORE_RESTORE_SUMMARY = 'Restored %d, %d replaced.'

NODE_HAS_NO_FILE_PARM = '%s has no file parameter to take %s'

NODE_HAS_NO_COLOR_RAMP = '%s has no color ramp to take the gradient'

LOG_SAVED_AS = 'Saved as:\n%s'

LOG_NOT_CLEARED = 'the debug log could not be cleared (%s). It is still there, and Debug Mode keeps writing to it.'

CHECK_LIBRARY_ONLY_A_REPORT = 'This Houdini session has already read this library, so this is only a report: open Amaze and use Check in Preferences ▸ Library to act on it.'

BUTTON_SHOW_IN_FOLDER = 'Show in Folder'



TITLE_AMAZE = 'Amaze'

TITLE_CHECK_LIBRARY = 'Check Library'

CHECK_FOUND_HEAD = 'Check Library found:'

BUTTON_FIX_ALL = 'Fix All'

BUTTON_FIX_SAFE = 'Fix Safe'

BUTTON_FIX_CANCEL = 'Cancel'

CHECK_NOTHING_TO_REPAIR = 'Nothing to repair.'

CHECK_DATABASE_CORRUPT = 'The %s database is corrupt.'

CHECK_DATABASE_MISSING = 'The %s database is missing.'

CHECK_DATABASE_NEWER = 'The %s database is from a newer Amaze.'

CHECK_DATABASE_IN_USE = 'The %s database is in use.'

CHECK_FOLDER_UNREAD = 'The %s folder cannot be read.'

CHECK_DRIVE_NOT_CONNECTED = "A folder's drive is not connected."

FIXED_RESTORED = '%s restored from its newest backup.'

FIXED_REBUILT = "%s rebuilt from the assets' own files."

FIXED_EMPTIED = '%s starts empty.'

CONFIRM_FIX_ALL_TRASH = 'Fix All moves these to the trash. An asset named here is removed from its database.'

BUTTONS_FIX_ALL_TRASH = ('Move to Trash', 'Skip These', 'Cancel')

FIXED_RECOVERED = '%s added to the database.'

FIXED_UNCATEGORIZED = '%s put in Uncategorized.'

FIXED_REMOVED = '%s removed from the database.'

FIXED_TRASHED = '%s moved to the trash.'

FIXED_FAVORITES = '%s removed.'

FIXED_FOLDERS = '%s removed from the Files section.'

CHECK_DATABASE_EMPTY_KEEPS = 'The %s database holds nothing, so the files that may be its stay where they are.'
CHECK_BACKUPS = 'It has %s.'
CHECK_NO_BACKUP = 'It has no backup.'
CHECK_DATABASE_SHRUNK = 'The %s database holds %d, under half of the %d its newest backup holds.'
CHECK_ROWS_WITHOUT_FILES = '%s in %s %s no files. A file still syncing looks the same.'
CHECK_UNLISTED_FOLDERS = '%s in no database; %d of them can be recovered from their own record.'
CHECK_ORPHANS = '%s that no database or version list names.'
CHECK_LEFTOVERS_FOUND = "%s left over from Amaze's own work."
CHECK_CONFLICTS_KEPT = '%s from a sync service, left where they are: each differs from its original, or has none.'
CHECK_UNKNOWN_FOUND = 'Not known to Amaze: %s.'
CHECK_NO_PICTURE = '%s with no picture.'
CHECK_NO_CATEGORY = '%s with no category, shown only under All.'
CHECK_LOCATIONS_GONE = 'Files section folders not on this computer: %s.'
CHECK_FAVORITES_GONE = '%s of files that are gone.'
CHECK_TRASH_EMPTY = "The library's trash is empty."
CHECK_TRASH_HOLDS = "The library's trash holds %s (%s); its oldest day is deleted on %s."
CHECK_REBUILD_REFUSED = 'The %s database reads, so it was left as it is.'
CHECK_FAVORITES_NOT_SAVED = 'The favorites could not be saved.'
CHECK_NEEDS_CONVERSION = 'This library is version 2.0: open it in Amaze and convert it to 3.0 first.'
CHECK_PICK_REPAIR = ("The %s database cannot be read. Restore its newest backup, from %s, or rebuild it "
                     "from the record in each asset's folder?")
CHECK_PICK_REBUILD = ("The %s database cannot be read and has no backup that reads. Rebuild it from the "
                      "record in each asset's folder?")
BUTTONS_RESTORE_OR_REBUILD = ('Restore Backup', 'Rebuild', 'Cancel')
BUTTONS_REBUILD_ONLY = ('Rebuild', 'Cancel')

TITLE_LOG_NOT_SAVED = 'Log not saved'

TITLE_LOG_SAVED = 'Log saved'

TITLE_SAVE_LOG_TO_FOLDER = 'Save Amaze log to folder'

TITLE_EMPTY_SNIPPET = 'Empty snippet'

TITLE_SAVE_TO = 'Save to %s'


BUTTONS_REPAIR_OR_OPEN_WITHOUT = ('Repair', 'Open Without Library')

BUTTONS_REPAIR_OR_CANCEL = ('Repair', 'Cancel')

BUTTONS_IMPORT = ('Import', 'Cancel')

BUTTONS_DELETE = ('Delete', 'Cancel')

BUTTONS_REMOVE = ('Remove', 'Cancel')

BUTTONS_DELETE_USER = ('Delete User', 'Cancel')

BUTTONS_OPEN_PREFERENCES = ('Open Preferences', 'Close')

BUTTONS_SHOW_IN_FOLDER = (BUTTON_SHOW_IN_FOLDER, 'Close')

BUTTONS_TURN_ON = ('Turn On', 'Cancel')

BUTTONS_INSTALL_UPDATE = ('Install Update', 'Later')

BUTTONS_CONTINUE = ('Continue', 'Cancel')

BUTTONS_UPDATE_AMAZE = ('Update Amaze', 'Cancel')
BUTTONS_CONVERT_LIBRARY = ('Convert', 'Cancel')

BUTTONS_SAVE_VERSION_OR_NEW = ('Save Version', 'Save New', 'Cancel')

BUTTONS_OVERWRITE_OR_NEW = ('Overwrite', 'Save New', 'Cancel')

BUTTONS_SAVE_NEW = ('Save New', 'Cancel')


HELP_MATERIAL_VERSIONS = "This is shared: everyone working from this library gets the same setting.\n\nWith it on, saving over an existing material keeps the previous version."
HELP_DELETE_USER = 'Their favorites and registered folders are removed from this library everywhere it syncs. A machine signed in as "%s" will ask who is using the library the next time it opens. This cannot be undone.'

HELP_LOG_SAVED = 'It contains your file paths, asset and material names - check before sharing it.'


SNIPPET_HAS_NO_CODE = "No code to save."
CODE_VERSION_UNREADABLE = "That version's file could not be read. The editor keeps the code it had."

SNIPPET_RUN_FAILED = "\"%s\" stopped: %s"
SNIPPET_NOT_PYTHON = "\"%s\" was not run: it is %s, and only a Python snippet runs in Houdini."
CONFIRM_CLEAR_THUMBNAIL_CACHE = "This deletes all cached thumbnails from disk. They regenerate as you browse."
NO_SCENE_VIEWER_FOR_THUMBNAIL = "Thumbnails render with a Scene Viewer's color settings, and none is open. Open one, then use Render Image."
THUMBNAIL_RENDERER_NOT_LOADED = '"%s" was not rendered because %s isn\'t loaded in this Houdini session.'

NEW_NAME_HAS_A_SLASH = '"%s" cannot be a name here: a slash divides folders.'
NEW_FOLDER_TAKEN = 'A folder named %s is already in %s.'
NEW_FOLDER_FAILED = 'The folder %s could not be made: %s'
SAVE_SCENE_TAKEN = 'A file named %s is already in %s, so the scene was not saved.'
SAVE_SCENE_FAILED = 'Houdini could not save the scene as %s: %s'

LOG_NOT_SAVED_UNEXPECTED = "The log couldn't be saved: %s"
CONVERSION_SUMMARY = "Converted %d of %d %s material(s) to %s."
NODE_CONVERTED = 'Converted "%s" to %s.'

NODE_SWAPPED = 'Converted "%s" to %s in its place.'

NODES_CONVERTED = 'Converted %d materials to %s.'

NODES_SWAPPED = 'Converted %d materials to %s in their place.'

NODE_NOT_A_MATERIAL = '"%s" is not a material Amaze can convert.'

NODE_SKIPPED_LINE = '"%s":\n  [skipped] %s'

CONVERSION_STOPPED = 'the conversion stopped, so no copy was made: %s'

SWAP_KEPT_OLD_NODE = 'not swapped: the old node is kept, and the copy is beside it'

NODE_ASSETS_IMPORT_FAILURES = "Some node assets couldn't be imported."
MATERIALS_SAVE_FAILURES = "Some materials could not be saved."
MATERIALS_IMPORT_FAILURES = "Some materials could not be imported."
LOADER_SOP_HAS_NO_FILE_PARM = "The \"%s\" SOP has no file parameter to set."
GEOMETRY_IMPORT_FAILED = "Could not import %s: %s"
HOLDER_NOT_MADE = "No %s node was made in %s: %s"
