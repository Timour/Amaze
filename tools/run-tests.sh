#!/bin/bash
# Runs the whole suite from any directory against the dev tree.
# PROVE, THEN SHIP - the suite runs against a SCRATCH install and the
# live sync happens only after a full green run. KEEP THAT ORDER.
# Inside hython the package file OVERRIDES an exported $AMAZE, so
# reaching scratch means skipping the package and rebuilding its two
# effects by hand. A subset or module run never promotes.
# Prose archived: AmazeNotes/code-prose.md ▸ run-tests.sh
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=tools/houdini-env.sh
. "$repo/tools/houdini-env.sh"

# Resolved BEFORE $AMAZE is repointed at scratch, with the commit the
# suite is about to prove - so a commit landing mid-run cannot ship.
live_amaze="${AMAZE:-}"
gate_head="$(git -C "$repo" rev-parse HEAD 2>/dev/null || echo none)"

scratch="$(mktemp -d "${TMPDIR:-/tmp}/amaze_gate_install.XXXXXX")"
trap 'rm -rf "$scratch"' EXIT
AMAZE_SYNC_NO_VERIFY=1 AMAZE_SCRATCH_INSTALL="$scratch" \
    "$repo/tools/sync-install.sh" >/dev/null
export AMAZE="$scratch"
export HOUDINI_PACKAGE_SKIPLIST="Amaze"
# Headless decided HERE, not by whichever module imports first: the
# first QApplication picks the Qt platform for the whole process, and
# the native one answers different fonts and geometry, so an unguarded
# module fails asserts in OTHER modules. ▸p/first-app-picks-the-platform
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}"
# `;` is portable; `:` is Unix-only and on Windows swallows the whole
# string as one entry, so `&` never expands and `$HH` leaves the path
# (research.md - the portable HOUDINI_PATH separator).
export HOUDINI_PATH="$scratch;&"

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

# --all-versions: EVERY installed Houdini, not just the newest. Bugs
# here are version-specific and the default run follows whichever
# install is newest, so a green suite can mean the other major never ran.
if [ "${1:-}" = "--all-versions" ]; then
    shift
    overall=0
    found=0
    # DEAD COVER: skips are intersected across hosts, because a test
    # skipped on EVERY host protects nothing while reading as coverage.
    # Only this branch can ask - one run cannot tell the two apart.
    reports_dir="$(mktemp -d "${TMPDIR:-/tmp}/amaze_skips.XXXXXX")"
    trap 'rm -rf "$reports_dir"' EXIT
    reports=""
    # A SUBSET MUST NOT ANSWER THIS: intersecting two partial runs says
    # "nothing dead" about modules that were never loaded.
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
        # Through amaze_python, never the shebang - Windows has no
        # executable bit to honour.
        checker_python="$(amaze_python || echo python3)"
        # Unquoted on purpose - a space-separated list of paths this
        # script built itself, under a mktemp dir with no spaces.
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
