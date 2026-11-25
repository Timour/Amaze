"""The library version this Amaze writes; an older Amaze's updater reads this file from a release."""

LIBRARY_VERSION = 6    # 6: each category under an id; 5 was format 3.0, one folder per asset
LIBRARY_VERSION_SINCE = "2.0.0"    # the first released Amaze that reads it, quoted by Check for Updates
LAYOUT_2_0 = 4    # the version of a 2.0 library, which is converted to 3.0 before it is opened
DATABASE_FORMAT = 6    # `branding.LIBRARY_FORMAT`, the `format` of each database; a test holds them equal
RECORD_FORMAT = 2    # `asset_record.FORMAT`, the `format` of each `<id>.json`; a test holds them equal
FORMAT_3_0 = (5, 5, 1)    # the three numbers at format 3.0; each step above one of them adds one to 3.x


def format_label(version: int, database: int = 0, record: int = 0) -> str:
    """The format the user reads: `3.<steps above 3.0>`; a 2.0 library `2.0`."""
    version = int(version or 0)
    if version < FORMAT_3_0[0]:
        return "2.0" if version == LAYOUT_2_0 else "%d" % version
    steps = sum(max(0, int(found or base) - base)
                for found, base in zip((version, database, record), FORMAT_3_0))
    return "3.%d" % steps
