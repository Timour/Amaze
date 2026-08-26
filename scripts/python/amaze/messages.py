"""EVERY MESSAGE AMAZE SHOWS IN A DIALOG, in ONE document - `hou.ui.displayMessage` and `debug.alert` alike, so a wording change is one edit here and never a hunt through eighteen modules. Keyed by NAME, never by a line number, because a line number rots on the next edit ▸p/messages-need-one-home"""

from __future__ import annotations

# 2 sites - core/category.py:272, core/library.py:481
LIBRARY_NOT_SAVED_ANOTHER_PANEL = 'The library was not saved because another Amaze panel is currently linked to a different library.\n\nClose the other panel, or reopen this one, and saving will resume normally.'

# core/database.py:288
SECTION_UNREADABLE_SAVING_DISABLED = 'Your saved %s could not be read, so Amaze has disabled saving to avoid overwriting them.\n\nTo resolve this, close Houdini and restore a recent backup using the Repair tool on the Amaze shelf.'

# core/database.py:369
LIBRARY_FORMAT_AHEAD_READ_ONLY = 'This library was saved by a newer version of Amaze. To prevent data loss, it has been opened in read-only mode. Update Amaze to restore full functionality.'

# core/database.py:668
LIBRARY_WRITE_FAILED = 'The library could not be saved - %s\n\nThis change is still in memory and will be included in the next successful save, but it is not yet on disk and will not persist if Houdini is closed.'

# core/gradient_library.py:292
PALETTE_NOT_SAVED = 'Amaze was unable to save "%s".\n\nTo resolve this, close any other Amaze panel, or restart Houdini, and then try again.'

# core/gradient_library.py:328
PALETTE_NOT_DELETED = '"%s" was not deleted because Amaze could not update your colors.\n\nTo resolve this, close any other Amaze panel, or restart Houdini, and then try again.'

# core/keyed_store.py:744
SAVE_DENIED_WITH_CAUSE = '%s\n\nThis happened because %s'

# core/library.py:600
ASSET_FILES_WRITTEN_BUT_LIST_NOT_UPDATED = '"%s" was written to disk, but Amaze could not update the library index.\n\nThe item will not appear in the grid until the index is updated.\n\nTo resolve this, restart Houdini and run Repair Library from the Amaze shelf.'

# core/library.py:609
ASSET_NOT_SAVED_LIST_NOT_UPDATED = '"%s" was not saved because Amaze could not update the library index.\n\nRestart Houdini and try saving again.'

# core/library.py:694
ASSET_NOT_DELETED_LIST_NOT_UPDATED = '"%s" was not deleted because Amaze could not update the library index.\n\nClose any other Amaze panels or restart Houdini, then try again.'

# core/library.py:1079
CLEANUP_FOUND_NOTHING_TO_CLEAN = 'Library cleanup finished: nothing to clean.'

# core/library.py:1338
ASSET_CHANGED_ON_DISK_SINCE_LOAD = 'Another user has updated "%s" since this session loaded it, so Amaze did not overwrite their version.\n\nYou can save it as a new material, or reopen the Amaze panel to load their version first.'

# 2 sites - core/matx_sources.py:560, core/matx_sources.py:452
UNSAFE_ARCHIVE_PATHS_SKIPPED = '%d file(s) in this download attempted to write outside your library folder and were skipped.\n\nNo data outside your library was affected. The remainder of the material was downloaded successfully.\n\nThis typically indicates a malformed package. If the material appears incorrect, delete it and download it again.'

# core/repair.py:595
NO_LIBRARY_FOLDER_CONFIGURED = 'No library folder has been configured for Amaze.\n\nTo resolve this, open Amaze, select a library folder in Preferences, and then run Repair again.'

# core/repair.py:602
LIBRARY_FOLDER_UNREACHABLE = 'Amaze cannot reach the library folder it is set to use:\n\n%s\n\nIf it is on a drive or in a synced folder, connect it and run Repair again. If you moved the library, open Amaze and point Preferences at the new location.'

# core/repair.py:616
AMAZE_OPEN_STOPS_REPAIR = 'Amaze is open, so Repair stopped before reading anything.\n\nAn open Amaze saves the library while you work. Quit Houdini, start it again, and run Repair before you open Amaze.'

# core/repair.py:695
CHOSEN_SAVED_COPY_CANNOT_BE_READ = 'That copy of the %s list cannot be read.'

# core/repair.py:711
CONFIRM_PUT_SAVED_COPY_BACK = 'Put the %s list back to the copy from %s?'

# core/repair.py:740
SAVED_COPY_PUT_BACK_DONE = 'The %s list is back to the copy from %s.\n\nOpen Amaze to look at it. %s'

