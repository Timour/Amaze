# Gallery Import: requirements

What importing a Houdini gallery (`.gal`) must do. The engine is `core/gallery_import.py` and
`import_galleries` in `pane/saving.py`; each entry is saved as SL saves a material. The levels and
the rules for tests are in the [README](README.md).

## Severe

- GI-01 Severe: Gallery Import leaves the scene as it was: every node it makes is off the undo list and removed, a failed entry's included.
- GI-02 Severe: Houdini's gallery list is left as it was found: a gallery not installed before is removed again, one installed stays installed, and if it cannot be put back the user is told.

## Wrong output

- GI-20 Wrong output: Nothing is imported before the user confirms the list of what the file holds; Cancel imports nothing.
- GI-21 Wrong output: Each VOP or LOP material entry becomes one new material, in a category named after its last gallery category, else Gallery, tagged `gallery`, not a favorite; every other entry is skipped and counted.
- GI-22 Wrong output: An entry that fails is counted and the rest go on; one whose files were saved but not its row counts as imported and is named.
- GI-23 Wrong output: Esc stops the import; what was saved stays, its categories shown in the sidebar.
- GI-24 Wrong output: The saved materials' pictures render in one batch at the end, after Esc too, and not at all when Render on Import is off.
- GI-25 Wrong output: The closing message gives how many were imported, skipped and failed.
