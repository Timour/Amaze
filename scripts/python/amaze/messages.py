"""EVERY MESSAGE AMAZE SHOWS IN A DIALOG, in ONE document - `hou.ui.displayMessage` and `debug.alert` alike, so a wording change is one edit here and never a hunt through eighteen modules. Keyed by NAME, never by a line number, because a line number rots on the next edit - grep the name for its call sites. In a BUTTON SET the FIRST word is the accepting one. ▸p/messages-need-one-home ▸archive/messages.py"""

from __future__ import annotations

LIBRARY_NOT_SAVED_ANOTHER_PANEL = 'The library was not saved because another Amaze panel is currently linked to a different library.\n\nClose the other panel, or reopen this one, and saving will resume normally.'

SECTION_UNREADABLE_SAVING_DISABLED = 'Your saved %s could not be read, so Amaze has disabled saving to avoid overwriting them.\n\nTo resolve this, close Houdini and restore a recent backup using the Repair tool on the Amaze shelf.'

LIBRARY_FORMAT_AHEAD_READ_ONLY = 'This library was saved by a newer version of Amaze. To prevent data loss, it has been opened in read-only mode. Update Amaze to restore full functionality.'

LIBRARY_WRITE_FAILED = 'The library could not be saved - %s\n\nThis change is still in memory and will be included in the next successful save, but it is not yet on disk and will not persist if Houdini is closed.'

PALETTE_NOT_SAVED = 'Amaze was unable to save "%s".\n\nTo resolve this, close any other Amaze panel, or restart Houdini, and then try again.'

PALETTE_NOT_DELETED = '"%s" was not deleted because Amaze could not update your colors.\n\nTo resolve this, close any other Amaze panel, or restart Houdini, and then try again.'

SAVE_DENIED_WITH_CAUSE = '%s\n\nThis happened because %s'

ASSET_FILES_WRITTEN_BUT_LIST_NOT_UPDATED = '"%s" was written to disk, but Amaze could not update the library index.\n\nThe item will not appear in the grid until the index is updated.\n\nTo resolve this, restart Houdini and run Repair Library from the Amaze shelf.'

ASSET_NOT_SAVED_LIST_NOT_UPDATED = '"%s" was not saved because Amaze could not update the library index.\n\nRestart Houdini and try saving again.'

ASSET_NOT_DELETED_LIST_NOT_UPDATED = '"%s" was not deleted because Amaze could not update the library index.\n\nClose any other Amaze panels or restart Houdini, then try again.'

CLEANUP_FOUND_NOTHING_TO_CLEAN = 'Library cleanup finished: nothing to clean.'

ASSET_CHANGED_ON_DISK_SINCE_LOAD = 'Another user has updated "%s" since this session loaded it, so Amaze did not overwrite their version.\n\nYou can save it as a new material, or reopen the Amaze panel to load their version first.'

VERSION_SWITCH_DIVERGED = "The version switch did not finish: the material's files hold version %d, but its version list still names the previous one. Every archived version is still there.\n\nSwitch the version again to finish."

UNSAFE_ARCHIVE_PATHS_SKIPPED = '%d file(s) in this download attempted to write outside your library folder and were skipped.\n\nNo data outside your library was affected. The remainder of the material was downloaded successfully.\n\nThis typically indicates a malformed package. If the material appears incorrect, delete it and download it again.'

NO_LIBRARY_FOLDER_CONFIGURED = 'No library folder has been configured for Amaze.\n\nTo resolve this, open Amaze, select a library folder in Preferences, and then run Repair again.'

LIBRARY_FOLDER_UNREACHABLE = 'Amaze cannot reach the library folder it is set to use:\n\n%s\n\nIf it is on a drive or in a synced folder, connect it and run Repair again. If you moved the library, open Amaze and point Preferences at the new location.'

AMAZE_OPEN_STOPS_REPAIR = 'Amaze is open, so Repair stopped before reading anything.\n\nAn open Amaze saves the library while you work. Quit Houdini, start it again, and run Repair before you open Amaze.'

CHOSEN_SAVED_COPY_CANNOT_BE_READ = 'That copy of the %s list cannot be read.'

CONFIRM_PUT_SAVED_COPY_BACK = 'Put the %s list back to the copy from %s?'

SAVED_COPY_PUT_BACK_DONE = 'The %s list is back to the copy from %s.\n\nOpen Amaze to look at it. %s'

CONFIRM_MOVE_FILES_ASIDE = 'Move %s aside?'

NOTHING_MOVED_ASIDE_REASON = 'Amaze moved nothing: %s.'

FILES_MOVED_ASIDE_SOME_FAILED = "%s moved into Amaze's holding folder on this computer, outside your library, where they are kept for 30 days.\n\n%s could not be moved and remain in place."

FILES_MOVED_ASIDE_DONE = "%s moved into Amaze's holding folder on this computer, outside your library, where they are kept for 30 days.\n\nClean Library will now run again."

CONFIRM_ADD_UNLISTED_TO_SECTION = 'Add %d unlisted %s to %s?'

