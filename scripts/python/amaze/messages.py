"""Every dialog message; a button set puts the accepting one first. ▸p/messages-need-one-home"""

from __future__ import annotations

DATABASE_CORRUPT_READ_ONLY = "Your %s database is corrupt/unreadable, so Amaze has opened it read-only; changes made now stay in memory only. Restore a backup with Check in Preferences ▸ Library."
DATABASE_MISSING_READ_ONLY = "Your %s database is missing from the library folder, though Amaze can see it was there before. If the folder syncs, it may not have finished yet. Until it is back the database is read-only; if it does not come back, use Check in Preferences ▸ Library."
DATABASE_SHRUNK = "Your %s database holds %d %s, but its newest backup holds %d %s. If you did not remove them yourself, use Check in Preferences ▸ Library before you change anything - it can restore that backup."
LIBRARY_FORMAT_AHEAD_READ_ONLY = "This library was saved by a newer Amaze, so this machine opens it read-only to protect it. Update Amaze to work with it normally."
CONFIRM_CONVERT_LIBRARY = "This library will be converted to format 2.0. Amaze older than %s cannot open it afterwards, so update Amaze on every computer that uses this library. If the library is in a synced folder, make sure it has finished syncing before you convert."
BUTTONS_CONVERT_LIBRARY = ("Convert", "Cancel")
CONVERT_LIBRARY_PROGRESS = "Converting library to 2.0"
CONVERT_LIBRARY_DONE = "The library is converted to format 2.0."
CONVERT_LIBRARY_DONE_SOME_LEFT = "The library is converted to format 2.0. %s could not be converted and are no longer in the library. Leave their files where they are, or move them to the trash?"
BUTTONS_UNCONVERTED = ("Leave", "Move to Trash")
CONVERT_CLASSIC_NEEDS_RENDERER = "%s use the classic builder, and Amaze needs %s loaded to convert them. Move them to the trash, or cancel and start Houdini with %s?"
BUTTONS_CLASSIC_NEEDS_RENDERER = ("Move to Trash", "Cancel")
OLD_TRASH_QUESTION = "The old trash for this library holds %d files (%s) on this computer. Amaze now keeps its trash in the library's trash folder and no longer uses the old one. Delete the old trash?"
BUTTONS_OLD_TRASH = ("Delete", "Leave")
CONVERT_LIBRARY_BLOCKED ="This library cannot be converted yet: %s Use Check Library from the Amaze shelf, then open the library again."
LIBRARY_WRITE_FAILED = "Amaze could not save the library: %s The change is kept in memory and is written with the next successful save, but it is lost if Houdini closes first."
PALETTE_NOT_SAVED = "Amaze could not save \"%s\": the colors database is read-only right now. Use Check in Preferences ▸ Library, then try again."
PALETTE_NOT_DELETED = "\"%s\" was not deleted because the colors database is read-only right now. Use Check in Preferences ▸ Library, then try again."
ASSET_NOT_SAVED_DATABASE_REFUSED = "\"%s\" was not saved: its database is read-only right now, so neither its files nor its entry were written. Use Check in Preferences ▸ Library, then save again."
ASSET_NOT_DELETED_LIST_NOT_UPDATED = "\"%s\" was not deleted because its database could not be updated. Use Check in Preferences ▸ Library, then try again."
EDIT_CONFLICT_KEPT_YOURS = "Someone else changed \"%s\" while you had it open.\n\nAmaze kept your version and discarded theirs."
EDIT_CONFLICT_KEPT_YOURS_BY = "%s changed \"%s\" while you had it open.\n\nAmaze kept your version and discarded theirs."
UNSAFE_ARCHIVE_PATHS_SKIPPED = "%d file(s) in this download tried to write outside your library folder and were skipped. Nothing outside the library was touched; the rest imported normally. If the material looks wrong, delete it and download again."
NO_LIBRARY_FOLDER_CONFIGURED = "Amaze has no library folder set. Pick one in Preferences (Amaze panel), then run Check Library again."
LIBRARY_FOLDER_UNREACHABLE = "Amaze can't reach its library folder:\n%s\nIf it's on a drive or in a synced folder, connect it and run Check Library again. If you moved the library, point Preferences at the new location."
CHECK_LIBRARY_IN_THE_PANEL = 'Amaze is open, so use Check in Preferences ▸ Library instead.'

