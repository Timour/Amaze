# Updates and the library's version: requirements

What Check for Updates, installing an update, and what the user is told about the library's format
must do. The engine is `core/updater.py`, `dialogs/update_dialog.py`, the version steps of
`actions/library.py` and `pane/library.py`, and the Library page's format line in
`dialogs/prefs_window.py`. Conversion to 3.0 and the format shown as 3.x are in
[library storage](library-storage.md). The levels and the rules for tests are in the
[README](README.md).

## Catastrophe

- UP-01 Catastrophe: An update that fails or is cut off at any moment, by Esc, a full disk or a crash, leaves one whole Amaze installed, the old one or the new one, and no half-copied files; only a crash in the instant between the swap's two renames leaves the old one whole beside the install, as `<install>.replacing`.
- UP-02 Catastrophe: A download is installed only when it is complete and matches the size and checksum the release published.
- UP-03 Catastrophe: Nothing from a release is written outside the update's own folder, and a download or archive bigger than a release can be is refused before it fills the disk.
- UP-04 Catastrophe: An update installs only Amaze's own files (`scripts`, `python_panels`, `toolbar`, `OPmenu.xml`), and a release missing one of them is not installed.
- UP-05 Catastrophe: An update keeps every installed add-on; when they cannot be copied, nothing is installed.
- UP-06 Catastrophe: An update that changes the library's format is installed only after a warning naming the oldest Amaze that can still open the library, and only on Continue, wherever it was started; Cancel, Esc and Return install nothing.
- UP-07 Catastrophe: An older Amaze can always learn which library format a release brings: `core/library_policy.py` keeps its path and its `LIBRARY_VERSION`, `LIBRARY_VERSION_SINCE`, `DATABASE_FORMAT` and `RECORD_FORMAT` lines.
- UP-08 Catastrophe: A library older than 2.0 is never marked as 3.0.

## Severe

- UP-10 Severe: After an update is installed, the running Houdini keeps working until it restarts, and the user is told to restart.

## Wrong output

- UP-20 Wrong output: Amaze looks for an update only when the user asks, with one call to the release list, and a check never installs anything.
- UP-21 Wrong output: Only a release newer than this Amaze is offered, versions compared as numbers (1.10 is newer than 1.9); a release list that cannot be reached, or holds no release, says so.
- UP-22 Wrong output: The offer says whether the library's format will change and to which, counting a step in the database or record format too; when the release's format cannot be read, no change is announced.
- UP-23 Wrong output: Opening a 3.x library that an older Amaze wrote records this Amaze's format at once, with no question.
- UP-24 Wrong output: A library a newer Amaze wrote is not opened; the library open before stays open and named in the settings, and Update Amaze is offered once Houdini is idle.
- UP-25 Wrong output: Before Apply, Preferences ▸ Library says what Apply will do to the picked library: nothing, update it to this Amaze's format, or nothing until Amaze is updated, in which case Apply is refused; an open Preferences shows the new format after an update.
