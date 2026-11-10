"""Every dialog message; a button set puts the accepting one first. ▸p/messages-need-one-home"""

from __future__ import annotations

LIBRARY_NOT_SAVED_ANOTHER_PANEL = "This panel's library was not saved: another Amaze panel is open on a different library. Close the other panel (or reopen this one), then save again."
SECTION_UNREADABLE_SAVING_DISABLED = "Your saved %s could not be read, so Amaze has paused saving to that file to protect it; changes made now stay in memory only. Put back a recent copy with Library ▸ Check Library… in the Amaze panel."
LIBRARY_FORMAT_AHEAD_READ_ONLY = "This library was saved by a newer Amaze, so this machine opens it read-only to protect it. Update Amaze to work with it normally."
LIBRARY_WRITE_FAILED = "Amaze could not save the library: %s The change is still in memory and goes into the next save that works, but it is lost if Houdini closes first."
PALETTE_NOT_SAVED = "Amaze could not save \"%s\". Close any other Amaze panel or restart Houdini, then try again."
PALETTE_NOT_DELETED = "\"%s\" was not deleted because the colors list could not be updated. Close any other Amaze panel or restart Houdini, then try again."
SAVE_DENIED_WITH_CAUSE = "%s Cause: %s"
ASSET_NOT_DELETED_LIST_NOT_UPDATED = "\"%s\" was not deleted because the library list could not be updated. Close any other Amaze panel or restart Houdini, then try again."
EDIT_CONFLICT_KEPT_YOURS = "Someone else changed \"%s\" while you had it open.\n\nAmaze kept your version and discarded theirs."
VERSION_SWITCH_DIVERGED = "The version switch didn't finish: the material's files hold version %d but its version list still names the old one. All archived versions are still there.\n\nSwitch the version again to finish."
UNSAFE_ARCHIVE_PATHS_SKIPPED = "%d file(s) in this download tried to write outside your library folder and were skipped. Nothing outside the library was touched; the rest imported normally. If the material looks wrong, delete it and download again."
NO_LIBRARY_FOLDER_CONFIGURED = "Amaze has no library folder set. Pick one in Preferences (Amaze panel), then run Check Library again."
LIBRARY_FOLDER_UNREACHABLE = "Amaze can't reach its library folder:\n%s\nIf it's on a drive or in a synced folder, connect it and run Check Library again. If you moved the library, point Preferences at the new location."
CHECK_LIBRARY_IN_THE_PANEL = 'Amaze is open, so use Library ▸ Check Library… in the Amaze panel instead.'

CHOSEN_SAVED_COPY_CANNOT_BE_READ = "That copy of the %s list cannot be read. Try another copy."
CONFIRM_PUT_SAVED_COPY_BACK = "Put the %s list back to the copy from %s?"
SAVED_COPY_PUT_BACK_DONE = "The %s list is back to the copy from %s.%s\n\n%s"
SETTINGS_UNREADABLE_REPAIR_REPORT = "Amaze's settings couldn't be read, so Check Library can't tell which library to check.\n\nSaved copies of your settings:\n%s"
SETTINGS_MISSING_REPAIR_REPORT = "Amaze's settings file is missing, so Check Library can't tell which library to check.\n\nSaved copies of your settings:\n%s"
SETTINGS_NO_LIBRARY_REPAIR_REPORT = "Your settings have no library folder set, so Check Library can't tell which library to check.\n\nSaved copies of your settings:\n%s"
SETTINGS_COPY_LINE_UNREADABLE = "%s — this copy can't be read"
SETTINGS_UNREADABLE_NO_COPIES = "Amaze's settings couldn't be read and there's no saved copy to put back.\n\nTo start fresh, move settings.json out of this folder and open Amaze:\n\n%s"
SETTINGS_COPY_CANNOT_BE_READ = "That copy of your settings can't be read."
CONFIRM_PUT_SETTINGS_BACK = "Put your settings back to the copy from %s?"
HELP_PUT_SETTINGS_BACK = "Amaze then opens the library it pointed to at that time, with the same view.%s"
SETTINGS_NOW_SAVED_FIRST = " Your settings from now are saved next to it first — run Check Library again and it offers that copy back."
SETTINGS_PUT_BACK_DONE = "Your settings are back to the copy from %s.\n\nOpen Amaze to use them.%s"
SETTINGS_EARLIER_COPY_KEPT = " Your previous settings are kept too — run Check Library again and put back the copy from %s to go back to them."
CONFIRM_MOVE_FILES_ASIDE = "Move %s aside?"
NOTHING_MOVED_ASIDE_REASON = "Amaze moved nothing: %s."
FILES_MOVED_ASIDE_SOME_FAILED = "%s moved to Amaze's holding folder on this computer (outside your library, kept 30 days). %s could not be moved and are still in place."
FILES_MOVED_ASIDE_DONE = "%s moved to Amaze's holding folder on this computer (outside your library, kept 30 days)."
CONFIRM_MOVE_UNKNOWN_ASIDE = 'Move the files Amaze does not know aside?'

