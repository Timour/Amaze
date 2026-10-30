"""EVERY MESSAGE AMAZE SHOWS IN A DIALOG, in ONE document - `hou.ui.displayMessage` and `debug.alert` alike, so a wording change is one edit here and never a hunt through eighteen modules. Keyed by NAME, never by a line number, because a line number rots on the next edit - grep the name for its call sites. In a BUTTON SET the FIRST word is the accepting one. ▸p/messages-need-one-home ▸archive/messages.py"""

from __future__ import annotations

LIBRARY_NOT_SAVED_ANOTHER_PANEL = 'The library was not saved because another Amaze panel is currently linked to a different library.\n\nClose the other panel, or reopen this one, and saving will resume normally.'

SECTION_UNREADABLE_SAVING_DISABLED = 'Your saved %s could not be read, so Amaze has disabled saving to avoid overwriting them.\n\nTo resolve this, close Houdini and restore a recent backup using the Repair tool on the Amaze shelf.'

LIBRARY_FORMAT_AHEAD_READ_ONLY = 'This library was saved by a newer version of Amaze. To prevent data loss, it has been opened in read-only mode. Update Amaze to restore full functionality.'

LIBRARY_WRITE_FAILED = 'The library could not be saved — %s\n\nThis change is still in memory and will be included in the next successful save, but it is not yet on disk and will not persist if Houdini is closed.'

PALETTE_NOT_SAVED = 'Amaze was unable to save "%s".\n\nTo resolve this, close any other Amaze panel, or restart Houdini, and then try again.'

PALETTE_NOT_DELETED = '"%s" was not deleted because Amaze could not update your colors.\n\nTo resolve this, close any other Amaze panel, or restart Houdini, and then try again.'

SAVE_DENIED_WITH_CAUSE = '%s\n\nThis happened because %s.'

ASSET_FILES_WRITTEN_BUT_LIST_NOT_UPDATED = '"%s" was written to disk, but Amaze could not update the library index.\n\nThe item will not appear in the grid until the index is updated.\n\nTo resolve this, restart Houdini and run Repair Library from the Amaze shelf.'

ASSET_NOT_SAVED_LIST_NOT_UPDATED = '"%s" was not saved because Amaze could not update the library index.\n\nRestart Houdini and try saving again.'

ASSET_NOT_DELETED_LIST_NOT_UPDATED = '"%s" was not deleted because Amaze could not update the library index.\n\nClose any other Amaze panels or restart Houdini, then try again.'

EDIT_CONFLICT_KEPT_YOURS = 'Someone else changed "%s" while you had it open, and you both edited the same thing.\n\nAmaze kept your version and discarded theirs.'

ASSET_CHANGED_ON_DISK_SINCE_LOAD ='Another user has updated "%s" since this session loaded it, so Amaze did not overwrite their version.\n\nYou can save it as a new material, or reopen the Amaze panel to load their version first.'

VERSION_SWITCH_DIVERGED = "The version switch did not finish: the material's files hold version %d, but its version list still names the previous one. Every archived version is still there.\n\nSwitch the version again to finish."

UNSAFE_ARCHIVE_PATHS_SKIPPED = '%d file(s) in this download attempted to write outside your library folder and were skipped.\n\nNo data outside your library was affected. The remainder of the material was downloaded successfully.\n\nThis typically indicates a malformed package. If the material appears incorrect, delete it and download it again.'

NO_LIBRARY_FOLDER_CONFIGURED = 'No library folder has been configured for Amaze.\n\nTo resolve this, open Amaze, select a library folder in Preferences, and then run Repair again.'

LIBRARY_FOLDER_UNREACHABLE = 'Amaze cannot reach the library folder it is set to use:\n\n%s\n\nIf it is on a drive or in a synced folder, connect it and run Repair again. If you moved the library, open Amaze and point Preferences at the new location.'

AMAZE_OPEN_STOPS_REPAIR = 'Amaze is open, so Repair stopped before reading anything.\n\nAn open Amaze saves the library while you work. Quit Houdini, start it again, and run Repair before you open Amaze.'

CHOSEN_SAVED_COPY_CANNOT_BE_READ = 'That copy of the %s list cannot be read.'

CONFIRM_PUT_SAVED_COPY_BACK = 'Put the %s list back to the copy from %s?'

