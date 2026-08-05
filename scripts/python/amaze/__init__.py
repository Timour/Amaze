import sys

# Never write .pyc caches AT RUNTIME. Half of a two-part arrangement,
# and the other half is in tools/sync-install.sh - read both or this
# line looks like the old "no bytecode at all" rule it replaced.
#
# The hazard is real: the install is file-synced between machines, and a
# synced .py can arrive with an mtime that makes an OLD __pycache__
# entry look current. Python then runs stale bytecode - "new UI, old
# behavior", and one hard crash with no interface.
#
# What changed 2026-08-02: the cure used to be "never cache", which cost
# a recompile of ~42k lines on every panel open (372ms, three times over
# on a first open). Now sync-install.sh precompiles the install with
# HASH-validated .pyc instead - PEP 552, where the check is the source's
# content hash, so a lying mtime proves nothing and a genuine edit still
# invalidates. Probed under hython: a module imported with its mtime
# forced to 1970 loaded from cache and returned the CURRENT value.
# Measured: 372ms -> 115ms.
#
# This flag stays True so that only sync-install ever writes a cache -
# a runtime write would be timestamp-validated and put the original
# hazard straight back. Reading is unaffected, which is what makes the
# precompiled caches work.
sys.dont_write_bytecode = True

# Environment-variable bridge: the package file defines $AMAZE (the
# current name) or $ASSETLIB (legacy installs) as the plugin root. The
# code and the parm-embedded "$AMAZE/..." resource paths need ONE of
# them reliably defined, so whichever the package set is mirrored onto
# the other here - this module runs before anything reads either.
# NOTE: "ASSETLIB" below is the deliberate legacy name, not a missed
# rename - keep it.
# Guarded: pure-python use (tests, offline tools) has no hou.
try:
    import hou

    _amaze = hou.getenv("AMAZE")
    _legacy = hou.getenv("ASSETLIB")
    if _amaze and not _legacy:
        hou.putenv("ASSETLIB", _amaze)
    elif _legacy and not _amaze:
        hou.putenv("AMAZE", _legacy)
    del _amaze, _legacy
except Exception:
    pass

import os as _os

#: Absolute path of this package on disk - THE way to locate bundled
#: files (ui/, res/). Four dialogs used to re-derive it from their own
#: __file__ each.
PACKAGE_ROOT = _os.path.dirname(_os.path.abspath(__file__))
