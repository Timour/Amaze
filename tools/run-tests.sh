#!/bin/bash
# Run the whole suite from ANY directory, against the DEV tree.
# Syncs first, because the install is what Houdini resolves for
# anything the tests reach through $AMAZE (resource tables, prefs).
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=tools/houdini-env.sh
. "$repo/tools/houdini-env.sh"
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
    # THE DEAD-COVER CHECK RIDES ALONG (2026-08-09). Each run records
    # which tests it SKIPPED; afterwards they are intersected, because a
    # test skipped on EVERY host protects nothing and still reads as
    # coverage. Only this branch can ask it - one run cannot tell a
    # correct skip from a dead one.
    reports_dir="$(mktemp -d "${TMPDIR:-/tmp}/amaze_skips.XXXXXX")"
    trap 'rm -rf "$reports_dir"' EXIT
    reports=""
    # A SUBSET RUN MUST NOT ANSWER THIS. Intersecting two partial runs
    # says "nothing dead" about the modules that were never loaded,
    # which is the false green this whole check exists to remove.
    full_run=1
    [ $# -eq 0 ] || full_run=0
    while IFS= read -r res; do
        [ -n "$res" ] || continue
        found=$((found + 1))
        echo "==========================================================="
        echo "  $res"
        echo "==========================================================="
        report="$reports_dir/run-$found.json"
        AMAZE_HOUDINI="$res" AMAZE_SKIP_REPORT="$report" \
            bash "$repo/scripts/python/amaze/tests/start_test.sh" "$@" || overall=$?
        reports="$reports $report"
    done < <(amaze_houdini_roots)
    if [ "$found" -eq 0 ]; then
        echo "no Houdini installs found" >&2
        exit 1
    fi
    echo "==========================================================="
    if [ "$full_run" -eq 0 ]; then
        echo "  dead-cover check SKIPPED - subset run cannot answer it"
    elif [ "$found" -lt 2 ]; then
        echo "  dead-cover check SKIPPED - only one Houdini installed"
    else
        # Through amaze_python, never the shebang: Windows has no
        # executable bit to honour, and start_test.sh already resolves
        # its own helpers this way.
        checker_python="$(amaze_python || echo python3)"
        # Unquoted on purpose: $reports is a space-separated list this
        # script built from paths it made itself, under a mktemp dir
        # with no spaces in it.
        # shellcheck disable=SC2086
        "$checker_python" \
            "$repo/scripts/python/amaze/tests/check_dead_cover.py" $reports \
            || overall=$?
    fi
    exit "$overall"
fi

exec bash "$repo/scripts/python/amaze/tests/start_test.sh" "$@"
