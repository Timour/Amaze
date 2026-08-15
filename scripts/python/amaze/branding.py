"""
Single source of truth for the app's DISPLAY name and tagline.

Rename the app by editing APP_NAME here. It reaches every place the USER
sees the name through Python: the About dialog, the panel title and
subtitle, the save-dialog titles, the "Save to <name>" menu labels
(OPmenu.xml imports this) and the panel lookup in utils/rc_calls.py.

Two things a rename does NOT reach:

  * ``assetlib_id``, the node userdata key for re-save recognition. It
    is stamped into every scene already saved and into the library's
    archives. Leave it - reading two key names forever is worse.
  * ``python_panels/Amaze.pypanel``'s ``label="..."``, which Houdini
    reads before any Python runs. One manual edit.

The console debug prefix ("Amaze: ...") is a plain literal by choice -
developer-facing, ~100 call sites, find/replace on a rename.
"""

#: The app's display name. Change this to rename the app.
APP_NAME = "Amaze"

#: One-line subtitle / tagline, shown under the name in the panel + docs.
APP_TAGLINE = "Browse it, save it, drag it."

#: The released version. Shown in the About tab and in the debug log's
#: session header, so a bug report says which build it came from -
#: "latest commit is the version" stops working the first time someone
#: else reports one.
APP_VERSION = "1.0"

#: The LIBRARY FORMAT stamp, written into every database this build
#: saves. An older build that opens a library stamped AHEAD of what it
#: knows latches read-only and says so once, instead of writing into a
#: format it cannot understand. Bump this only when the on-disk shape
#: genuinely changes; the app version above moves freely without it.
#: 2 (2026-08-09): the tile-icon dual-write retired. A pick lives in
#: icons.json alone now, so a build that still reads it off the asset
#: record would show a stale pick or none - which is exactly what this
#: stamp exists to prevent, by opening such a library read-only and
#: saying to update.
LIBRARY_FORMAT = 2