# core/repair.py:748
CONFIRM_MOVE_FILES_ASIDE = 'Move %s aside?'

# core/repair.py:769
NOTHING_MOVED_ASIDE_REASON = 'Amaze moved nothing: %s.'

# core/repair.py:774
FILES_MOVED_ASIDE_SOME_FAILED = "%s moved into Amaze's holding folder on this computer, outside your library, where they are kept for 30 days.\n\n%s could not be moved and remain in place."

# core/repair.py:783
FILES_MOVED_ASIDE_DONE = "%s moved into Amaze's holding folder on this computer, outside your library, where they are kept for 30 days.\n\nClean Library will now run again."

# core/repair.py:807
CONFIRM_ADD_UNLISTED_TO_SECTION = 'Add %d unlisted %s to %s?'

# core/repair.py:829
SECTION_LIST_UNCHANGED_REASON = 'Amaze did not change the %s list: %s.'

# core/repair.py:833
UNLISTED_FILES_ADDED_BACK_DONE = '%d %s were restored to %s.\n\nOpen Amaze to review them. They are in the %s category and ready to be renamed.'

# core/tile_icons.py:207
TILE_ICON_NOT_SAVED = 'Your tile icon could not be saved.\n\nNo other data has been lost — only this icon selection. The tile will retain its previous icon.\n\nThis occurred because %s'

# dialogs/prefs_dialog.py:188
USER_DELETE_CONFIRM = 'Delete user "%s" from this library?'

# dialogs/prefs_dialog.py:206
MATERIAL_VERSIONS_TURN_ON_CONFIRM = 'Enable Material Versions for this library?'

# dialogs/prefs_dialog.py:225
LIBRARY_SETTING_NOT_WRITTEN = 'The setting could not be written to the library folder and was not changed.'

# dialogs/prefs_dialog.py:843
TEST_FOLDER_NOT_PREPARED = 'The folder could not be prepared:\n\n%s'

# panel/notes_panel.py:634
PICTURE_NOT_COPIED_TO_LIBRARY = 'That picture could not be copied into your library, so it was not added. Nothing has been changed.'

# panel/notes_panel.py:639
PICTURE_COPIED_BUT_UNREADABLE = 'That file was copied but could not be shown as a picture, so it was not added.'

# panel/panel.py:221
LIBRARY_INDEX_UNREADABLE = "The library index could not be read.\n\nRepair will restore the most recent backup. If no backup is available, the index will be rebuilt from each asset's embedded metadata. Category names are preserved, but their order and colors may change during a rebuild. The corrupted file is retained as a backup in either case.\n\nOpen Without Library leaves the folder unchanged."

# panel/panel.py:239
REPAIR_COULD_NOT_FIX_THE_LIST = 'Repair was unable to restore the index: %s.\n\nAmaze will open without a library. For more details, use the Repair tool on the Amaze shelf.'

# panel/panel.py:252
INDEX_UNREADABLE_AFTER_REPAIR = 'The repaired index still could not be read.\n\nAmaze will open without a library. For more details, use the Repair tool on the Amaze shelf.'

# panel/panel.py:532
STARTER_SEED_REFUSED_DIRECTORY_HELD_LIBRARY = 'This folder looks like a library whose list has not arrived yet, so Amaze did not set up a new one over it.\n\nIf it lives in a synced folder, let the sync finish and reopen Amaze. If the list really is gone, run Repair Library from the Amaze shelf to rebuild it.'

# panel/panel.py:1491
NO_FOLDER_SELECTED_TO_RELOCATE = 'Select the registered folder to re-point first ("All" is not a real folder).'

# panel/panel.py:1503
RELOCATE_TARGET_NOT_A_FOLDER = 'The specified location does not exist as a folder.'

# 2 sites - panel/panel.py:1788, panel/panel.py:1836
NO_LIBRARY_CONFIGURED = 'Please configure a library first.'

# panel/panel.py:1807
PACKAGE_IMPORT_SUMMARY = 'Imported %d asset(s) and %d file(s) into the Import category.'

# panel/panel.py:1852
MATERIAL_PRESETS_FOUND = 'No material presets were found in: %s'

# panel/panel.py:1863
IMPORT_MATERIAL_PRESETS_FROM = 'Import %d material presets from:\n%s\n\n%s\n\nNote: Thumbnails are not generated during import. After importing, select the new materials and use Update Preview.'

# panel/panel.py:1897
GALLERY_IMPORT_FINISHED_IMPORTED_SKIPPED = 'Gallery import complete.\n\nImported: %d\nSkipped: %d\nFailed: %d\n\nTo generate previews, select the new materials and use Update Preview.'

# 2 sites - panel/panel.py:1911, panel/panel.py:2034
NO_LIBRARY_OPEN = 'Please open a library first.'