CHOSEN_SAVED_COPY_CANNOT_BE_READ = "That backup of the %s database cannot be read. Try another backup."
CONFIRM_PUT_SAVED_COPY_BACK = "Restore the %s database from the backup of %s?"
SAVED_COPY_PUT_BACK_DONE = "The %s database is restored from the backup of %s.%s\n\n%s"
SETTINGS_UNREADABLE_REPAIR_REPORT = "Amaze's settings couldn't be read, so Check Library can't tell which library to check.\n\nBackups of your settings:\n%s"
SETTINGS_MISSING_REPAIR_REPORT = "Amaze's settings file is missing, so Check Library can't tell which library to check.\n\nBackups of your settings:\n%s"
SETTINGS_NO_LIBRARY_REPAIR_REPORT = "Your settings have no library folder set, so Check Library can't tell which library to check.\n\nBackups of your settings:\n%s"
SETTINGS_COPY_LINE_UNREADABLE = "%s — this backup can't be read"
SETTINGS_UNREADABLE_NO_COPIES = "Amaze's settings couldn't be read and there's no backup to restore.\n\nTo start fresh, move settings.json out of this folder and open Amaze:\n\n%s"
CONFIRM_MOVE_FILES_ASIDE = "Move %s to the trash?"
NOTHING_MOVED_ASIDE_REASON = "Amaze moved nothing: %s."
FILES_MOVED_ASIDE_SOME_FAILED = "%s moved to the library's trash folder (deleted after 30 days). %s could not be moved and are still in place."
FILES_MOVED_ASIDE_DONE = "%s moved to the library's trash folder (deleted after 30 days)."
CONFIRM_MOVE_UNKNOWN_ASIDE = 'Move the files Amaze does not know to the trash?'

CONFIRM_SET_ASIDE_FOLDERS = 'Set aside %s in the Files section?'

CONFIRM_REMOVE_DEAD_STARS = 'Remove %s of files that are gone?'

CONFIRM_PUT_IN_UNCATEGORIZED = 'Put %s in %s?'

FOLDERS_SET_ASIDE_DONE = 'Set aside %s in the Files section. Adding a folder again brings back its comments, icons and favorites.%s'

DEAD_STARS_ALSO_REMOVED = ' Removed %s of files that are gone as well.'

DEAD_STARS_REMOVED_DONE = 'Removed %s of files that are gone.'

PUT_IN_UNCATEGORIZED_DONE = 'Put %s in %s.'

CONFIRM_RECOVER = "Recover %s?"
SECTION_LIST_UNCHANGED_REASON = "Amaze did not change the %s database: %s."
NOTHING_CHANGED_REASON = 'Amaze changed nothing: %s.'
LIBRARY_CHANGED_SINCE_CHECK = "Something changed in the library since the check. Run Check Library again."

ORPHANED_FILES_RECOVERED_DONE = "Recovered %s. Each came back with the metadata saved beside its files: name, category and tags."
ORPHANED_FILES_RECOVERED_SOME_UNNAMED = "Recovered %s.\n\n%d of them had no metadata that could be read beside the files: they are in the %s category, named %s followed by their id. Rename them as needed."
TILE_ICON_NOT_SAVED = "The tile icon could not be saved: %s The tile keeps its previous icon."
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
CONFIRM_REBUILD_DATABASE = "Rebuild the %s database from each asset's metadata?"
HELP_REBUILD_DATABASE = "The %s database is replaced by one built from the metadata saved beside each asset's files in its folder. Category names come back; their order and colors may not."
DATABASE_REBUILT_DONE = "The %s database is rebuilt from each asset's metadata: %s."
DATABASE_REBUILT_SOME_UNREAD = " The metadata of %s could not be read."
PICK_DATABASE_TO_REBUILD = "Which database should Amaze rebuild from each asset's metadata?"
LIBRARY_INDEX_READ_NOT_PERMITTED = 'this account is not allowed to read it:\n%s\n\nThe permissions on the file, or on a folder above it, have to let this account read it.'

