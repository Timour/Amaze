#!/bin/bash
# Run migrate-sidecars.py under hython from any directory.
#
#   tools/migrate-sidecars.sh --dry-run     report, write nothing
#   tools/migrate-sidecars.sh               write the sidecars
#
# H21 by default is not incidental: the Redshift plugin only builds to
# 21.0.729, so under H22 every rs_usd_material_builder .interface fails
# to run and the migration would silently skip the 220 assets that are
# the entire reason it exists. AMAZE_HOUDINI pins a different install.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# The corpus check reads the DEV tree directly (migrate-sidecars.py inserts
# scripts/python on sys.path), but anything it reaches through $AMAZE -
# resource tables, the shipped starter library - resolves to the
# install, so the same sync-first rule as the suite applies.
AMAZE_SYNC_NO_VERIFY=1 "$repo/tools/sync-install.sh" >/dev/null

# Its own log directory. debug.py reads $AMAZE_LOG_DIR once at import,
# so exporting it here keeps a 548-asset run - which logs an import
# event per asset - out of the real debug log the live session uses.
AMAZE_LOG_DIR="$(mktemp -d -t amaze_migrate_log)"
export AMAZE_LOG_DIR
trap 'rm -rf "$AMAZE_LOG_DIR"' EXIT

if [ -n "${AMAZE_HOUDINI:-}" ]; then
    HFS="$AMAZE_HOUDINI"
    export HFS
    PATH="$HFS/bin:$PATH"
    export PATH
elif ! command -v hython >/dev/null 2>&1 && [ -z "${HFS:-}" ]; then
    HFS="$(ls -d /Applications/Houdini/Houdini*/Frameworks/Houdini.framework/Versions/Current/Resources 2>/dev/null | sort -V | tail -1)"
    export HFS
fi

if ! command -v hython >/dev/null 2>&1; then
    if [ -z "${HFS:-}" ] || [ ! -d "$HFS" ]; then
        echo "hython not on PATH and no Houdini found - set HFS" >&2
        exit 1
    fi
    cd "$HFS"
    # houdini_setup reads unset variables (tcsh among them), so nounset
    # has to come off across the source or it aborts before Houdini's
    # environment is ever established. start_test.sh avoids this by
    # never enabling -u at all; restoring it afterwards keeps the rest
    # of this script under the stricter setting.
    set +u
    # shellcheck disable=SC1091
    source houdini_setup
    set -u
fi

exec hython "$repo/tools/migrate-sidecars.py" "$@"
