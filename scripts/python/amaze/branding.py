"""
Single source of truth for the app's DISPLAY name and tagline.

Rename the app by editing APP_NAME here - it flows to every place the USER
sees the name through Python: the About dialog, the panel title + subtitle,
the save-dialog titles, the node right-click "Save to <name>" menu labels
(OPmenu.xml imports this), and the panel lookup in utils/rc_calls.py.

After the 2026-07-27 modernisation, ONE identifier remains deliberately
old, because it is stamped into every scene the user has ever saved and
cannot be migrated from here:

  * the ``assetlib_id`` node userdata key (re-save recognition). The
    saved archives in the library carry it too. Renaming it would make
    every existing scene node and asset unrecognisable; reading two key
    names forever is worse than one invisible old name.

Everything else was migrated that day with backward-compatible reads
or one-time renames: the python package (matlib -> amaze), the pypanel
file and its interface name (desktops patched), /obj/MatLib -> 
/obj/Amaze (zero materials carried a COP companion at the time), the
converter's uv-scale tag (legacy tag still honoured on old networks),
the debug log filename, and the library seed markers.

One spot Python cannot reach at load time, so it stays a manual edit on a
rename (kept to a single line, and called out here):

  * ``python_panels/Amaze.pypanel`` -> the ``label="..."`` attribute
    (Houdini reads the pane-tab label from the XML before any Python runs)

The console debug prefix ("Amaze: ...") is a plain literal by choice
(developer-facing, ~100 call sites); a future rename find/replaces it.
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