SAVED_COPY_PUT_BACK_DONE = 'The %s list is back to the copy from %s.\n\nOpen Amaze to look at it. %s'

SETTINGS_UNREADABLE_REPAIR_REPORT = 'Your Amaze settings could not be read, so Repair cannot tell which library to look at.\n\nSaved copies of your settings:\n%s'

SETTINGS_MISSING_REPAIR_REPORT = 'Your Amaze settings file is missing, so Repair cannot tell which library to look at.\n\nSaved copies of your settings:\n%s'

SETTINGS_NO_LIBRARY_REPAIR_REPORT = 'Your Amaze settings have no library folder set, so Repair cannot tell which library to look at.\n\nSaved copies of your settings:\n%s'

SETTINGS_COPY_LINE_UNREADABLE = '%s - this copy cannot be read'

SETTINGS_UNREADABLE_NO_COPIES = 'Your Amaze settings could not be read, and there is no saved copy of them to put back.\n\nTo start again with new settings, move settings.json out of this folder and open Amaze:\n\n%s'

SETTINGS_COPY_CANNOT_BE_READ = 'That copy of your settings cannot be read.'

CONFIRM_PUT_SETTINGS_BACK = 'Put your Amaze settings back to the copy from %s?'

HELP_PUT_SETTINGS_BACK = 'Amaze then opens the library it was set to at that time, with the view it had.%s'

SETTINGS_NOW_SAVED_FIRST = ' The settings you have now are saved beside them first - run Repair again and it offers that copy back.'

SETTINGS_PUT_BACK_DONE = 'Your Amaze settings are back to the copy from %s.\n\nOpen Amaze to use them.%s'

SETTINGS_EARLIER_COPY_KEPT = ' The settings you had a moment ago are kept too: run Repair again and put back the copy from %s to return to them.'

CONFIRM_MOVE_FILES_ASIDE = 'Move %s aside?'

NOTHING_MOVED_ASIDE_REASON = 'Amaze moved nothing: %s.'

FILES_MOVED_ASIDE_SOME_FAILED = "%s moved into Amaze's holding folder on this computer, outside your library, where they are kept for 30 days.\n\n%s could not be moved and remain in place."

FILES_MOVED_ASIDE_DONE = "%s moved into Amaze's holding folder on this computer, outside your library, where they are kept for 30 days.\n\nClean Library will now run again."

CONFIRM_ADD_UNLISTED_TO_SECTION = 'Add %d unlisted %s to %s?'

SECTION_LIST_UNCHANGED_REASON = 'Amaze did not change the %s list: %s.'

UNLISTED_FILES_ADDED_BACK_DONE = '%d %s were restored to %s.\n\nOpen Amaze to review them. Each one came back with the name, category, and tags recorded beside its files.'

UNLISTED_FILES_ADDED_BACK_SOME_UNNAMED = '%d %s were restored to %s.\n\nOpen Amaze to review them. %d of them had no record beside the files: those are in the %s category, named after their file, and ready to be renamed.'

TILE_ICON_NOT_SAVED = 'Your tile icon could not be saved.\n\nNo other data has been lost — only this icon selection. The tile will retain its previous icon.\n\nThis occurred because %s.'

USER_DELETE_CONFIRM = 'Delete user "%s" from this library?'

USER_NAME_TAKEN = 'A user named "%s" is already in this library. Choose another name.'

NO_USER_PICKED = 'No user is picked for this library. Open Preferences, pick your user or create one, and press Apply.'

MATERIAL_VERSIONS_TURN_ON_CONFIRM = 'Enable Versions for this library?'

LIBRARY_SETTING_NOT_WRITTEN = 'The setting could not be written to the library folder and was not changed.'

TEST_FOLDER_NOT_PREPARED = 'The folder could not be prepared:\n\n%s'

PICTURE_NOT_COPIED_TO_LIBRARY = 'That picture could not be copied into your library, so it was not added. Nothing has been changed.'

PICTURE_COPIED_BUT_UNREADABLE = 'That file was copied but could not be shown as a picture, so it was not added.'

LIBRARY_INDEX_UNREADABLE = "The library index could not be read.\n\nRepair will restore the most recent backup. If no backup is available, the index will be rebuilt from each asset's embedded metadata. Category names are preserved, but their order and colors may change during a rebuild. The corrupted file is retained as a backup in either case.\n\nOpen Without Library leaves the folder unchanged."