CONFIRM_SET_ASIDE_FOLDERS = 'Set aside %s in the Files section?'

CONFIRM_REMOVE_DEAD_STARS = 'Remove %s of files that are gone?'

CONFIRM_PUT_IN_UNCATEGORIZED = 'Put %s in %s?'

FOLDERS_SET_ASIDE_DONE = 'Set aside %s in the Files section. Adding a folder again brings back its comments, icons and favorites.%s'

DEAD_STARS_ALSO_REMOVED = ' Removed %s of files that are gone as well.'

DEAD_STARS_REMOVED_DONE = 'Removed %s of files that are gone.'

PUT_IN_UNCATEGORIZED_DONE = 'Put %s in %s.'

CONFIRM_ADD_UNLISTED_TO_SECTION = "Add %d unlisted %s to %s?"
SECTION_LIST_UNCHANGED_REASON = "Amaze did not change the %s list: %s."
NOTHING_CHANGED_REASON = 'Amaze changed nothing: %s.'

UNLISTED_FILES_ADDED_BACK_DONE = "%d %s restored to %s. Each came back with the name, category and tags recorded beside its files."
UNLISTED_FILES_ADDED_BACK_SOME_UNNAMED = "%d %s restored to %s.\n\n%d of them had no record beside the files: they're in the %s category, named after their file — rename them as needed."
TILE_ICON_NOT_SAVED = "The tile icon could not be saved: %s The tile keeps its previous icon."
USER_DELETE_CONFIRM = "Delete user \"%s\" from this library?"
USER_NAME_TAKEN = "A user named \"%s\" already exists in this library. Choose another name."
NO_USER_PICKED = "No user is picked for this library. Open Preferences, pick or create your user, and press Apply."
MATERIAL_VERSIONS_TURN_ON_CONFIRM = "Turn on Material Versions for this library?"
LIBRARY_SETTING_NOT_WRITTEN = "The setting could not be written to the library folder, so it was not changed."
TEST_FOLDER_NOT_PREPARED = "That folder could not be prepared:\n\n%s"
PICTURE_NOT_COPIED_TO_LIBRARY = "That picture could not be copied into the library, so it was not added."
PICTURE_COPIED_BUT_UNREADABLE = "That file was copied but couldn't be read as a picture, so it was not added."
LIBRARY_INDEX_UNREADABLE = "The library's list file could not be read. Repair puts back the newest saved copy or, if no copy reads, rebuilds the list from what each asset file remembers. Category names survive; their order and colors may not. The broken file is preserved as a backup. Open Without Library opens Amaze without touching the folder."
LIBRARY_INDEX_REPAIRED = 'The library index can be read again: %s.'

