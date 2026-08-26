"""EVERY MESSAGE AMAZE SHOWS IN A DIALOG, in ONE document - `hou.ui.displayMessage` and `debug.alert` alike, so a wording change is one edit here and never a hunt through eighteen modules. Keyed by NAME, never by a line number, because a line number rots on the next edit ▸p/messages-need-one-home"""

from __future__ import annotations

# 2 sites - core/category.py:272, core/library.py:481
LIBRARY_NOT_SAVED_ANOTHER_PANEL = 'Amaze did not save this library, because another Amaze panel has been pointed at a different one.\n\nNothing is lost. Close the other panel, or reopen this one, and your changes will save again.'

# core/database.py:288
SECTION_UNREADABLE_SAVING_DISABLED = 'Your saved %s could not be read, so Amaze will not save over them.\n\nNothing has been lost - the file is untouched. Changes you make there now will not be kept.\n\nClose Houdini and put back a recent copy with the Repair tool in the Amaze shelf.'

# core/database.py:369
LIBRARY_FORMAT_AHEAD_READ_ONLY = 'This library was saved by a newer Amaze. To keep it safe, this machine opens it read-only - update Amaze, then everything works as normal.'

# core/database.py:668
LIBRARY_WRITE_FAILED = 'Could not save the library - %s\n\nNothing already saved has been lost. This change is still here in Amaze, and saving anything else writes it too - but it is NOT on disk yet, so it will not survive closing Houdini.'

# core/gradient_library.py:292
PALETTE_NOT_SAVED = 'Amaze could not save "%s".\n\nNothing else has been lost - your other colors are exactly as they were.\n\nClose any other Amaze panel, or restart Houdini, then try again.'

# core/gradient_library.py:328
PALETTE_NOT_DELETED = '"%s" was not deleted, because Amaze could not update your colors.\n\nNothing was removed - the palette is exactly as it was.\n\nClose any other Amaze panel, or restart Houdini, then try again.'

# core/keyed_store.py:744
SAVE_DENIED_WITH_CAUSE = '%s\n\nThis happened because %s'

# core/library.py:600
ASSET_FILES_WRITTEN_BUT_LIST_NOT_UPDATED = '"%s" was written to disk, but Amaze could not update the library list.\n\nNothing is lost - the files are there. It will not appear in the grid until the list is written.\n\nRestart Houdini, then run Repair Library from the Amaze shelf to put it back in the list.'

# core/library.py:609
ASSET_NOT_SAVED_LIST_NOT_UPDATED = '"%s" was not saved, because Amaze could not update the library list.\n\nNothing else was changed - everything already in the library is untouched.\n\nRestart Houdini and save it again.'

# core/library.py:694
ASSET_NOT_DELETED_LIST_NOT_UPDATED = '"%s" was not deleted, because Amaze could not update the library list.\n\nNothing was removed - the material and its files are exactly as they were.\n\nClose any other Amaze panel, or restart Houdini, then try again.'

# core/library.py:1079
CLEANUP_FOUND_NOTHING_TO_CLEAN = 'Library cleanup finished: nothing to clean.'

# core/library.py:1338
ASSET_CHANGED_ON_DISK_SINCE_LOAD = 'Someone else has updated "%s" since this Houdini read it, so Amaze did not save over their version.\n\nNothing is lost - your network is still in the scene. Save it as a new material, or reopen the Amaze panel to load their version first.'

# 2 sites - core/matx_sources.py:560, core/matx_sources.py:452
UNSAFE_ARCHIVE_PATHS_SKIPPED = '%d file(s) in this download tried to write outside your library folder, so Amaze skipped them.\n\nNothing outside your library was touched. The rest of the material was downloaded normally.\n\nThis usually means the package is malformed. If the material looks wrong, delete it and download it again.'

# core/repair.py:595
NO_LIBRARY_FOLDER_CONFIGURED = 'Amaze has no library folder yet.\n\nOpen Amaze and pick one in Preferences, then run Repair again.'

# core/repair.py:602
LIBRARY_FOLDER_UNREACHABLE = 'Amaze cannot reach the library folder it is set to use:\n\n%s\n\nNothing was changed. If it is on a drive or in a synced folder, connect it and run Repair again. If you moved the library, open Amaze and point Preferences at the new place.'

# core/repair.py:616
AMAZE_OPEN_STOPS_REPAIR = 'Amaze is open, so Repair stopped before reading anything.\n\nAn open Amaze saves the library while you work, and it would write over anything Repair put back. Quit Houdini, start it again, and run Repair before you open Amaze.'

# core/repair.py:695
CHOSEN_SAVED_COPY_CANNOT_BE_READ = 'That copy of the %s list cannot be read, so Amaze left everything alone. Try another copy.'

# core/repair.py:711
CONFIRM_PUT_SAVED_COPY_BACK = 'Put the %s list back to the copy from %s?'