REPAIR_COULD_NOT_FIX_THE_LIST = 'Repair was unable to restore the index: %s.\n\nAmaze will open without a library. For more details, use the Repair tool on the Amaze shelf.'

INDEX_UNREADABLE_AFTER_REPAIR = 'The repaired index still could not be read.\n\nAmaze will open without a library. For more details, use the Repair tool on the Amaze shelf.'

LIBRARY_INDEX_UNREADABLE_SWITCHING = "The library index could not be read.\n\nRepair will restore the most recent backup. If no backup is available, the index will be rebuilt from each asset's embedded metadata. Category names are preserved, but their order and colors may change during a rebuild. The corrupted file is retained as a backup in either case.\n\nCancel leaves the folder unchanged and keeps the library you have open."

REPAIR_COULD_NOT_FIX_THE_LIST_SWITCHING = 'Repair was unable to restore the index: %s.\n\nAmaze keeps the library you have open. For more details, use the Repair tool on the Amaze shelf.'

INDEX_UNREADABLE_AFTER_REPAIR_SWITCHING = 'The repaired index still could not be read.\n\nAmaze keeps the library you have open. For more details, use the Repair tool on the Amaze shelf.'

LIBRARY_INDEX_READ_NOT_PERMITTED = 'this account is not allowed to read it:\n%s\n\nThe permissions on the file, or on a folder above it, have to let this account read it.'

LIBRARY_NOT_OPENED = 'The library could not be opened because %s\n\nAmaze will open without a library.'

LIBRARY_NOT_OPENED_SWITCHING = 'The library could not be opened because %s\n\nAmaze keeps the library you have open.'

LIBRARY_LIST_NOT_LOADED = 'one of its lists could not be loaded (%s).'

STARTER_SEED_REFUSED_DIRECTORY_HELD_LIBRARY = 'This folder looks like a library whose list has not arrived yet, so Amaze did not set up a new one over it.\n\nIf it lives in a synced folder, let the sync finish and reopen Amaze. If the list really is gone, run Repair Library from the Amaze shelf to rebuild it.'

NO_FOLDER_SELECTED_TO_RELOCATE = 'Select the registered folder to re-point first ("All" is not a real folder).'

RELOCATE_TARGET_NOT_A_FOLDER = 'The specified location does not exist as a folder.'

NO_LIBRARY_CONFIGURED = 'Configure a library first.'

PACKAGE_IMPORT_SUMMARY = 'Imported %d asset(s) and %d file(s) into the Import category.'

MATERIAL_PRESETS_FOUND = 'No material presets were found in: %s'

IMPORT_MATERIAL_PRESETS_FROM = 'Import %d material presets from:\n%s\n\n%s\n\nNote: Thumbnails are not generated during import. After importing, select the new materials and use Update Render.'

IMPORT_MATERIAL_PRESETS_FROM_RENDERING = 'Import %d material presets from:\n%s\n\n%s\n\nNote: Thumbnails are rendered in one batch once the import finishes.'

GALLERY_IMPORT_FINISHED_IMPORTED_SKIPPED = 'Gallery import complete.\n\nImported: %d\nSkipped: %d\nFailed: %d\n\nTo render them, select the new materials and use Update Render.'

GALLERY_IMPORT_FINISHED_RENDERING = 'Gallery import complete.\n\nImported: %d\nSkipped: %d\nFailed: %d\n\nTheir thumbnails are rendering now.'

GALLERY_IMPORT_INTERRUPTED = 'Gallery import stopped.\n\nImported: %d\nSkipped: %d\nFailed: %d\n\nTo render them, select the new materials and use Update Render.'

NO_LIBRARY_OPEN = 'Open a library first.'

CLEAN_LIBRARY_CONFIRM = 'Clean Library?'

AMAZE_COULD_NOT = '%d of %d items could not be imported:\n\n%s'

SCENE_BUILD_PARTIAL_FAILURE = '%d of %d items could not be built:\n\n%s'

TILE_ICON_SAVE_FAILED = '%d tile icon%s could not be saved. Verify that the library folder is writable.'

CAPTURE_SELECT_ONE_TILE = 'Select one tile to capture onto.'

NO_LIBRARY_CONFIGURED_2 = 'Configure a library first. Open Preferences, add one under Library and press Apply.'