LIBRARY_NOT_OPENED = 'The library could not be opened because %s\n\nAmaze will open without a library.'

LIBRARY_NOT_OPENED_SWITCHING = 'The library could not be opened because %s\n\nAmaze keeps the library you have open.'

LIBRARY_LIST_NOT_LOADED = 'one of its databases could not be loaded (%s).'

LIBRARY_FOLDER_NOT_EMPTY = "This folder is not empty. Pick an empty folder for a new library."
CONVERT_OLD_LIBRARY_PICK = "Convert Old Library"
CONVERT_OLD_LIBRARY_NONE = "This folder holds no older library."
CONVERT_OLD_LIBRARY_AS = "Convert as"
CONVERT_OLD_LIBRARY_NAME = "This library has no users. Enter the name its favorites and locations go to."
BUTTONS_CONVERT_OLD_LIBRARY_NAME = ("Convert", "Cancel")
CONVERT_LIBRARY_STOPPED = "The conversion stopped at a file it could not read or write:\n%s\nClose any program using the library, then convert it again to finish."
NO_FOLDER_SELECTED_TO_RELOCATE = "Select the registered folder to re-point first (\"All\" is not a real folder)."
RELOCATE_TARGET_NOT_A_FOLDER = "That location isn't a folder."
LOCATION_ALREADY_ADDED = "That location is already added."
NO_LIBRARY_CONFIGURED = "Set up a library first."
PACKAGE_IMPORT_SUMMARY = "Imported %d asset(s) and %d file(s) into the Import category."
PACKAGE_EXPORTED = "Exported %d items to %s."
PACKAGE_EXPORTED_ONE = "Exported 1 item to %s."
PACKAGE_EXPORT_EMPTY = "Nothing to export. This category is empty."
PACKAGE_NOT_SAVED = "The package could not be saved: %s"
PACKAGE_NOT_READABLE ='"%s" is not a package Amaze can read.'
PACKAGE_TOO_LARGE = "This package unpacks to %s, more than the %s Amaze imports at once."
DOWNLOAD_TOO_LARGE = "This download is larger than the %s Amaze imports at once."
MATERIAL_PRESETS_FOUND = "No material presets found in: %s"
IMPORT_MATERIAL_PRESETS_FROM = "Import %d material presets from:\n%s\n\n%s\n\nPreviews aren't generated during import — select the new materials afterwards and use Thumbnail ▸ Render Image."
IMPORT_MATERIAL_PRESETS_FROM_RENDERING = 'Import %d material presets from:\n%s\n\n%s\n\nNote: Thumbnails are rendered in one batch once the import finishes.'

GALLERY_IMPORT_FINISHED_IMPORTED_SKIPPED = "Gallery import complete.\nImported: %d\nSkipped: %d\nFailed: %d\n\nSelect the new materials and use Thumbnail ▸ Render Image to render them."
GALLERY_IMPORT_FINISHED_RENDERING = 'Gallery import complete.\n\nImported: %d\nSkipped: %d\nFailed: %d\n\nTheir thumbnails are rendering now.'

GALLERY_IMPORT_INTERRUPTED = 'Gallery import stopped.\n\nImported: %d\nSkipped: %d\nFailed: %d\n\nTo render them, select the new materials and use Thumbnail ▸ Render Image.'

NO_LIBRARY_OPEN = "Open a library first."
AMAZE_COULD_NOT = "%d of %d items could not be imported."
SCENE_BUILD_PARTIAL_FAILURE = "%d of %d could not be built."
TILE_ICON_SAVE_FAILED = "%d tile icon%s could not be saved - check that the library folder is writable."
CAPTURE_SELECT_ONE_TILE = "Select one tile to capture onto."
NO_LIBRARY_CONFIGURED_2 = "Set up a library first: open Preferences, add one under Library, press Apply."
NO_NODE_TO_SAVE = "Right-click the node or network you want to save."
RESTART_TO_FINISH_UPDATE = "Amaze was updated while Houdini was running. Restart Houdini to finish."
NODE_CANNOT_BE_SAVED = "\"%s\" can't be saved — it's not a material, color ramp, code node or network."
NODE_SAVE_FAILED_WITH_REASON = "\"%s\" could not be saved: %s"
NODE_SAVE_FAILED = "\"%s\" could not be saved."
OBJECT_HAS_NO_MATERIAL_PARM = "\"%s\" has no material parameter — imported to /mat without assigning."
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

