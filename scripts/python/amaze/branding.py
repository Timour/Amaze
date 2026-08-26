"""Single source of truth for the app's DISPLAY name, tagline and two version stamps - a rename reaches everything the user sees through Python, but NOT `assetlib_id` or the .pypanel label. ▸p/branding-stamps"""

APP_NAME = "Amaze"    # change this to rename the app

APP_TAGLINE = "Browse it, save it, drag it."    # one-line subtitle, shown under the name in the panel and docs

APP_VERSION = "1.0.10"    # the RELEASED version, MAJOR.MINOR.PATCH ▸p/version-scheme

LIBRARY_FORMAT = 2    # the ON-DISK stamp: an older build opening a library stamped ahead of this latches read-only. Bump ONLY when the on-disk shape changes ▸p/branding-stamps

