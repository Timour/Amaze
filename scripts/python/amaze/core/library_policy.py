"""The library version this Amaze writes; an older Amaze's updater reads this file from a release."""

LIBRARY_VERSION = 4    # 4 is format 2.0: six databases, `backup/` and `trash/` in the library
LIBRARY_VERSION_SINCE = "1.40.0"    # the first released Amaze that reads it, quoted by Check for Updates
DATABASE_FORMAT = 5    # `branding.LIBRARY_FORMAT`, the `format` of each database; a test holds them equal
RECORD_FORMAT = 1    # `asset_record.FORMAT`, the `format` of each `<id>.json`; a test holds them equal
FORMAT_2_0 = (4, 5, 1)    # the three numbers at format 2.0; each step above one of them adds one to 2.x


def format_label(version: int, database: int = 0, record: int = 0) -> str:
    """The format the user reads: `2.<steps above 2.0>`; a library older than 2.0 its own number."""
    version = int(version or 0)
    if version < FORMAT_2_0[0]:
        return "%d" % version
    steps = sum(max(0, int(found or base) - base)
                for found, base in zip((version, database, record), FORMAT_2_0))
    return "2.%d" % steps
