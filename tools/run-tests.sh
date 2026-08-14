#!/bin/bash
# Run the whole suite from ANY directory, against the DEV tree —
# PROVE, THEN SHIP (2026-08-14, devlog #505).
#
# This script used to sync the LIVE install first and test after, so a
# red build — and every sabotage commit mid-cycle — was live in the
# cloud-synced install for the minutes it took to notice (#499's
# rider). Now the suite runs against a SCRATCH install and the live
# sync happens only after a FULL green run:
#
#   - the scratch sync reuses sync-install's own scratch mechanism,
#     so a dirty tree can still be TESTED while the live promote
#     keeps refusing it;
#   - inside hython the package file OVERRIDES an exported $AMAZE
#     (measured 2026-08-14: os.environ itself is rewritten to the
#     package value), so the suite reaches scratch by SKIPPING the
#     package (HOUDINI_PACKAGE_SKIPLIST) and rebuilding its two
#     effects by hand: $AMAZE and the HOUDINI_PATH entry;
#   - a SUBSET or module run never promotes — start_test.sh's "a
#     subset can never BE the gate" now holds for shipping too, where
#     the old order shipped before reading its arguments.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=tools/houdini-env.sh
. "$repo/tools/houdini-env.sh"

# The live target, resolved BEFORE $AMAZE is repointed at scratch —
# and the commit the suite is about to prove. Promote compares against
# it, so a commit landing mid-run can never ship untested.
live_amaze="${AMAZE:-}"
gate_head="$(git -C "$repo" rev-parse HEAD 2>/dev/null || echo none)"

scratch="$(mktemp -d "${TMPDIR:-/tmp}/amaze_gate_install.XXXXXX")"
trap 'rm -rf "$scratch"' EXIT
AMAZE_SYNC_NO_VERIFY=1 AMAZE_SCRATCH_INSTALL="$scratch" \
    "$repo/tools/sync-install.sh" >/dev/null
export AMAZE="$scratch"
export HOUDINI_PACKAGE_SKIPLIST="Amaze"
export HOUDINI_PATH="$scratch:&"

# Ship the proven build. Green is necessary but not sufficient: the
# live sync still refuses a dirty tree, because the suite just proved
# the WORKING TREE and only a committed tree may reach the install.
promote() {
    local now_head
    now_head="$(git -C "$repo" rev-parse HEAD 2>/dev/null || echo none)"
    if [ "$now_head" != "$gate_head" ]; then
        echo "run-tests: suite GREEN but HEAD moved during the run" >&2
        echo "  ($gate_head -> $now_head) - what was proven is not" >&2
        echo "  what would ship. The live install is unchanged; run again." >&2
        return 1
    fi
    if AMAZE="$live_amaze" AMAZE_SYNC_NO_VERIFY=1 \
       HOUDINI_PACKAGE_SKIPLIST="" HOUDINI_PATH="" \
       "$repo/tools/sync-install.sh" >/dev/null; then
        echo "run-tests: green — the live install now holds this build"
        return 0
    fi
    echo "run-tests: suite GREEN but the live sync REFUSED (dirty" >&2
    echo "  tree?). The live install is unchanged and this gate" >&2
    echo "  cannot vouch for HEAD — commit, then run again." >&2
    return 1
}

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
    if [ "$overall" -eq 0 ] && [ "$full_run" -eq 1 ]; then
        promote || overall=$?
    elif [ "$overall" -eq 0 ]; then
        echo "run-tests: green SUBSET — nothing shipped, the gate is the full run"
    fi
    exit "$overall"
fi

status=0
bash "$repo/scripts/python/amaze/tests/start_test.sh" "$@" || status=$?

# Promote only what the FULL suite proved: no module args, or
# --isolated alone (which still runs every module, one hython each).
if [ "$status" -eq 0 ]; then
    if [ $# -eq 0 ] || { [ "$1" = "--isolated" ] && [ $# -eq 1 ]; }; then
        promote || status=$?
    else
        echo "run-tests: green SUBSET — nothing shipped, the gate is the full run"
    fi
fi
exit "$status"