# core/repair.py:740
SAVED_COPY_PUT_BACK_DONE = 'The %s list is back to the copy from %s.\n\nOpen Amaze to look at it. %s'

# core/repair.py:748
CONFIRM_MOVE_FILES_ASIDE = 'Move %s aside?'

# core/repair.py:769
NOTHING_MOVED_ASIDE_REASON = 'Amaze moved nothing: %s.'

# core/repair.py:774
FILES_MOVED_ASIDE_SOME_FAILED = "%s moved into Amaze's holding folder on this computer - outside your library, kept for 30 days. %s could not be moved and are still where they were - nothing was lost either way."

# core/repair.py:783
FILES_MOVED_ASIDE_DONE = "%s moved into Amaze's holding folder on this computer - outside your library, kept for 30 days. Nothing was deleted, and Clean Library will run again now."

# core/repair.py:807
CONFIRM_ADD_UNLISTED_TO_SECTION = 'Add %d unlisted %s to %s?'

# core/repair.py:829
SECTION_LIST_UNCHANGED_REASON = 'Amaze did not change the %s list: %s.'

# core/repair.py:833
UNLISTED_FILES_ADDED_BACK_DONE = '%d %s came back into %s. Open Amaze to see them - they are in the %s category, ready to be renamed.'

# core/tile_icons.py:207
TILE_ICON_NOT_SAVED = 'Your tile icon could not be saved.\n\nNothing else has been lost - only this icon choice. The tile keeps the icon it had.\n\nThis happened because %s'

# dialogs/prefs_dialog.py:188
USER_DELETE_CONFIRM = 'Delete user "%s" from this library?'

# dialogs/prefs_dialog.py:206
MATERIAL_VERSIONS_TURN_ON_CONFIRM = 'Turn on Material Versions for this library?'

# dialogs/prefs_dialog.py:225
LIBRARY_SETTING_NOT_WRITTEN = 'Could not write the setting to the library folder, so it was not changed.'

# dialogs/prefs_dialog.py:843
TEST_FOLDER_NOT_PREPARED = 'That folder could not be prepared:\n\n%s'

# panel/notes_panel.py:634
PICTURE_NOT_COPIED_TO_LIBRARY = 'That picture could not be copied into your library, so it was not added. Nothing has been changed.'

# panel/notes_panel.py:639
PICTURE_COPIED_BUT_UNREADABLE = 'That file was copied but could not be shown as a picture, so it was not added.'

# panel/panel.py:221
LIBRARY_INDEX_UNREADABLE = "Your library's list could not be read.\n\nRepair puts back the newest saved copy - or, if none reads, rebuilds the list from what each asset itself remembers. Categories keep their names; their order and colours may not survive a rebuild. The broken file is kept beside itself either way.\n\nOpen Without Library leaves the folder untouched."

# panel/panel.py:239
REPAIR_COULD_NOT_FIX_THE_LIST = 'Repair could not fix the list: %s.\n\nAmaze opens without a library. The Repair tool on the Amaze shelf can tell you more.'

# panel/panel.py:252
INDEX_UNREADABLE_AFTER_REPAIR = 'The repaired list still could not be read.\n\nAmaze opens without a library. The Repair tool on the Amaze shelf can tell you more.'

# panel/panel.py:532
STARTER_SEED_REFUSED_DIRECTORY_HELD_LIBRARY = 'This folder looks like a library whose list has not arrived yet, so Amaze did not set up a new one over it.\n\nIf it lives in a synced folder, let the sync finish and reopen Amaze. If the list really is gone, run Repair Library from the Amaze shelf to rebuild it.'

# panel/panel.py:1491
NO_FOLDER_SELECTED_TO_RELOCATE = 'Select the registered folder to re-point first ("All" is not a real folder).'

# panel/panel.py:1503
RELOCATE_TARGET_NOT_A_FOLDER = "That location doesn't exist as a folder - nothing was changed."

# 2 sites - panel/panel.py:1788, panel/panel.py:1836
NO_LIBRARY_CONFIGURED = 'Please set a library first.'

# panel/panel.py:1807
PACKAGE_IMPORT_SUMMARY = 'Imported %d asset(s) and %d file(s) into the Import category.'

# panel/panel.py:1852
MATERIAL_PRESETS_FOUND = 'No material presets found in:\n%s'

# panel/panel.py:1863
IMPORT_MATERIAL_PRESETS_FROM = 'Import %d material presets from\n%s\n\n%s\n\nThumbnails are NOT rendered during the import - select the new materials afterwards and use Update Preview.'

# panel/panel.py:1897
GALLERY_IMPORT_FINISHED_IMPORTED_SKIPPED = 'Gallery import finished.\n\nImported: %d\nSkipped: %d\nFailed: %d\n\nSelect the new materials and use Update Preview to generate their previews.'