# panel/panel.py:1914
CLEAN_LIBRARY_CONFIRM = 'Clean Library?'

# panel/panel.py:2376
AMAZE_COULD_NOT = '%d of %d items could not be imported:\n\n%s'

# panel/panel.py:2591
SCENE_BUILD_PARTIAL_FAILURE = '%d of %d items could not be built:\n\n%s'

# panel/panel.py:2694
TILE_ICON_SAVE_FAILED = '%d tile icon%s could not be saved. Please verify that the library folder is writable.'

# 4 sites - panel/panel.py:2744, panel/panel.py:2852, panel/panel.py:3395
NO_LIBRARY_CONFIGURED_2 = 'Please configure a library first. Open Preferences and select one under Library Path.'

# panel/panel.py:2780
NO_NODE_WITH_CODE_SELECTED = 'To save a snippet, right-click a wrangle or other node that has a code parameter.'

# panel/panel.py:2788
NODE_HAS_NO_CODE_PARM = '"%s" does not have a code or snippet parameter.'

# panel/panel.py:2862
NO_NETWORK_SELECTED_TO_SAVE = 'To save, right-click the network or the nodes you want to export.'

# panel/panel.py:2905
NODE_SAVE_FAILED_WITH_REASON = '"%s" could not be saved: %s'

# panel/panel.py:2910
NODE_SAVE_FAILED = '"%s" could not be saved.'

# panel/panel.py:3141
OBJECT_HAS_NO_MATERIAL_PARM = '"%s" does not have a material parameter. The material was imported to /mat but was not assigned.'

# panel/panel.py:3175
STOCK_LOP_HELPERS_UNAVAILABLE = "Could not load Houdini's material-assignment helpers. The material was not imported."

# panel/panel.py:3232
NETWORK_REFUSED_MATERIAL_LIBRARY = 'Amaze: %s cannot take a Material Library, so the material was not imported.\n\n%s'

# panel/panel.py:3260
DROPPED_MATERIAL_IMPORT_FAILED = 'The dropped material could not be imported and was not assigned. The remaining selected items were added to the library.'

# panel/panel.py:3289
MATERIAL_ASSIGN_FAILED = 'The material was imported, but assignment failed: %s'

# panel/panel.py:3404
SELECT_ONE_NODE_WITH_RAMP = 'Select a single node with a color ramp first.'

# 2 sites - panel/panel.py:3769, panel/panel.py:2558
NO_MATERIAL_DESTINATION_NETWORK = 'Unable to create the material. Please open a LOP or /mat network first.'

# panel/panel.py:3779
MATERIAL_GENERATION_FAILED = 'Generation failed. See the debug log for details.'

# panel/panel.py:3789
GENERATED_MATERIAL_MOVE_FAILED = 'Amaze: the generated material could not be moved into %s.'

# panel/panel.py:3814
GENERATED_MATERIAL_NOT_REGISTERED = '"%s" was created in %s, but no material entry references it. Please check the library node\'s material list.'

# panel/panel.py:3823
MATERIAL_GENERATION_ERROR = 'Material generation failed (%s).'

# panel/panel.py:3841
NO_MATERIAL_SELECTED = 'No material selected.'

# panel/panel.py:3920
MATERIAL_UPDATE_FAILED = 'Update failed. The library material was not modified.'

# panel/sections.py:126
SCENE_NODE_NEEDS_ASSET_SECTION = 'This section browses files on disk — a scene node cannot be saved here. Please switch to Material, Color, Node, or Code first.'

# panel/sections.py:1301
SCENE_FILE_MISSING = 'That scene file is no longer there:\n%s'

# panel/sections.py:1313
SCENE_OPEN_FAILED = 'Could not open that scene:\n%s\n\n%s'

# prefs/prefs.py:151
LIBRARY_PATH_INVALID = 'Invalid Path selected. Please try again'

# render/nodes.py:852
IMPORTED_MATERIAL_MAY_NOT_APPEAR = '"%s" was imported into %s but may not appear as a material: %s.'

# render/nodes.py:1369
NO_NODES_SELECTED_TO_SAVE = 'No nodes are selected — nothing to save.'

# render/nodes.py:1376
NETWORK_EMPTY_NOTHING_TO_SAVE = 'The network is empty — nothing to save.'

# render/nodes.py:1549
OCIO_NOT_SET = 'Please configure $OCIO first.'

# render/nodes.py:1579
NODE_IS_NOT_A_MATERIAL_BUILDER = 'The selected node is not a Material Builder.'

# utils/rc_calls.py:20
PANEL_NOT_OPEN = 'Please open the %s panel first.'

# core/updater.py
NO_RELEASE_TO_INSTALL = 'There is no release to install. Check for updates first.'