NO_NODE_TO_SAVE = 'To save, right-click the node or network you want to keep.'

RESTART_TO_FINISH_UPDATE = 'Amaze was updated while Houdini was running. Restart Houdini to finish the update.'

NODE_CANNOT_BE_SAVED = '"%s" cannot be saved. It is not a material, a color ramp, a code node or a network.'

NODE_SAVE_FAILED_WITH_REASON = '"%s" could not be saved: %s'

NODE_SAVE_FAILED = '"%s" could not be saved.'

OBJECT_HAS_NO_MATERIAL_PARM = '"%s" does not have a material parameter. The material was imported to /mat but was not assigned.'

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

STOCK_LOP_HELPERS_UNAVAILABLE = "Could not load Houdini's material-assignment helpers. The material was not imported."

NETWORK_REFUSED_MATERIAL_LIBRARY = 'Amaze: %s cannot take a Material Library, so the material was not imported.\n\n%s'

DROPPED_MATERIAL_IMPORT_FAILED = 'The dropped material could not be imported and was not assigned. The remaining selected items were added to the library.'

MATERIAL_ASSIGN_FAILED = 'The material was imported, but assignment failed: %s'

NO_MATERIAL_DESTINATION_NETWORK = 'Unable to create the material. Open a LOP or /mat network first.'

MATERIAL_GENERATION_FAILED = 'Generation failed. See the debug log for details.'

GENERATED_MATERIAL_MOVE_FAILED = 'Amaze: the generated material could not be moved into %s.'

GENERATED_MATERIAL_NOT_REGISTERED = '"%s" was created in %s, but no material entry references it. Check the library node\'s material list.'

MATERIAL_GENERATION_ERROR = 'Material generation failed (%s).'

NO_MATERIAL_SELECTED = 'No material selected.'

MATERIAL_UPDATE_FAILED = 'Update failed. The library material was not modified.'

SCENE_FILE_MISSING = 'That scene file is no longer there:\n%s'

SCENE_OPEN_FAILED = 'Could not open that scene:\n%s\n\n%s'

LIBRARY_PATH_INVALID = 'The selected path is not valid. Choose a library folder.'

LIBRARY_LIST_FULL = 'The Library list holds %d libraries. Remove one in Manage to add another.'

TITLE_CHOOSE_LIBRARY_FOLDER = 'Choose a folder for your Amaze library'

IMPORTED_MATERIAL_MAY_NOT_APPEAR = '"%s" was imported into %s but may not appear as a material: %s.'

MATERIAL_FAILED_TO_IMPORT = '"%s" failed to import.'

NO_NODES_SELECTED_TO_SAVE = 'No nodes are selected — nothing to save.'

NETWORK_EMPTY_NOTHING_TO_SAVE = 'The network is empty — nothing to save.'

OCIO_NOT_SET = 'Configure $OCIO first.'

NODE_IS_NOT_A_MATERIAL_BUILDER = 'The selected node is not a Material Builder.'

PANEL_NOT_OPEN = 'Open the %s panel first.'

AMAZE_NOT_IMPORTABLE = 'Amaze is not importable from this session (%s).\n\nCheck that $AMAZE points at the install and that Houdini was restarted after it changed.'

NO_RELEASE_TO_INSTALL = 'There is no release to install. Check for updates first.'

INSTALL_LOCATION_UNKNOWN = 'Amaze cannot tell where it is installed, so it cannot replace itself. Check that $AMAZE points at the install.'

UPDATE_OFFER = '%s\n\nRestart Houdini after installing.'

UPDATE_LIBRARY_AVAILABLE = 'Amaze v%s is available. The library will be updated to v%d.'

LIBRARY_UPDATE_WARNING = 'Your library will be updated and not compatible with Amaze versions lower than %s.'

LIBRARY_NEEDS_NEWER_AMAZE = 'This library is version %d, which needs a newer Amaze. Update Amaze to open it.'

UPDATE_INSTALLED = 'Amaze %s is installed. Restart Houdini to use it.'

UPDATE_FAILED_UNEXPECTED = 'The update could not be installed (%s).'

ADDONS_NONE = 'No add-ons are installed. Check for Updates finds them in the Amaze store.'

ADDONS_UP_TO_DATE = 'Every add-on is up to date.'

ADDONS_AVAILABLE = 'Available: %s.'

