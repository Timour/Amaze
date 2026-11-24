# Open and switch library: requirements

What opening a library, and switching to another, must do. The engine is the open sequence in
`pane/library.py`, `actions/library.py` and `core/model_registry.py`, with Apply in
`dialogs/prefs_window.py`. A newer library is LS-06, a 2.0 one LS-19, no change without a user
LS-30, Repair CL-26. The levels and the rules for tests are in the [README](README.md).

## Catastrophe

- SW-01 Catastrophe: After a switch, every write goes to the library now open: no row, category, icon, star or delete read from one library is written into another.
- SW-02 Catastrophe: A change still waiting to be saved when the library or the user is switched is saved in the library it was made in, as the user who made it.
- SW-03 Catastrophe: A new library is made only in an empty folder; a folder holding other files is refused and nothing is written to it.

## Wrong output

- SW-20 Wrong output: A library opens only with one of its own users selected, a new library's new user included; a user of another library counts as none, and nothing is written to it: no starters, no version stamp, no trash expiry, no folder icon.
- SW-21 Wrong output: A library that does not open, for any reason, or a Cancel, leaves the open library, its user and the settings as they were, and writes nothing.
- SW-22 Wrong output: Picking another library or user in Preferences changes nothing until Apply; Apply switches both together, once.
- SW-23 Wrong output: After a switch, every section's grid and sidebar show the new library as it is on disk, the grid filtered on the row its sidebar shows.
- SW-24 Wrong output: Panels on one library share one set of rows: one panel's save never undoes another's edit or delete, and a panel opened later joins the same set.
- SW-25 Wrong output: One section's database that cannot be read does not stop a switch: the others open, and saving into that one says why.