REPAIR_COULD_NOT_FIX_THE_LIST = "Repair could not fix the list: %s.\n\nAmaze will open without a library. Close Amaze and run Check Library on the Amaze shelf for details."
INDEX_UNREADABLE_AFTER_REPAIR = "The repaired list still could not be read. Amaze opens without a library; close Amaze and run Check Library on the Amaze shelf for details."
LIBRARY_INDEX_UNREADABLE_SWITCHING = "The library's list file could not be read.\n\nRepair puts back the newest saved copy or, if no copy reads, rebuilds the list from what each asset file remembers. Category names survive; their order and colors may not. The broken file is preserved as a backup.\n\nCancel leaves the folder unchanged and keeps the current library open."
REPAIR_COULD_NOT_FIX_THE_LIST_SWITCHING = "Repair could not fix the list: %s.\n\nAmaze keeps the library you have open. Check This Library looks at the one that failed and offers the fixes that apply."
INDEX_UNREADABLE_AFTER_REPAIR_SWITCHING = "The repaired list still could not be read.\n\nAmaze keeps the library you have open. Check This Library looks at the one that failed and offers the fixes that apply."
LIBRARY_INDEX_READ_NOT_PERMITTED = 'this account is not allowed to read it:\n%s\n\nThe permissions on the file, or on a folder above it, have to let this account read it.'

LIBRARY_NOT_OPENED = 'The library could not be opened because %s\n\nAmaze will open without a library.'

LIBRARY_NOT_OPENED_SWITCHING = 'The library could not be opened because %s\n\nAmaze keeps the library you have open.'

LIBRARY_LIST_NOT_LOADED = 'one of its lists could not be loaded (%s).'

STARTER_SEED_REFUSED_DIRECTORY_HELD_LIBRARY = "This folder looks like a library whose list hasn't arrived yet, so Amaze didn't set up a new one over it. If it's in a synced folder, let the sync finish and reopen Amaze. If the list is really gone, close Amaze and run Check Library on the Amaze shelf to rebuild it."
NO_FOLDER_SELECTED_TO_RELOCATE = "Select the registered folder to re-point first (\"All\" is not a real folder)."
RELOCATE_TARGET_NOT_A_FOLDER = "That location isn't a folder."
NO_LIBRARY_CONFIGURED = "Set up a library first."
PACKAGE_IMPORT_SUMMARY = "Imported %d asset(s) and %d file(s) into the Import category."
PACKAGE_NOT_READABLE = '"%s" is not a package Amaze can read.'
PACKAGE_TOO_LARGE = "This package unpacks to %s, more than the %s Amaze imports at once."
DOWNLOAD_TOO_LARGE = "This download is larger than the %s Amaze imports at once."
MATERIAL_PRESETS_FOUND = "No material presets found in: %s"
IMPORT_MATERIAL_PRESETS_FROM = "Import %d material presets from:\n%s\n\n%s\n\nPreviews aren't generated during import — select the new materials afterwards and use Update Render."
IMPORT_MATERIAL_PRESETS_FROM_RENDERING = 'Import %d material presets from:\n%s\n\n%s\n\nNote: Thumbnails are rendered in one batch once the import finishes.'

GALLERY_IMPORT_FINISHED_IMPORTED_SKIPPED = "Gallery import complete.\nImported: %d\nSkipped: %d\nFailed: %d\n\nSelect the new materials and use Update Render to render them."
GALLERY_IMPORT_FINISHED_RENDERING = 'Gallery import complete.\n\nImported: %d\nSkipped: %d\nFailed: %d\n\nTheir thumbnails are rendering now.'

GALLERY_IMPORT_INTERRUPTED = 'Gallery import stopped.\n\nImported: %d\nSkipped: %d\nFailed: %d\n\nTo render them, select the new materials and use Update Render.'

NO_LIBRARY_OPEN = "Open a library first."
AMAZE_COULD_NOT = "%d of %d items could not be imported:"
SCENE_BUILD_PARTIAL_FAILURE = "%d of %d could not be built:"
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
MATERIALS_NOT_UPDATED = "Some materials were not updated:"
MATERIAL_NOT_UPDATED_LINE = "\"%s\": %s"
UPDATE_REFUSED_GONE = "it is no longer in the library."
UPDATE_REFUSED_VERSIONS_OFF = "Material Versions is off for this library."
UPDATE_REFUSED_CHANGED_ON_DISK = "it was changed on disk since this Houdini read it. Save it as a new material, or reopen the Amaze panel to load the other version first."
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
UPDATE_LIBRARY_AVAILABLE = "Amaze v%s is available. The library will be updated to v%d."
LIBRARY_UPDATE_WARNING = "The library will be updated and won't work with Amaze versions older than %s."
LIBRARY_NEEDS_NEWER_AMAZE = "This library is version %d and needs a newer Amaze. Update Amaze to open it."
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