STOCK_LOP_HELPERS_UNAVAILABLE = "Could not load Houdini's material-assignment helpers — material not imported."
NETWORK_REFUSED_MATERIAL_LIBRARY = "%s can't take a Material Library, so the material was not imported.\n\n%s"
DROPPED_MATERIAL_IMPORT_FAILED = "The dropped material could not be imported, so nothing was assigned. Other materials in the selection were still added to the library."
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
ASSET_ADDED_LIBRARY_NOT_SAVED = "\"%s\" was added, but the library could not be saved."
MATERIALS_ADDED_LIBRARY_NOT_SAVED = "%d materials were added, but the library could not be saved."
MATERIAL_NOT_UPDATED = "\"%s\" was not updated: %s"
MATERIALS_NOT_UPDATED = "Some materials were not updated."
MATERIAL_NOT_UPDATED_LINE = "\"%s\": %s"
UPDATE_REFUSED_GONE = "it is no longer in the library."
UPDATE_REFUSED_VERSIONS_OFF = "Material Versions is off for this library."
UPDATE_REFUSED_CHANGED_ON_DISK = "it was changed on disk since this session read it. Save it as a new material, or reopen the Amaze panel to load the other version first."
UPDATE_REFUSED_NOT_A_BUILDER = "the node is not a Material Builder."
SCENE_FILE_MISSING = "That scene file no longer exists: %s"
SCENE_OPEN_FAILED = "Could not open that scene: %s\n\n%s"
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

ADDON_AUTHOR = 'author: %s'

CANNOT_LOAD_HERE = "This content can't be loaded into this context."
MATERIAL_ALREADY_IN_LIBRARY = '"%s" already exists in the library.'

MATERIALS_ALREADY_IN_LIBRARY = '%d of %d dropped materials already exist in the library.'

VERSIONS_OFF_SAVES_NEW = '\n\nVersions is off for this library, so the existing material stays as it is. Saving will add a new material.'

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

STORE_RESTORE_SUMMARY = 'Restored %d, %d already present.'

NODE_HAS_NO_FILE_PARM = '%s has no file parameter to take %s'

NODE_HAS_NO_COLOR_RAMP = '%s has no color ramp to take the gradient'

LOG_SAVED_AS = 'Saved as:\n%s'

LOG_NOT_CLEARED = 'the debug log could not be cleared (%s). It is still there, and Debug Mode keeps writing to it.'

CHECK_LIBRARY_ONLY_A_REPORT = 'This Houdini session has already read this library, so this is only a report: open Amaze and use Check in Preferences ▸ Library to act on it.'

RECOVER_WRITES_A_NEW_DATABASE = ' There is no %s database in the library folder, so Amaze writes a new one with these in it.'

PICK_AN_ACTION = 'What should Amaze do?'

COLUMN_ACTION = 'Action'

PICK_LIST_TO_PUT_BACK = "Which database should Amaze restore? Each line is that database's newest backup."

PICK_OLDER_COPY_TO_PUT_BACK = 'Which older backup of the %s database should Amaze restore?'

COLUMN_NEWEST_SAVED_COPIES = 'Newest backups'

COLUMN_OLDER_SAVED_COPIES = 'Older backups'

COLUMN_SECTION = 'Section'

CURRENT_LIST_UNREADABLE = 'The database you have now cannot be read at the moment, so Amaze cannot say what is in it to compare.'

CURRENT_LIST_COMPARED = 'The database you have now holds %d. Restoring this backup takes you from %d to %d: anything saved to %s since %s is not in this backup and will not be there afterwards.'

LIST_EARLIER_COPY_KEPT = 'The database you had a moment ago is backed up in the library folder: run Check Library again and restore the backup of %s to return to it.'