# core/updater.py
INSTALL_LOCATION_UNKNOWN = 'Amaze cannot tell where it is installed, so it cannot replace itself. Check that $AMAZE points at the install.'

# toolbar/Amaze.shelf - the offer, with the feed's own sentence as %s
UPDATE_OFFER = '%s\n\nRestart Houdini after installing.'

# 2 sites - toolbar/Amaze.shelf, dialogs/prefs_dialog.py
UPDATE_INSTALLED = 'Amaze %s is installed. Restart Houdini to use it.'

# 2 sites - toolbar/Amaze.shelf, dialogs/prefs_dialog.py
UPDATE_FAILED_UNEXPECTED = 'The update could not be installed (%s).'


# ── Dialog TITLES ────────────────────────────────────────────────────

# 6 sites
TITLE_AMAZE = 'Amaze'

# 17 sites - core/repair.py
TITLE_AMAZE_REPAIR = 'Amaze Repair'

# dialogs/prefs_dialog.py:1002
TITLE_LOG_NOT_SAVED = 'Amaze - Log not saved'

# dialogs/code_dialog.py:178
TITLE_EMPTY_SNIPPET = 'Empty snippet'

# ── BUTTON SETS ──────────────────────────────────────────────────────
# The words on the buttons. The FIRST is the accepting one.

# core/repair.py:703
BUTTONS_PUT_COPY_BACK = ('Put This Copy Back', 'Cancel')

# core/repair.py:739
BUTTONS_MOVE_ASIDE = ('Move Them Aside', 'Cancel')

# core/repair.py:793
BUTTONS_ADD_BACK = ('Add Them Back', 'Cancel')

# panel/panel.py:223
BUTTONS_REPAIR_OR_OPEN_WITHOUT = ('Repair', 'Open Without Library')

# panel/panel.py:1847
BUTTONS_IMPORT = ('Import', 'Cancel')

# panel/panel.py:1893
BUTTONS_CLEAN_LIBRARY = ('Clean Library', 'Cancel')

# panel/panel.py:3720
BUTTONS_DELETE = ('Delete', 'Cancel')

# dialogs/prefs_dialog.py:189
BUTTONS_DELETE_USER = ('Delete User', 'Cancel')

# dialogs/prefs_dialog.py:207
BUTTONS_TURN_ON = ('Turn On', 'Cancel')

# toolbar/Amaze.shelf
BUTTONS_INSTALL_UPDATE = ('Install Update', 'Later')

# ── HELP text, shown under a Houdini dialog's question ───────────────

# panel/panel.py:1893
HELP_CLEAN_LIBRARY = 'Removes index rows whose files are gone, deletes orphaned files that no library references, and drops folder pointers and favourites that no longer exist.\n\nFiles are deleted from disk. This cannot be undone.'

# dialogs/prefs_dialog.py:207
HELP_MATERIAL_VERSIONS = 'This applies to everyone who opens this library, on every machine, because it is stored with the library rather than in your preferences.\n\nWith it on, saving over an existing material keeps the previous version instead of replacing it.'

# ── Messages that were still written at their call site ──────────────

# dialogs/code_dialog.py:178
SNIPPET_HAS_NO_CODE = 'There is no code to save.'

# dialogs/prefs_dialog.py:879
CONFIRM_CLEAR_THUMBNAIL_CACHE = 'This deletes all cached image and geometry thumbnails from disk. They will regenerate as you browse.'

# dialogs/prefs_dialog.py:1007
LOG_NOT_SAVED_UNEXPECTED = 'The log could not be saved. Unexpected error: %s'

# ── Built at runtime: the FIXED lead-in, the caller supplies the rest ─

# panel/panel.py:1668
REDSHIFT_CONVERSION_SUMMARY = 'Converted %d of %d Redshift material(s) to Karma.\n\n%s'

# panel/panel.py:2699
NODE_ASSETS_IMPORT_FAILURES = 'Some node assets could not be imported:\n\n%s'

# panel/panel.py:3945
MATERIALS_SAVE_FAILURES = 'Some materials could not be saved:\n\n%s'

# panel/panel.py:3975
MATERIALS_IMPORT_FAILURES = 'Some materials could not be imported:\n\n%s'

# panel/panel.py:1938
CLEANUP_REMOVED_SUMMARY = 'Library cleanup removed:\n\n%s'

# panel/panel.py:3008
LOADER_SOP_HAS_NO_FILE_PARM = 'The "%s" SOP has no file parameter to set.'

# panel/panel.py:3380
NODE_HAS_NO_COLOR_RAMP = '"%s" (%s) has no color ramp parameter to save.'

# panel/panel.py:2997
GEOMETRY_IMPORT_FAILED = 'Could not import %s: %s'