CHECK_LIBRARY_ONLY_A_REPORT = 'Amaze has already read this library since Houdini started, so this is only a report: open Amaze and use Library ▸ Check Library… to act on it.'

ADD_BACK_WRITES_A_NEW_LIST = ' There is no %s list in the library folder, so Amaze writes a new one with these on it.'

PICK_AN_ACTION = 'What should Amaze do?'

COLUMN_ACTION = 'Action'

PICK_LIST_TO_PUT_BACK = "Which list should Amaze put back? Each line is that list's newest saved copy."

PICK_OLDER_COPY_TO_PUT_BACK = 'Which older copy of the %s list should Amaze put back?'

PICK_SECTION_FOR_FILES = 'Which section do these %s belong in? Amaze cannot tell from the files themselves - a saved material and a saved node look the same in the folder.'

COLUMN_NEWEST_SAVED_COPIES = 'Newest saved copies'

COLUMN_OLDER_SAVED_COPIES = 'Older saved copies'

COLUMN_SECTION = 'Section'

CURRENT_LIST_UNREADABLE = 'The list you have now cannot be read at the moment, so Amaze cannot say what is in it to compare.'

CURRENT_LIST_COMPARED = 'The list you have now holds %d. Putting this copy back takes you from %d to %d: anything saved to %s since %s is not in this copy and will not be there afterwards.'

LIST_EARLIER_COPY_KEPT = 'The list you had a moment ago is still in the library folder: run Check Library again and put back the copy from %s to return to it.'

NO_EARLIER_LIST = 'There was no list here before, so there is nothing to go back to.'

BUTTON_SHOW_IN_FOLDER = 'Show in Folder'

BUTTON_REPAIR_ADD_BACK = 'Add %s Back'

BUTTON_REPAIR_PUT_COPY_BACK = 'Put a Saved Copy Back'

BUTTON_REPAIR_ADD_TO_SECTION = 'Add %s to a Section'

BUTTON_REPAIR_MOVE_ASIDE = 'Move %s Aside'

BUTTON_MOVE_ONE_UNKNOWN_ASIDE = 'Move 1 Unknown File Aside'

BUTTON_MOVE_UNKNOWN_ASIDE = 'Move %d Unknown Files Aside'

BUTTON_SET_ASIDE_FOLDERS = 'Set Aside %s'

BUTTON_REMOVE_DEAD_STARS = 'Remove %s of Missing Files'

BUTTON_PUT_IN_UNCATEGORIZED = 'Put %s in %s'

BUTTON_SHOW_HOLDING_FOLDER = 'Show Holding Folder'

BUTTON_CHOOSE_AN_ACTION = 'Choose an Action...'

BUTTON_REPAIR_CLOSE = 'Close'



TITLE_AMAZE = 'Amaze'

TITLE_CHECK_LIBRARY = 'Check Library'

TITLE_LOG_NOT_SAVED = 'Log not saved'

TITLE_LOG_SAVED = 'Log saved'

TITLE_SAVE_LOG_TO_FOLDER = 'Save Amaze log to folder'

TITLE_EMPTY_SNIPPET = 'Empty snippet'

TITLE_SAVE_TO = 'Save to %s'


BUTTONS_PUT_COPY_BACK = ('Put This Copy Back', 'Cancel')

BUTTONS_PUT_COPY_BACK_OR_OLDER = ('Put This Copy Back', 'Older Copies...', 'Cancel')

BUTTONS_MOVE_ASIDE = ('Move Them Aside', 'Cancel')

BUTTONS_SET_ASIDE = ('Set Them Aside', 'Cancel')

BUTTONS_REMOVE = ('Remove Them', 'Cancel')

BUTTONS_PUT_THEM_THERE = ('Put Them There', 'Cancel')

BUTTONS_ADD_BACK = ('Add Them Back', 'Cancel')

