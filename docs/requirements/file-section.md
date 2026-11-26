# File section: requirements

What the File section must do with the user's own folders: browse them, bring a file into the scene,
New Folder, Save Scene, Copy Path and its locations. The engine is `core/file_library.py`,
`core/locations.py`, `core/folders.py`, `actions/files.py`, `pane/files.py` and `sections/file.py`.
Moves and Paste are [file moves](file-moves.md); a file's data following it is FM-20, CM-25, CM-26
and LS-31; a location not on this computer is CL-14; a drop is DD. The levels and the rules for tests
are in the [README](README.md).

## Catastrophe

- FI-01 Catastrophe: Browsing, counting, and adding, renaming, locating, sorting or removing a location never writes, moves or removes a file in the user's folders.
- FI-02 Catastrophe: New Folder and Save Scene never write over anything: a name in use, or one with a slash, is refused and nothing is made.

## Severe

- FI-10 Severe: Opening a scene never drops unsaved work in the open scene: Houdini's own save prompt comes first.
- FI-11 Severe: Save Scene saves the open scene whole under the new name in the folder shown, and the new file becomes the open scene; a typed scene extension is not added twice; a save that fails leaves the open scene as it was and says why.

## Wrong output

- FI-20 Wrong output: A location lists every file in its own folder, hidden files excepted, and none below it; a file's kind follows its extension.
- FI-21 Wrong output: A location keeps one id for every user, so renaming, locating or adding a location around it keeps its files' data; its name, colour and place in the list are each user's own.
- FI-22 Wrong output: Locate points a location at another folder, keeping its id, name and its files' data; a folder that is already a location is refused.
- FI-23 Wrong output: Removing a location asks first, then unregisters it for this user and sweeps its cached tile pictures; captures stay.
- FI-24 Wrong output: Double-click and Import on a geometry file do exactly what Houdini's File ▸ Import ▸ Geometry does: it follows the scene viewer's Create at Object Level or Create in Context, and a selected node's file is not changed. With no scene viewer it goes into the network shown, as DD-23. One undo step per command. An image goes to the one selected node that takes it, else a new image node; a scene opens; any other file copies its path.
- FI-25 Wrong output: A path written into the scene, and Copy Path's text, are spelled as Write Paths As says, one path per line.
- FI-26 Wrong output: The `$HIP` row shows the open scene's folder and follows Save, Open and New.
- FI-27 Wrong output: New Folder and Save Scene act on the folder shown and are off while All is shown; the scene's extension follows the licence.
