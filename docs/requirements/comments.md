# Comments: requirements

What comments must do: their text, the pictures pasted into them, and how both follow their asset
or file. The engine is `core/notes.py`, the Comments page's save rules, and the comment keys of files
in `core/locations.py`. The text is in its section's database, one page per asset id or file key; an
asset's pictures are in its folder (LS-36, LS-40), a file's in `files/comments/`. A file's favorites
go as its comments do (LS-31); a moved file keeps its comments (FM-20); a deleted asset's folder goes
to the trash (LS-39). The levels and the rules for tests are in the [README](README.md).

## Catastrophe

- CM-01 Catastrophe: Saving a comment changes only its own page: every other page, in every section, and every other entry of its database are kept, those another session saved included.
- CM-02 Catastrophe: An asset delete that is not saved keeps its comment, its pictures and every user's favorite of it; one that is saved drops the comment in that same save.
- CM-03 Catastrophe: No picture a comment names is trashed or removed, except with its asset's folder when the asset is deleted.
- CM-04 Catastrophe: An edit changes only what was edited: every other item is saved as it was, a picture whose file is not here yet included, and undo never takes away what was loaded.

## Severe

- CM-10 Severe: What is typed is saved to the asset or file, and the library, it was typed for: within a second, and at once when the selection or the library changes, the pane hides or closes, the panel is deleted or Houdini quits; a rename while typing loses none of it.

## Wrong output

- CM-20 Wrong output: A comment is text, to-dos and pictures in the order written, and reads back the same in every session and on every computer.
- CM-21 Wrong output: Each item names the user who wrote it; an unchanged or ticked item keeps its id and author.
- CM-22 Wrong output: A comment with no text, to-do or picture left is removed, so its asset or file has no comment; one that still holds an item only a newer Amaze knows is kept (LS-13).
- CM-23 Wrong output: A pasted picture is copied into the library under a name of its own before the comment names it, so two pictures never share a file; the original is only read.
- CM-24 Wrong output: A picture whose file is not here, still syncing or gone, shows its fallback text, and the picture the next time the comment opens after the file arrives.
- CM-25 Wrong output: A file's comment stays with it when its location is renamed or relocated, when a location is added above or inside it, and when two ids of one folder become one, whose pages are joined.
- CM-26 Wrong output: Removing a File location drops the comments under it, except files a remaining location covers, whose comments move to it; a failed move drops nothing.
- CM-27 Wrong output: An exported asset takes its comment and its pictures; imported, the comment shows them.
- CM-28 Wrong output: A comment that comes with new assets (an import, a starter set, a download's credit) is written only for assets that were saved.
- CM-29 Wrong output: A page of any shape is read without an error; a broken item is left out, and a picture path never names a file outside the library.
- CM-30 Wrong output: A picture taken out of a comment goes to the library's trash in the same save, unless another comment still shows it.
