# File moves: requirements

What moving and copying the user's own files must do. The engine is `core/file_moves.py`, with
`locations.files_moved` in `core/locations.py`, which keeps a moved file's data with it.
The levels and the rules for tests are in the [README](README.md).

## Catastrophe

- FM-01 Catastrophe: A move or copy never writes over a file already at the destination unless the user chose to replace it, and never replaces a file with itself.
- FM-02 Catastrophe: A move or copy cut off at any moment, by a stop, Houdini quitting, a full disk or a drive unplugged, leaves every file whole: at its source, or complete at its destination.
- FM-03 Catastrophe: A move to another drive removes the original only after the copy is complete on disk; when the original cannot be removed, both are kept and the user is told.

## Severe

- FM-10 Severe: The scene open in Houdini is never moved, and the user is told why.
- FM-11 Severe: A file another program has open is tried again for a moment; still held, it is left where it is and reported.

## Wrong output

- FM-20 Wrong output: A moved file keeps its comments, tile picture, capture and every user's heart; a copy gets none of them.
- FM-21 Wrong output: After a move, the user is told which files moved, which were skipped because the name was taken, and which failed and why.
- FM-22 Wrong output: Undo moves the last move's files back to where they were.
- FM-23 Wrong output: Only one move or copy runs at a time; a second one started while the first runs is refused with a message.
- FM-24 Wrong output: A file already in the destination folder is left where it is.
- FM-25 Wrong output: A moved or copied file keeps its dates.