SECTION_LIST_UNCHANGED_REASON = 'Amaze did not change the %s list: %s.'

UNLISTED_FILES_ADDED_BACK_DONE = '%d %s were restored to %s.\n\nOpen Amaze to review them. They are in the %s category and ready to be renamed.'

TILE_ICON_NOT_SAVED = 'Your tile icon could not be saved.\n\nNo other data has been lost — only this icon selection. The tile will retain its previous icon.\n\nThis occurred because %s'

USER_DELETE_CONFIRM = 'Delete user "%s" from this library?'

MATERIAL_VERSIONS_TURN_ON_CONFIRM = 'Enable Material Versions for this library?'

LIBRARY_SETTING_NOT_WRITTEN = 'The setting could not be written to the library folder and was not changed.'

TEST_FOLDER_NOT_PREPARED = 'The folder could not be prepared:\n\n%s'

PICTURE_NOT_COPIED_TO_LIBRARY = 'That picture could not be copied into your library, so it was not added. Nothing has been changed.'

PICTURE_COPIED_BUT_UNREADABLE = 'That file was copied but could not be shown as a picture, so it was not added.'

LIBRARY_INDEX_UNREADABLE = "The library index could not be read.\n\nRepair will restore the most recent backup. If no backup is available, the index will be rebuilt from each asset's embedded metadata. Category names are preserved, but their order and colors may change during a rebuild. The corrupted file is retained as a backup in either case.\n\nOpen Without Library leaves the folder unchanged."

REPAIR_COULD_NOT_FIX_THE_LIST = 'Repair was unable to restore the index: %s.\n\nAmaze will open without a library. For more details, use the Repair tool on the Amaze shelf.'

INDEX_UNREADABLE_AFTER_REPAIR = 'The repaired index still could not be read.\n\nAmaze will open without a library. For more details, use the Repair tool on the Amaze shelf.'

STARTER_SEED_REFUSED_DIRECTORY_HELD_LIBRARY = 'This folder looks like a library whose list has not arrived yet, so Amaze did not set up a new one over it.\n\nIf it lives in a synced folder, let the sync finish and reopen Amaze. If the list really is gone, run Repair Library from the Amaze shelf to rebuild it.'

NO_FOLDER_SELECTED_TO_RELOCATE = 'Select the registered folder to re-point first ("All" is not a real folder).'

RELOCATE_TARGET_NOT_A_FOLDER = 'The specified location does not exist as a folder.'

NO_LIBRARY_CONFIGURED = 'Please configure a library first.'

PACKAGE_IMPORT_SUMMARY = 'Imported %d asset(s) and %d file(s) into the Import category.'

MATERIAL_PRESETS_FOUND = 'No material presets were found in: %s'

IMPORT_MATERIAL_PRESETS_FROM = 'Import %d material presets from:\n%s\n\n%s\n\nNote: Thumbnails are not generated during import. After importing, select the new materials and use Update Preview.'

GALLERY_IMPORT_FINISHED_IMPORTED_SKIPPED = 'Gallery import complete.\n\nImported: %d\nSkipped: %d\nFailed: %d\n\nTo generate previews, select the new materials and use Update Preview.'

NO_LIBRARY_OPEN = 'Please open a library first.'

CLEAN_LIBRARY_CONFIRM = 'Clean Library?'

AMAZE_COULD_NOT = '%d of %d items could not be imported:\n\n%s'

SCENE_BUILD_PARTIAL_FAILURE = '%d of %d items could not be built:\n\n%s'

TILE_ICON_SAVE_FAILED = '%d tile icon%s could not be saved. Please verify that the library folder is writable.'

NO_LIBRARY_CONFIGURED_2 = 'Please configure a library first. Open Preferences and select one under Library Path.'

NO_NODE_WITH_CODE_SELECTED = 'To save a snippet, right-click a wrangle or other node that has a code parameter.'

NODE_HAS_NO_CODE_PARM = '"%s" does not have a code or snippet parameter.'

NO_NETWORK_SELECTED_TO_SAVE = 'To save, right-click the network or the nodes you want to export.'

NODE_SAVE_FAILED_WITH_REASON = '"%s" could not be saved: %s'

NODE_SAVE_FAILED = '"%s" could not be saved.'

OBJECT_HAS_NO_MATERIAL_PARM = '"%s" does not have a material parameter. The material was imported to /mat but was not assigned.'

STOCK_LOP_HELPERS_UNAVAILABLE = "Could not load Houdini's material-assignment helpers. The material was not imported."

NETWORK_REFUSED_MATERIAL_LIBRARY = 'Amaze: %s cannot take a Material Library, so the material was not imported.\n\n%s'

DROPPED_MATERIAL_IMPORT_FAILED = 'The dropped material could not be imported and was not assigned. The remaining selected items were added to the library.'

MATERIAL_ASSIGN_FAILED = 'The material was imported, but assignment failed: %s'

