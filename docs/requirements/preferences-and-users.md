# Preferences and users: requirements

What this computer's settings and the library's users must do. The engine is `prefs/prefs.py`,
`prefs/persistence.py`, `prefs/settings_store.py` and `core/users.py`. Shared settings are LS-35,
per-user stars and folder lists LS-31, no change without a user LS-30. The levels and the rules
for tests are in the [README](README.md).

## Catastrophe

- PR-01 Catastrophe: A write of settings.json cut off at any moment leaves it whole; one that cannot be read is kept as a copy and never written over.
- PR-02 Catastrophe: Deleting a user removes their favourites and folder list; it never removes or changes an asset, comment, picture or shared setting.

## Wrong output

- PR-20 Wrong output: Every setting saved reads back the same.
- PR-21 Wrong output: Two panes or two Houdini sessions on one computer saving settings keep each other's changes; neither undoes the other's library switch.
- PR-22 Wrong output: A damaged or unknown settings.json never stops the pane: Amaze opens without a library, and keys it does not know stay in the file.
- PR-23 Wrong output: View state is per user on this computer: each user gets their own back, a first pick keeps what is on screen, and with no user nothing per user is saved.
- PR-24 Wrong output: A user is an id with a name: no two users of a library share a name, ignoring case, and a rename changes the name only.
- PR-25 Wrong output: A deleted user's view state leaves this computer's settings at once and other computers' at their next save; a user of another library, or any user while the roster cannot be read, is never dropped.
- PR-26 Wrong output: The Library list holds each folder once, the last opened first; Add stops at 20; Remove from List never removes the open library and never touches a folder.