# 2 sites - panel/panel.py:1911, panel/panel.py:2034
NO_LIBRARY_OPEN = 'Please open a library first'

# panel/panel.py:1914
CLEAN_LIBRARY_CONFIRM = 'Clean Library?'

# panel/panel.py:2376
AMAZE_COULD_NOT = 'Amaze: %d of %d could not be imported:\n\n%s'

# panel/panel.py:2591
SCENE_BUILD_PARTIAL_FAILURE = 'Amaze: %d of %d could not be built:\n\n%s'

# panel/panel.py:2694
TILE_ICON_SAVE_FAILED = '%d tile icon%s could not be saved - check that the library folder is writable.'

# 4 sites - panel/panel.py:2744, panel/panel.py:2852, panel/panel.py:3395
NO_LIBRARY_CONFIGURED_2 = 'Please set a library first. Use the %s panel - Library/Open Dialog.'

# panel/panel.py:2780
NO_NODE_WITH_CODE_SELECTED = 'Right-click a wrangle (or other node with a code parameter) to save its snippet.'

# panel/panel.py:2788
NODE_HAS_NO_CODE_PARM = '"%s" has no code/snippet parameter.'

# panel/panel.py:2862
NO_NETWORK_SELECTED_TO_SAVE = 'Right-click the network - or the nodes - you want to save.'

# panel/panel.py:2905
NODE_SAVE_FAILED_WITH_REASON = '"%s" could not be saved: %s'

# panel/panel.py:2910
NODE_SAVE_FAILED = '"%s" could not be saved.'

# panel/panel.py:3141
OBJECT_HAS_NO_MATERIAL_PARM = "'%s' has no material parameter - imported to /mat without assigning."

# panel/panel.py:3175
STOCK_LOP_HELPERS_UNAVAILABLE = "Amaze: could not load Houdini's material-assignment helpers - material not imported."

# panel/panel.py:3232
NETWORK_REFUSED_MATERIAL_LIBRARY = 'Amaze: %s cannot take a Material Library, so the material was not imported.\n\n%s'

# panel/panel.py:3260
DROPPED_MATERIAL_IMPORT_FAILED = 'The material you dropped could not be imported, so nothing was assigned. The others in the selection were still added to the library.'

# panel/panel.py:3289
MATERIAL_ASSIGN_FAILED = 'Amaze: imported, but assigning failed: %s'

# panel/panel.py:3404
SELECT_ONE_NODE_WITH_RAMP = 'Select a single node with a color ramp first.'

# 2 sites - panel/panel.py:3769, panel/panel.py:2558
NO_MATERIAL_DESTINATION_NETWORK = 'Amaze: no place to create the material - open a LOP or /mat network first.'

# panel/panel.py:3779
MATERIAL_GENERATION_FAILED = 'Generation failed - see the debug log.'

# panel/panel.py:3789
GENERATED_MATERIAL_MOVE_FAILED = 'Amaze: the generated material could not be moved into %s.'

# panel/panel.py:3814
GENERATED_MATERIAL_NOT_REGISTERED = '"%s" was created in %s but no material entry covers it - check the library node\'s material list.'

# panel/panel.py:3823
MATERIAL_GENERATION_ERROR = 'Amaze: generation failed (%s).'

# panel/panel.py:3841
NO_MATERIAL_SELECTED = 'No material selected'

# panel/panel.py:3920
MATERIAL_UPDATE_FAILED = 'Update failed - the library material was not changed.'

# panel/sections.py:126
SCENE_NODE_NEEDS_ASSET_SECTION = "This section browses files on disk - a scene node can't be saved into it. Switch to Material, Color, Node or Code first."

# panel/sections.py:1301
SCENE_FILE_MISSING = 'That scene file is no longer there:\n%s'

# panel/sections.py:1313
SCENE_OPEN_FAILED = 'Could not open that scene:\n%s\n\n%s'

# prefs/prefs.py:151
LIBRARY_PATH_INVALID = 'Invalid Path selected. Please try again'

# render/nodes.py:852
IMPORTED_MATERIAL_MAY_NOT_APPEAR = '"%s" was imported into %s but may not appear as a material: %s.'

# render/nodes.py:1369
NO_NODES_SELECTED_TO_SAVE = 'No nodes selected - nothing to save.'

# render/nodes.py:1376
NETWORK_EMPTY_NOTHING_TO_SAVE = 'The network is empty - nothing to save.'

# render/nodes.py:1549
OCIO_NOT_SET = 'Please set $OCIO first'

# render/nodes.py:1579
NODE_IS_NOT_A_MATERIAL_BUILDER = 'Selected Node is not a Material Builder'

# utils/rc_calls.py:20
PANEL_NOT_OPEN = 'Please open the %s panel first.'