NO_EARLIER_LIST = 'There was no database here before, so there is nothing to go back to.'

BUTTON_SHOW_IN_FOLDER = 'Show in Folder'

BUTTON_REPAIR_RECOVER = 'Recover %s'

BUTTON_REPAIR_PUT_COPY_BACK = 'Restore Backup'

BUTTON_REBUILD_FROM_METADATA = 'Rebuild from Metadata'

BUTTON_REPAIR_MOVE_ASIDE = 'Move %s to Trash'

BUTTON_MOVE_ONE_UNKNOWN_ASIDE = 'Move 1 Unknown File to Trash'

BUTTON_MOVE_UNKNOWN_ASIDE = 'Move %d Unknown Files to Trash'

BUTTON_SET_ASIDE_FOLDERS = 'Set Aside %s'

BUTTON_REMOVE_DEAD_STARS = 'Remove %s of Missing Files'

BUTTON_PUT_IN_UNCATEGORIZED = 'Put %s in %s'

BUTTON_SHOW_HOLDING_FOLDER = 'Show Trash'

BUTTON_CHOOSE_AN_ACTION = 'Choose an Action...'

BUTTON_REPAIR_CLOSE = 'Close'



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

CHECK_NO_FILES = '%s listed in the database %s no files.'

CHECK_IN_NO_DATABASE = '%s in %s %s in no database.'

CHECK_LEFTOVERS = "%s %s left over from Amaze's own work."

CHECK_UNKNOWN = '%s %s not known to Amaze.'

CHECK_CONFLICT_COPIES = '%s from a sync service.'

CHECK_DEAD_FAVORITES = '%s %s of %s gone.'

CHECK_DEAD_FOLDERS = '%s in the Files section %s gone.'

FIXED_RESTORED = '%s restored from %s.'

FIXED_REBUILT = "%s rebuilt from the assets' own files."

FIXED_EMPTIED = '%s start%s empty.'

CHECK_DATABASE_NO_BACKUP = 'The %s database has no backup. Fix All starts it empty.'

CONFIRM_FIX_ALL_TRASH = 'Fix All moves these to the trash. An asset named here is removed from its database.'

BUTTONS_FIX_ALL_TRASH = ('Move to Trash', 'Skip These', 'Cancel')

FIXED_RECOVERED = '%s added to the database.'

FIXED_REMOVED = '%s removed from the database.'

FIXED_TRASHED = '%s moved to the trash.'

FIXED_FAVORITES = '%s removed.'

FIXED_FOLDERS = '%s removed from the Files section.'

TITLE_LOG_NOT_SAVED = 'Log not saved'

TITLE_LOG_SAVED = 'Log saved'

TITLE_SAVE_LOG_TO_FOLDER = 'Save Amaze log to folder'

TITLE_EMPTY_SNIPPET = 'Empty snippet'

TITLE_SAVE_TO = 'Save to %s'


BUTTONS_PUT_COPY_BACK = ('Restore', 'Cancel')

BUTTONS_PUT_COPY_BACK_OR_OLDER = ('Restore', 'Older Backups...', 'Cancel')

BUTTONS_MOVE_ASIDE = ('Move to Trash', 'Cancel')

BUTTONS_SET_ASIDE = ('Set Them Aside', 'Cancel')

BUTTONS_REMOVE = ('Remove Them', 'Cancel')

BUTTONS_PUT_THEM_THERE = ('Put Them There', 'Cancel')

BUTTONS_RECOVER = ('Recover', 'Cancel')

BUTTONS_REPAIR_OR_OPEN_WITHOUT = ('Repair', 'Open Without Library')

BUTTONS_REPAIR_OR_CANCEL = ('Repair', 'Cancel')

BUTTONS_REBUILD = ('Rebuild', 'Cancel')

BUTTONS_IMPORT = ('Import', 'Cancel')

BUTTONS_DELETE = ('Delete', 'Cancel')

BUTTONS_DELETE_USER = ('Delete User', 'Cancel')

BUTTONS_OPEN_PREFERENCES = ('Open Preferences', 'Close')

