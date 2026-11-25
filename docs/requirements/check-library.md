# Check Library: requirements

What checking and repairing a library must do. Preferences ▸ Library ▸ Check and the Check Library
shelf tool show one report with the same fixes. The library is 3.0: each material and node in its
own folder. The levels and the rules for tests are in the [README](README.md).

## Catastrophe

- CL-01 Catastrophe: Checking changes nothing: the report alone writes, moves and removes nothing.
- CL-02 Catastrophe: No fix deletes: everything a fix takes away goes to the library's trash under its old path, and a database it replaces, an unreadable one included, is kept in `backup/` first.
- CL-03 Catastrophe: Each fix is applied whole or not at all, and only to what the check showed: a file or row that changed or appeared since is left alone.
- CL-04 Catastrophe: Nothing is trashed while the check is incomplete: while any database or asset folder cannot be read, is missing or empty, or a change is still being written to the library.
- CL-05 Catastrophe: A listed asset's folder is never trashed, nor an unlisted asset folder whose record can still recover it.
- CL-06 Catastrophe: A row whose files are missing stays, with the files it still has; it is removed only after a confirmation that names it.
- CL-07 Catastrophe: Unknown files and folders, and Code and Colors folders no database lists, are trashed only after a confirmation that names each one; Skip These keeps them and does the rest. A Materials or Nodes folder no database lists is never named there: Recover lists it.
- CL-08 Catastrophe: No fix runs unless the user chose it; Cancel, Return and Esc change nothing at any step.
- CL-09 Catastrophe: While this Houdini has the library open in a panel, Check Library from the shelf only reports.
- CL-10 Catastrophe: Restoring a backup brings back every asset saved after it from its record, and brings assets changed after it up to date.
- CL-11 Catastrophe: Rebuilding a database from records keeps every asset whose record can be read, in the section whose folder holds it.
- CL-12 Catastrophe: Repairing a library other than the open one never writes to the open one.
- CL-13 Catastrophe: Only the File section's favorites are checked against the disk; a material, node, code or color favorite is never removed.
- CL-14 Catastrophe: A File location whose folder is not on this computer is set aside, keeping its id, comments, tile pictures and favorites, which come back with the folder; a location on a drive that is not connected is left as it is.
- CL-15 Catastrophe: The user's files in `import/`, comment pictures, version stores and the system's folder-icon files are never leftovers or unknown.
- CL-16 Catastrophe: Code and Colors rows are never checked for files, and never changed.

## Wrong output

- CL-20 Wrong output: The report gives each database's state and what it holds, its backups when it is in trouble, and a database holding under half of its newest backup.
- CL-21 Wrong output: The report names rows whose files are missing (a file still syncing looks the same), rows with no category, unlisted asset folders and which can be recovered, leftovers, conflict copies left where they are, unknown files and folders, locations not on this computer, favorites of missing files, and what the trash holds.
- CL-22 Wrong output: Recover, which Fix All runs first, lists every Materials or Nodes asset folder no database lists in its section's database, with the name, category and tags of its record; one whose record cannot be read becomes "Recovered <id>" in the category Recovered. Fix Safe, which runs Recover, is offered whenever there is such a folder, its record read or not.
- CL-23 Wrong output: A sync service's copy is a leftover only when it matches its original, and a scratch file only once it is an hour old.
- CL-24 Wrong output: A version file its ledger does not list is an orphaned file, never a version.
- CL-25 Wrong output: Put in Uncategorized gives every item with no category the category Uncategorized; a name with a comma is kept whole.
- CL-26 Wrong output: When a library with a corrupt Materials or Nodes database opens, or is switched to, Repair is offered: restore a backup or rebuild from records, whichever the user picks.
- CL-27 Wrong output: After a fix, the library is read again and the panel shows the change without a restart.
- CL-28 Wrong output: `tools/library-audit.py` lists what does not belong in a library, by kind; it changes nothing and runs without Houdini.
- CL-29 Wrong output: An asset folder no database lists that holds only scratch files, or nothing, is a leftover, not an asset: Recover and a rebuild never make it a row, and Fix All trashes it whole once it is an hour old.
- CL-30 Wrong output: Preferences' Check Database row shows one state of the check: a red light and Repair, which runs Fix All, when Repair has something to fix; a yellow light and Fix, which only puts rows with no category in Uncategorized, when that is all it found; a yellow light and Check when it found only what no fix puts right, or could not check a part; a green light and Check when it found nothing. The light's tip names every finding.
- CL-31 Wrong output: Restoring a backup or rebuilding from records keeps each asset in its category, using the category name in its record.
- CL-32 Wrong output: An asset whose category is missing from the list counts as having no category, and Fix puts it in Uncategorized.
