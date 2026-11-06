import os as _os

PACKAGE_ROOT = _os.path.dirname(_os.path.abspath(__file__))    # the way to locate bundled files (ui/, res/); needs no environment


def package_file(*parts) -> str:
    """The absolute path of a file shipped inside this package; works without `$AMAZE`."""
    return _os.path.join(PACKAGE_ROOT, *parts)
