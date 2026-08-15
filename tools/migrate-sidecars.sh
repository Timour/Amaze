#!/bin/bash
# Run migrate-sidecars.py under hython from any directory.
#
#   tools/migrate-sidecars.sh --dry-run     report, write nothing
#   tools/migrate-sidecars.sh               write the sidecars
#
# RUN IT ON H21. Redshift only builds to 21.0.729, so under H22 every
# rs_usd_material_builder .interface fails and the run silently skips
# the 220 assets it exists for. AMAZE_HOUDINI pins the install.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Sync first, as the suite does: the run reads the DEV tree, but
# anything reached through $AMAZE resolves to the INSTALL.
AMAZE_SYNC_NO_VERIFY=1 "$repo/tools/sync-install.sh" >/dev/null

# Its own log dir, so a 548-asset run stays out of the real debug log.
# debug.py reads $AMAZE_LOG_DIR once at import. Full template, not -t:
# GNU/MSYS mktemp refuses a -t template with no X's.
AMAZE_LOG_DIR="$(mktemp -d "${TMPDIR:-/tmp}/amaze_migrate_log.XXXXXX")"
export AMAZE_LOG_DIR
trap 'rm -rf "$AMAZE_LOG_DIR"' EXIT

# The ONE resolver - never hand-roll a Houdini lookup here.
# shellcheck source=tools/houdini-env.sh
. "$repo/tools/houdini-env.sh"

if [ -n "${AMAZE_HOUDINI:-}" ]; then
    HFS="$AMAZE_HOUDINI"
    export HFS
    if amaze_is_windows; then
        # cygpath first - a drive letter shatters PATH on its colon.
        PATH="$(cygpath -u "$HFS")/bin:$PATH"
    else
        PATH="$HFS/bin:$PATH"
    fi
    export PATH
elif ! command -v hython >/dev/null 2>&1 && [ -z "${HFS:-}" ]; then
    HFS="$(amaze_newest_houdini)"
    export HFS
    if amaze_is_windows && [ -n "$HFS" ]; then
        # MSYS-form root from the resolver is PATH-safe, and hython
        # needs no houdini_setup on Windows.
        PATH="$HFS/bin:$PATH"
        export PATH
    fi
fi

if ! command -v hython >/dev/null 2>&1; then
    if [ -z "${HFS:-}" ] || [ ! -d "$HFS" ]; then
        echo "hython not on PATH and no Houdini found - set HFS" >&2
        exit 1
    fi
    cd "$HFS"
    # nounset OFF across the source: houdini_setup reads unset
    # variables and aborts under -u before Houdini's env exists.
    set +u
    # shellcheck disable=SC1091
    source houdini_setup
    set -u
fi

exec hython "$repo/tools/migrate-sidecars.py" "$@"
