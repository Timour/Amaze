# Library storage: requirements

What the library's storage must do. The engine is `core/guard.py`, `core/documents.py`,
`core/library_db.py`, `core/library_settings.py`, `core/library_policy.py`, the asset folders
in `core/material.py`, `core/texstore.py` and the comment pictures in `core/notes.py`, and
`core/layout_conversion.py`. Check Library is its own engine, with its own
[list](check-library.md). The levels and the rules for tests are in the [README](README.md).

## Catastrophe

- LS-01 Catastrophe: A write cut off at any moment leaves every file in the library whole, as it was before or as it was written: databases, records, pictures, textures and downloaded materials alike.
- LS-02 Catastrophe: A change of several files is applied whole or not at all; a change cut off halfway is finished the next time the library is opened.
- LS-03 Catastrophe: A save never overwrites what another session saved since it was read: the two are merged, and if the file keeps changing, nothing is written and the user is told.
- LS-04 Catastrophe: When two users change the same field at once, one value is kept and the other user is named in an alert; no change is lost without a word.
- LS-05 Catastrophe: A database that cannot be read is never written over or removed: it shows as damaged, takes no change, and one copy of it is kept in `backup/`.
- LS-06 Catastrophe: A database, or a change waiting in the library, from a newer Amaze is never written or applied by this one.
- LS-07 Catastrophe: A database that existed and is now gone shows as missing; it is never quietly started again empty.
- LS-08 Catastrophe: Each database keeps backups of what its saves replaced: the newest 3, at least 30 minutes apart, and one a day for 30 days.
- LS-09 Catastrophe: A database that holds less than half of its newest backup is reported, so a mass loss is noticed.
- LS-10 Catastrophe: Restoring a backup keeps the file it replaces as an undo copy.
- LS-11 Catastrophe: A deleted file goes to the library's trash, in that day's folder under its old path, never over another trashed file, and is removed after 30 days.
- LS-12 Catastrophe: Nothing is written, moved or removed outside the library folder.
- LS-13 Catastrophe: Data this Amaze does not know, written by a newer one, is kept when it saves.
- LS-14 Catastrophe: An asset's `<id>.json` record gets its row's changes in the same save as the database, so a lost database can be rebuilt from the records.
- LS-15 Catastrophe: Two Amaze sessions on one computer never write the library at the same moment.
- LS-16 Catastrophe: A file another program holds delays a change instead of losing it: the change is kept and finished on a later read or save.
- LS-17 Catastrophe: A failed write, a full disk included, leaves the library as it was, leaves no stray files, and tells the user.
- LS-18 Catastrophe: Converting a 2.0 library to 3.0 moves every asset's files into its own folder: a material's or node's files, a snippet's or color's picture, a material's versions, and each picture pasted into its comments; any other section's versions go to the trash, as only materials keep versions; every `matX` texture and every comment picture goes into each asset that uses it, a copy for each one after the first; a conversion cut off at any moment loses nothing and is finished when it runs again.
- LS-19 Catastrophe: A 2.0 library is not opened or written by this Amaze until the user chose to convert it.

## Severe

- LS-20 Severe: When the library's policy cannot be read, saving over an existing asset is not allowed.

## Wrong output

- LS-30 Wrong output: With no user selected, the library takes no change at all.
- LS-31 Wrong output: A user's favorites and folder list are their own: one user's change never alters another user's, except that a file's favorites go the same way as its comments, for everyone: moved with it, and dropped when it is deleted or its folder is removed.
- LS-32 Wrong output: Every shared entry records which user changed it last, and when.
- LS-33 Wrong output: What another session saved appears here without a restart.
- LS-34 Wrong output: The library records the format this Amaze writes, and shows its format as 3.x.
- LS-35 Wrong output: Shared settings hold one plain value per name, and a cleared one is gone.
- LS-36 Wrong output: Every asset has its own folder, `<name>__<id>` in its section's folder, holding all its files: record, network, picture, textures, downloaded sources, the pictures pasted into its comments, and a material's versions. A material or node has it from its first save, a snippet or color from its first file; renaming it renames its folder in the same save.
- LS-37 Wrong output: A saved material keeps its own copy of every texture it uses and names it in its own folder, so a copy or an import of it never uses another material's texture.
- LS-38 Wrong output: A texture path saved in the 2.0 layout is read as the same file in the material's own folder.
- LS-39 Wrong output: Deleting an asset moves its whole folder to the trash.
- LS-40 Wrong output: A picture pasted into an asset's comment is kept in that asset's folder and still shows after the asset is renamed; the comment text stays in its section's database.
