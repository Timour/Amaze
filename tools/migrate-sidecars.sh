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
# Full template, not -t: GNU/MSYS mktemp reads -t as a deprecated
# template and refuses one with no X's (research.md > Windows).
AMAZE_LOG_DIR="$(mktemp -d "${TMPDIR:-/tmp}/amaze_migrate_log.XXXXXX")"
export AMAZE_LOG_DIR
trap 'rm -rf "$AMAZE_LOG_DIR"' EXIT

# The ONE resolver, like every other caller - this was the last copy of
# the mac-only `ls -d` glob lookup (practice.md > A LOOKUP WRITTEN FOUR
# TIMES), left behind by the 2026-08-06 consolidation.
# shellcheck source=tools/houdini-env.sh
. "$repo/tools/houdini-env.sh"

if [ -n "${AMAZE_HOUDINI:-}" ]; then
    HFS="$AMAZE_HOUDINI"
    export HFS
    if amaze_is_windows; then
        # A drive-letter path shatters bash PATH on its colon
        # (research.md > Windows); cygpath first, like start_test.sh.
        PATH="$(cygpath -u "$HFS")/bin:$PATH"
    else
        PATH="$HFS/bin:$PATH"
    fi
    export PATH
elif ! command -v hython >/dev/null 2>&1 && [ -z "${HFS:-}" ]; then
    HFS="$(amaze_newest_houdini)"
    export HFS
    if amaze_is_windows && [ -n "$HFS" ]; then
        # MSYS-form root straight from the resolver - PATH-safe, and
        # hython needs no houdini_setup on Windows (research.md).
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