BUTTONS_SHOW_IN_FOLDER = (BUTTON_SHOW_IN_FOLDER, 'Close')

BUTTONS_TURN_ON = ('Turn On', 'Cancel')

BUTTONS_INSTALL_UPDATE = ('Install Update', 'Later')

BUTTONS_CONTINUE = ('Continue', 'Cancel')

BUTTONS_UPDATE_AMAZE = ('Update Amaze', 'Cancel')

BUTTONS_SAVE_VERSION_OR_NEW = ('Save Version', 'Save New', 'Cancel')

BUTTONS_SAVE_NEW = ('Save New', 'Cancel')


HELP_CHECK_LIBRARY = "Check Library looks at every database and folder in your library and changes nothing until you press a button. Files you move to the trash go into the library's trash folder and are deleted after 30 days."

HELP_MATERIAL_VERSIONS = "This is shared: everyone working from this library gets the same setting.\n\nWith it on, saving over an existing material keeps the previous version, and the + in the code editor keeps versions of a snippet."
HELP_DELETE_USER = 'Their favorites and registered folders are removed from this library everywhere it syncs. A machine signed in as "%s" will ask who is using the library the next time it opens. This cannot be undone.'

HELP_LOG_SAVED = 'It contains your file paths, asset and material names - check before sharing it.'

HELP_PUT_SAVED_COPY_BACK = "That backup is from %s and holds %d %s. %s\n\nYour %s' own files and thumbnails are not touched either way, and the database you have now is backed up in the library folder first - run Check Library again and it offers that backup."

HELP_MOVE_FILES_ASIDE = "%s They move into the library's trash folder and are deleted after 30 days. To restore one before then, copy it back into the library.\n\nEverything showing in Amaze stays.%s"

HELP_MOVE_UNLISTED = 'The orphaned files: %s.'

HELP_MOVE_LEFTOVERS = 'The files Amaze left behind and no longer needs: %s.'

HELP_MOVE_UNLISTED_LAST = ' Do this only if you have already tried restoring a backup of a database: if one of these files belongs to a material whose database was lost, restoring the database is what brings it back.'

HELP_MOVE_UNKNOWN_ASIDE = "These are not files Amaze made or knows: %s. They move into the library's trash folder and are deleted after 30 days."

HELP_SET_ASIDE_FOLDERS = "Each folder's comments, icons and favorites are kept, and come back when the folder is added again. Its files are not touched.%s"

HELP_DEAD_STARS_GO_TOO = ' Favorites of files that are gone from a folder still on this computer are removed too.'

HELP_PUT_IN_UNCATEGORIZED = 'Each one has no category now, so it shows only under All.'

HELP_RECOVER = 'Each one goes in the database of the folder its files are in: the materials folder in Materials, the nodes folder in Nodes. Each keeps the metadata saved beside its files: name, category and tags. One whose metadata cannot be read is recovered in a category called %s, named %s followed by its id, with no renderer badge until you save it again.%s\n\nIf there is a backup of a database from before they went missing, restoring that instead is still the closest match. Nothing here is deleted or overwritten either way.'


SNIPPET_HAS_NO_CODE = "No code to save."
CODE_VERSION_UNREADABLE = "That version's file could not be read. The editor keeps the code it had."

SNIPPET_RUN_FAILED = "\"%s\" stopped: %s"
CONFIRM_CLEAR_THUMBNAIL_CACHE = "This deletes all cached thumbnails from disk. They regenerate as you browse."
NO_SCENE_VIEWER_FOR_THUMBNAIL = "Thumbnails render with a Scene Viewer's color settings, and none is open. Open one, then use Thumbnail ▸ Render Image."
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

NODE_ASSETS_IMPORT_FAILURES = "Some node assets couldn't be imported."
MATERIALS_SAVE_FAILURES = "Some materials could not be saved."
MATERIALS_IMPORT_FAILURES = "Some materials could not be imported."
LOADER_SOP_HAS_NO_FILE_PARM = "The \"%s\" SOP has no file parameter to set."
GEOMETRY_IMPORT_FAILED = "Could not import %s: %s"
