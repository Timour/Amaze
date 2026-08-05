#!/bin/bash
# Run the whole suite from ANY directory, against the DEV tree.
# Syncs first, because the install is what Houdini resolves for
# anything the tests reach through $AMAZE (resource tables, prefs).
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AMAZE_SYNC_NO_VERIFY=1 "$repo/tools/sync-install.sh" >/dev/null

# --all-versions: run the whole suite against EVERY installed Houdini,
# not just the newest. The project supports two majors, its bugs have
# been version-specific (a viewport pick that is correct on one build
# and 279px out on another), and the default single run silently
# follows whichever install is newest - so a green suite can mean the
# other version was never executed at all.
if [ "${1:-}" = "--all-versions" ]; then
    shift
    overall=0
    found=0
    for res in $(ls -d /Applications/Houdini/Houdini*/Frameworks/Houdini.framework/Versions/Current/Resources 2>/dev/null | sort -V); do
        found=$((found + 1))
        echo "==========================================================="
        echo "  $res"
        echo "==========================================================="
        AMAZE_HOUDINI="$res" bash "$repo/scripts/python/amaze/tests/start_test.sh" "$@" || overall=$?
    done
    if [ "$found" -eq 0 ]; then
        echo "no Houdini installs found" >&2
        exit 1
    fi
    exit "$overall"
fi

exec bash "$repo/scripts/python/amaze/tests/start_test.sh" "$@"