ADDONS_INSTALLED = 'Installed. Restart Houdini to load %s.'

ADDONS_TURNED = 'Restart Houdini to turn %s %s.'

ADDONS_STORE_UNREACHABLE = 'The Amaze store could not be reached (%s).'

ADDONS_LOCATION_UNKNOWN = 'Amaze cannot tell where it is installed, so it cannot install add-ons. Check that $AMAZE points at the install.'

ADDON_VERSION = 'version %s'

ADDON_AUTHOR = 'author: %s'



TITLE_AMAZE = 'Amaze'

TITLE_AMAZE_REPAIR = 'Amaze Repair'

TITLE_LOG_NOT_SAVED = 'Amaze — Log not saved'

TITLE_EMPTY_SNIPPET = 'Empty snippet'


BUTTONS_PUT_COPY_BACK = ('Put This Copy Back', 'Cancel')

BUTTONS_PUT_COPY_BACK_OR_OLDER = ('Put This Copy Back', 'Older Copies...', 'Cancel')

BUTTONS_MOVE_ASIDE = ('Move Them Aside', 'Cancel')

BUTTONS_ADD_BACK = ('Add Them Back', 'Cancel')

BUTTONS_REPAIR_OR_OPEN_WITHOUT = ('Repair', 'Open Without Library')

BUTTONS_REPAIR_OR_CANCEL = ('Repair', 'Cancel')

BUTTONS_IMPORT = ('Import', 'Cancel')

BUTTONS_CLEAN_LIBRARY = ('Clean Library', 'Cancel')

BUTTONS_DELETE = ('Delete', 'Cancel')

BUTTONS_DELETE_USER = ('Delete User', 'Cancel')

BUTTONS_OPEN_PREFERENCES = ('Open Preferences', 'Close')

BUTTONS_TURN_ON = ('Turn On', 'Cancel')

BUTTONS_INSTALL_UPDATE = ('Install Update', 'Later')

BUTTONS_CONTINUE = ('Continue', 'Cancel')

BUTTONS_UPDATE_AMAZE = ('Update Amaze', 'Cancel')


HELP_CLEAN_LIBRARY = "Files that nothing in your library uses move into Amaze's holding folder on this computer, outside your library, where they are kept for 30 days. Materials and saved networks whose files are missing stay, and the summary names them.\n\nFile locations whose folder is gone are removed, with their labels, colors, comments, favorites and icons. Favorites of missing files are removed too. This part cannot be undone. Locations and favorites on a drive that is not connected stay."

HELP_MATERIAL_VERSIONS = 'This applies to everyone who opens this library, on every machine, because it is stored with the library rather than in your preferences.\n\nWith it on, saving over an existing material keeps the previous version instead of replacing it, and the + in the code editor keeps versions of a snippet.'


SNIPPET_HAS_NO_CODE = 'There is no code to save.'
CODE_VERSION_UNREADABLE = "That version's file could not be read. The editor keeps the code it had."

SNIPPET_RUN_FAILED = '"%s" stopped: %s'

CONFIRM_CLEAR_THUMBNAIL_CACHE = 'This deletes all cached image and geometry thumbnails from disk. They will regenerate as you browse.'

NO_SCENE_VIEWER_FOR_THUMBNAIL = "Amaze renders thumbnails with a Scene Viewer's color settings, and no Scene Viewer is open. Open one, then use Update Render."

THUMBNAIL_RENDERER_NOT_LOADED = '"%s" was not rendered because %s isn\'t loaded in this Houdini.'

LOG_NOT_SAVED_UNEXPECTED = 'The log could not be saved. Unexpected error: %s'


CONVERSION_SUMMARY = 'Converted %d of %d %s material(s) to %s.\n\n%s'

NODE_ASSETS_IMPORT_FAILURES = 'Some node assets could not be imported:\n\n%s'

MATERIALS_SAVE_FAILURES = 'Some materials could not be saved:\n\n%s'

MATERIALS_IMPORT_FAILURES = 'Some materials could not be imported:\n\n%s'

CLEANUP_SUMMARY = 'Library cleanup:\n\n%s'

LOADER_SOP_HAS_NO_FILE_PARM = 'The "%s" SOP has no file parameter to set.'

GEOMETRY_IMPORT_FAILED = 'Could not import %s: %s'
