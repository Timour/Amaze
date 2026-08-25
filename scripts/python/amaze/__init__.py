import sys

sys.dont_write_bytecode = True    # only sync-install.sh may write a cache, and it writes HASH-validated .pyc; a runtime write would be timestamp-validated and restore the stale-bytecode hazard ▸r/module-reload

import os as _os

PACKAGE_ROOT = _os.path.dirname(_os.path.abspath(__file__))    # THE way to locate bundled files (ui/, res/) - derived from this module's own location, so it needs no environment at all


def package_file(*parts) -> str:
    """The absolute path of a file shipped inside this package - THE one join, right in a test, in hython, and in a Houdini that never set `$AMAZE`."""
    return _os.path.join(PACKAGE_ROOT, *parts)
