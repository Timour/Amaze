# Versions: requirements

What the version store must do. Only materials keep versions: a snippet's old versions stay in its
folder as they are, and nothing else uses versions. The engine is `core/versions.py`, with its
caller in `actions/materials.py` (saving over a material) and the Versions window's calls in
`core/library.py`, which `pane/assets.py` makes for Select and Delete. Preferences ▸ Versions is the library's policy (LS-20). The levels and the rules
for tests are in the [README](README.md).

## Catastrophe

- VS-01 Catastrophe: Switching versions never loses the material's current content: what no version holds yet is kept as a new version first, and when that cannot be written, nothing switches.
- VS-02 Catastrophe: Making or switching a version is applied whole or not at all: cut off by a full disk, a crash or a file another program holds, the material is left on one version, never part of one and part of another, and the list names the version its files hold.
- VS-03 Catastrophe: A new version never writes over a version file already on disk, even one the list does not name, such as another computer's arriving by sync.
- VS-04 Catastrophe: A version list that cannot be read is never written over: no version is made, switched, renamed or deleted until it can be read.
- VS-05 Catastrophe: Losing a material's versions, the whole folder or only its list, never touches the material itself: it still opens, imports and renders.
- VS-06 Catastrophe: Deleting a version takes away that version's files and its line in the list, and nothing else: no other version's file and none of the material's own. The files go to the library's trash.
- VS-07 Catastrophe: Deleting a version is applied whole or not at all: cut off by a full disk, a crash or a file another program holds, the list names every version whose files are in place and none whose files are gone.

## Severe

- VS-10 Severe: Saving over a material keeps it as it was as a version when no version holds it, for a change of values or of nodes alike, and the new state becomes the active version: the first time, the old one becomes Version 1 and the new one Version 2. When that copy cannot be written, the save-over is refused with a message and the material stays as it was.
- VS-11 Severe: Switching versions keeps the material's current name, category, tags and comments.
- VS-12 Severe: Deleting the version in use first puts the first version left in the list on the material, exactly as Select does; when that cannot be done, nothing is deleted.

## Wrong output

- VS-20 Wrong output: Select in the Versions window puts that version on the material, whole: its network, builder, picture and COP companion with the companion's name in the row; nothing of the version shown before stays. Cancel changes nothing.
- VS-21 Wrong output: Changing a material's name, category, tags or comments makes no new version.
- VS-22 Wrong output: A fresh render goes into the active version only, and only while that version holds the material; every other version keeps its own picture.
- VS-24 Wrong output: After a switch, saving over that material is not refused as changed elsewhere.
- VS-26 Wrong output: With Versions off, saving over a material replaces it and makes no version; the versions it already has stay as they are.
- VS-27 Wrong output: The Versions window opens for the material whose Versions row was picked; a row that is gone opens none.
- VS-28 Wrong output: Delete in the Versions window asks first and names the version; Cancel there deletes nothing.
- VS-29 Wrong output: After a delete the window lists the versions left with the one in use picked, and a later version never gets a deleted version's number.
- VS-30 Wrong output: Delete is off while one version is left.
- VS-31 Wrong output: A Select that could not be done says so in a message that names the version.
- VS-32 Wrong output: A Delete that could not be done says so in a message that names the version, and the window lists the versions as they are.
- VS-33 Wrong output: A material with two versions or more shows the versions mark on its tile; one with a single version does not.