BUTTONS_REPAIR_OR_OPEN_WITHOUT = ('Repair', 'Open Without Library')

BUTTONS_REPAIR_OR_CANCEL = ('Repair', 'Cancel')

BUTTONS_CHECK_THIS_LIBRARY = ('Check This Library', 'Close')

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


HELP_CHECK_LIBRARY = "Check Library looks at every list and folder in your library and changes nothing until you press a button. Anything you move aside goes into Amaze's holding folder on this computer, outside your library, and is kept for 30 days."

HELP_MATERIAL_VERSIONS = "This is shared: everyone working from this library gets the same setting.\n\nWith it on, saving over an existing material keeps the previous version, and the + in the code editor keeps versions of a snippet."
HELP_DELETE_USER = 'Their favorites and registered folders are removed from this library everywhere it syncs. A machine signed in as "%s" will ask who is using the library the next time it opens. This cannot be undone.'

HELP_LOG_SAVED = 'It contains your file paths, asset and material names - check before sharing it.'

HELP_ADD_BACK = 'Each one comes back with the name, category and tags saved beside its files.%s'

HELP_PUT_SAVED_COPY_BACK = "That copy is from %s and holds %d %s. %s\n\nYour %s' own files and thumbnails are not touched either way, and the list you have now is saved in the library folder first - run Check Library again and it offers that copy back."

HELP_MOVE_FILES_ASIDE = "%s They move into Amaze's own holding folder on this computer - outside your library, so they do not sync and do not travel. Nothing is deleted today: they are kept for 30 days and named in the report, and moving one back is copying it back.\n\nEverything showing in Amaze stays.%s"

HELP_MOVE_UNLISTED = 'The files no section lists: %s.'

HELP_MOVE_LEFTOVERS = 'The files Amaze left behind and no longer needs: %s.'

HELP_MOVE_UNLISTED_LAST = ' Do this only if you have already tried putting a saved copy of a list back: if one of these files belongs to a material whose list was lost, restoring the list is what brings it back.'

HELP_MOVE_UNKNOWN_ASIDE = "These are not files Amaze made or knows: %s. They move into Amaze's holding folder on this computer, outside your library, and are kept for 30 days."

HELP_SET_ASIDE_FOLDERS = "Each folder's comments, icons and favorites are kept, and come back when the folder is added again. Its files are not touched.%s"

HELP_DEAD_STARS_GO_TOO = ' Favorites of files that are gone from a folder still on this computer are removed too.'

HELP_PUT_IN_UNCATEGORIZED = 'Each one has no category now, so it shows only under All.'

HELP_ADD_TO_SECTION = 'Each one keeps the name, category and tags recorded beside its files, and comes back where it was. Anything with no such record comes back in a new category called %s, named %s plus the start of its file name, with no renderer badge until you save it again - rename those afterwards.\n\nIf there is a saved copy of the %s list from before they went missing, putting that back instead is still the closest match. Nothing here is deleted or overwritten either way.'


SNIPPET_HAS_NO_CODE = "No code to save."
CODE_VERSION_UNREADABLE = "That version's file could not be read. The editor keeps the code it had."

SNIPPET_RUN_FAILED = "\"%s\" stopped: %s"
CONFIRM_CLEAR_THUMBNAIL_CACHE = "This deletes all cached thumbnails from disk. They regenerate as you browse."
NO_SCENE_VIEWER_FOR_THUMBNAIL = "Thumbnails render with a Scene Viewer's color settings, and none is open. Open one, then use Update Render."
THUMBNAIL_RENDERER_NOT_LOADED = '"%s" was not rendered because %s isn\'t loaded in this Houdini.'

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

NODE_ASSETS_IMPORT_FAILURES = "Some node assets couldn't be imported:"
MATERIALS_SAVE_FAILURES = "Some materials could not be saved:"
MATERIALS_IMPORT_FAILURES = "Some materials could not be imported:"
LOADER_SOP_HAS_NO_FILE_PARM = "The \"%s\" SOP has no file parameter to set."
GEOMETRY_IMPORT_FAILED = "Could not import %s: %s"