SELECT_ONE_NODE_WITH_RAMP = 'Select a single node with a color ramp first.'

NO_MATERIAL_DESTINATION_NETWORK = 'Unable to create the material. Please open a LOP or /mat network first.'

MATERIAL_GENERATION_FAILED = 'Generation failed. See the debug log for details.'

GENERATED_MATERIAL_MOVE_FAILED = 'Amaze: the generated material could not be moved into %s.'

GENERATED_MATERIAL_NOT_REGISTERED = '"%s" was created in %s, but no material entry references it. Please check the library node\'s material list.'

MATERIAL_GENERATION_ERROR = 'Material generation failed (%s).'

NO_MATERIAL_SELECTED = 'No material selected.'

MATERIAL_UPDATE_FAILED = 'Update failed. The library material was not modified.'

SCENE_NODE_NEEDS_ASSET_SECTION = 'This section browses files on disk — a scene node cannot be saved here. Please switch to Material, Color, Node, or Code first.'

SCENE_FILE_MISSING = 'That scene file is no longer there:\n%s'

SCENE_OPEN_FAILED = 'Could not open that scene:\n%s\n\n%s'

LIBRARY_PATH_INVALID = 'Invalid Path selected. Please try again'

IMPORTED_MATERIAL_MAY_NOT_APPEAR = '"%s" was imported into %s but may not appear as a material: %s.'

NO_NODES_SELECTED_TO_SAVE = 'No nodes are selected — nothing to save.'

NETWORK_EMPTY_NOTHING_TO_SAVE = 'The network is empty — nothing to save.'

OCIO_NOT_SET = 'Please configure $OCIO first.'

NODE_IS_NOT_A_MATERIAL_BUILDER = 'The selected node is not a Material Builder.'

PANEL_NOT_OPEN = 'Please open the %s panel first.'

NO_RELEASE_TO_INSTALL = 'There is no release to install. Check for updates first.'

INSTALL_LOCATION_UNKNOWN = 'Amaze cannot tell where it is installed, so it cannot replace itself. Check that $AMAZE points at the install.'

UPDATE_OFFER = '%s\n\nRestart Houdini after installing.'

UPDATE_INSTALLED = 'Amaze %s is installed. Restart Houdini to use it.'

UPDATE_FAILED_UNEXPECTED = 'The update could not be installed (%s).'



TITLE_AMAZE = 'Amaze'

TITLE_AMAZE_REPAIR = 'Amaze Repair'

TITLE_LOG_NOT_SAVED = 'Amaze - Log not saved'

TITLE_EMPTY_SNIPPET = 'Empty snippet'


BUTTONS_PUT_COPY_BACK = ('Put This Copy Back', 'Cancel')

BUTTONS_MOVE_ASIDE = ('Move Them Aside', 'Cancel')

BUTTONS_ADD_BACK = ('Add Them Back', 'Cancel')

BUTTONS_REPAIR_OR_OPEN_WITHOUT = ('Repair', 'Open Without Library')

BUTTONS_IMPORT = ('Import', 'Cancel')

BUTTONS_CLEAN_LIBRARY = ('Clean Library', 'Cancel')

BUTTONS_DELETE = ('Delete', 'Cancel')

BUTTONS_DELETE_USER = ('Delete User', 'Cancel')

BUTTONS_TURN_ON = ('Turn On', 'Cancel')

BUTTONS_INSTALL_UPDATE = ('Install Update', 'Later')


HELP_CLEAN_LIBRARY = 'Removes index rows whose files are gone, deletes orphaned files that no library references, and drops folder pointers and favourites that no longer exist.\n\nFiles are deleted from disk. This cannot be undone.'

HELP_MATERIAL_VERSIONS = 'This applies to everyone who opens this library, on every machine, because it is stored with the library rather than in your preferences.\n\nWith it on, saving over an existing material keeps the previous version instead of replacing it.'


SNIPPET_HAS_NO_CODE = 'There is no code to save.'

CONFIRM_CLEAR_THUMBNAIL_CACHE = 'This deletes all cached image and geometry thumbnails from disk. They will regenerate as you browse.'

LOG_NOT_SAVED_UNEXPECTED = 'The log could not be saved. Unexpected error: %s'


REDSHIFT_CONVERSION_SUMMARY = 'Converted %d of %d Redshift material(s) to Karma.\n\n%s'

NODE_ASSETS_IMPORT_FAILURES = 'Some node assets could not be imported:\n\n%s'

MATERIALS_SAVE_FAILURES = 'Some materials could not be saved:\n\n%s'

MATERIALS_IMPORT_FAILURES = 'Some materials could not be imported:\n\n%s'

CLEANUP_REMOVED_SUMMARY = 'Library cleanup removed:\n\n%s'

LOADER_SOP_HAS_NO_FILE_PARM = 'The "%s" SOP has no file parameter to set.'

NODE_HAS_NO_COLOR_RAMP = '"%s" (%s) has no color ramp parameter to save.'

GEOMETRY_IMPORT_FAILED = 'Could not import %s: %s'
