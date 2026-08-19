#!/bin/bash
# Runs the hython test modules. Machine-agnostic: point $HFS at your
# Houdini install (or run from a shell where houdini_setup already ran),
# and run this script from anywhere - it locates the tests next to
# itself.
#
#   HFS=/opt/hfs22.0 ./start_test.sh

set -e

# Resolved BEFORE any cd: with a relative invocation, dirname "$0" is
# only meaningful from the original working directory.
tests_dir="$(cd "$(dirname "$0")" && pwd)"

# Where Houdini is. Shared with run-tests.sh, sync-install.sh and the
# pre-push hook - this file's own comment below records that three
# callers had each grown a private copy of the lookup.
# shellcheck source=../../../../tools/houdini-env.sh
. "$tests_dir/../../../../tools/houdini-env.sh"

# ARGUMENTS ARE CHECKED FIRST, before Houdini is looked for, so a typo
# costs nothing instead of an interpreter start.
#
# NAMED MODULES RUN THROUGH THE FRONT DOOR. Do not refuse an argument
# and send the user to a bare `hython -m unittest` - that skips the
# sync, the isolated AMAZE_LOG_DIR, the shell lint and the log-leak
# check. And a NAME THAT DOES NOT EXIST IS AN ERROR, never an empty
# run: a subset that silently shrinks reads as a run that passed.
isolated=0
if [ "${1:-}" = "--isolated" ]; then
    isolated=1
    shift
fi
wanted_modules=""
if [ $# -gt 0 ]; then
    missing=""
    for module in "$@"; do
        # `[ ] || assign` is errexit-safe mid-script either way
        # (research.md > Shell / set -e): the list ends 0 whether the
        # file is there or the assignment runs.
        [ -f "$tests_dir/$module.py" ] || missing="$missing $module"
    done
    if [ -n "$missing" ]; then
        echo "start_test.sh: no such test module(s):$missing" >&2
        echo "Modules are <name>.py in $tests_dir" >&2
        exit 2
    fi
    wanted_modules="$*"
fi

# The suite gets its OWN debug log. debug.py reads $AMAZE_LOG_DIR once
# at import, so exporting it here isolates every module in the run -
# including any that forgets to import test_support. Needed because the
# crash tier records tracebacks with Debug Mode OFF: tests that raise on
# purpose were writing genuine-looking crash records into the user's
# real log.
# An explicit template, not `-t <prefix>`: `-t` names a prefix to BSD
# mktemp and a deprecated template to GNU's, which refuses a template
# carrying no X characters - so the macOS form died on Git Bash with a
# `too few X` error before a single test ran. A full path ending in X
# characters is the one spelling both accept.
AMAZE_LOG_DIR="$(mktemp -d "${TMPDIR:-/tmp}/amaze_test_log.XXXXXX")"
export AMAZE_LOG_DIR
trap 'rm -rf "$AMAZE_LOG_DIR"' EXIT

# THE SANDBOX. Armed, hostos.write_json_atomic refuses any path outside
# a temporary directory, loudly. test_no_live_data asserts the same
# thing afterwards; this stops it BEFORE the write.
export AMAZE_SANDBOX=1

# Where the real log ENDS before the run. check_log_leak.py parses only
# what gets appended after this point, and attributes each record to the
# process that wrote it - so an open Houdini logging while the suite runs
# is not mistaken for a leak. Pure stdlib, no Houdini needed (it is not
# set up yet at this point).
python="$(amaze_python || echo python3)"
real_log="$("$python" "$tests_dir/check_log_leak.py" --path 2>/dev/null || true)"
before=0
if [ -n "$real_log" ] && [ -f "$real_log" ]; then
    before="$(wc -c <"$real_log" | tr -d ' ')"
fi

# Find Houdini rather than demanding the caller export $HFS. Three
# separate callers had grown their own copy of this; a git hook and a
# sync script inherit almost no environment, so "set HFS first" is a
# rule that gets forgotten exactly when it matters.
if [ -n "${AMAZE_HOUDINI:-}" ]; then
    # An explicit install wins over anything on PATH, so a caller can
    # pin the version the suite runs against.
    HFS="$AMAZE_HOUDINI"
    # A drive-letter spelling cannot ride in bash PATH - PATH splits on
    # the colon, so `C:/...` shatters into two dead entries and hython
    # is silently not found. cygpath makes either spelling safe.
    if amaze_is_windows && command -v cygpath >/dev/null 2>&1; then
        HFS="$(cygpath -u "$HFS")"
    fi
    export HFS
    PATH="$HFS/bin:$PATH"
    export PATH
elif ! command -v hython >/dev/null 2>&1 && [ -z "${HFS:-}" ]; then
    HFS="$(amaze_newest_houdini)"
    export HFS
fi

if ! command -v hython >/dev/null 2>&1; then
    if [ -z "${HFS:-}" ] || [ ! -d "$HFS" ]; then
        echo "hython not on PATH and no Houdini found - set HFS" >&2
        exit 1
    fi
    if amaze_is_windows; then
        # No houdini_setup on Windows: hython.exe does not need it with
        # $HFS/bin on PATH, and one fewer thing sourced is one fewer way
        # the platforms diverge.
        PATH="$HFS/bin:$PATH"
        export PATH
    else
        cd "$HFS"
        source houdini_setup
    fi
fi

cd "$tests_dir"

# NAME the environment in the output. The runner picks the NEWEST
# installed Houdini, so updating Houdini silently moves the gate - and
# the bugs here are version-specific, so a green result has to say which
# host produced it.
#
# AMAZE_HOUDINI=/path/to/Resources pins one install;
# tools/run-tests.sh --all-versions runs every one in turn.
hython -c 'import hou, sys; print("suite host: Houdini %s, Python %s"
          % (hou.applicationVersionString(), sys.version.split()[0]))' \
    2>/dev/null | grep "suite host:" || \
    echo "suite host: UNKNOWN - hython could not report its version"

status=0
# Lint the shell first. shellcheck catches NO form of the silent
# `set -e` abort, so it is a secondary net for quoting and
# word-splitting - test_shell_gates.py and the DONE markers are the
# real defence.
if command -v shellcheck >/dev/null 2>&1; then
    if ! shellcheck -S warning \
            "$tests_dir/start_test.sh" \
            "$tests_dir/../../../../tools/sync-install.sh" \
            "$tests_dir/../../../../tools/run-tests.sh" \
            "$tests_dir/../../../../tools/git-hooks/pre-push"; then
        echo "shell lint FAILED - fix before the suite runs" >&2
        exit 1
    fi
fi

MODULES="test_category test_library test_renders test_generator \
test_roundtrip test_thumbnail_shutdown test_debug_flood \
test_restore_drill test_lop_assign test_drag_gesture \
test_drop_targets test_drop_resolution test_cop_root \
test_prefs_equality test_karma_batch \
test_nodes_section test_tile_icons test_category_colors \
test_shell_gates test_delegates test_folder_sections \
test_viewport_pick test_host_engines test_log_export \
test_hip_section test_library_policy test_atomic_write \
test_gradient_guard test_absent_database test_harness_reset \
test_db_hardening test_stale_proxy_index test_alert_sink \
test_versions test_grid_scroll test_file_section test_notes \
test_repair test_toolbar_filter test_shaderball_assets \
test_cancel_conversions \
test_list_columns test_designed_dialog test_no_live_data test_screen_dpr \
test_write_ordering test_thumbnail_paths test_panel_correctness \
test_prefs_and_sources test_prefs_shared test_prefs_per_user test_unbound_names test_conversion test_keyed_store test_library_prefs test_area_bindings test_grid_order test_sidebar_area test_sidebar_order test_toolbar_area test_comments_area test_grid_operations test_grid_badges test_sidebar_colour test_grid_menu test_sidebar_menu test_grid_columns test_matx_translate \
test_redshift_terminal test_dead_cover test_updater test_preview_boundary \
test_empty_state test_role_numbers test_comment_budget test_ui_labels \
test_fresh_library test_grouped_import test_row_addressing \
test_device_pixmap"

# Vulkan viewport multithreading OFF for the suite, on every platform.
# Ten panel modules crash 10/10 with it on - Houdini's own heap misuse
# inside DM_VPortAgent::setupGeometry, not any GPU's, since NVIDIA, AMD
# and SwiftShader all crash and all pass with it off. macOS never met
# it because SideFX default the threading on for Linux and Windows
# only. Suite-only: a live Houdini keeps its own defaults.
# ▸r/vulkan-threading
export HOUDINI_VULKAN_VIEWER_MULTITHREADING=0
echo "suite: viewport draw single-threaded for this run" \
     "(HOUDINI_VULKAN_VIEWER_MULTITHREADING=0)"

# ONE hython process by default - separate launches cost almost all
# their time starting Houdini again, which is what makes it affordable
# to gate every sync and every push on the FULL suite.
#
# --isolated restores the per-module run. Keep it: the shared run is
# strictly weaker isolation, so reach for it on a failure you suspect
# is cross-module pollution, and re-check it before a release.
if [ -n "$wanted_modules" ]; then
    run_modules="$wanted_modules"
    # SAY it is a subset, every time. Both gates - pre-push and
    # sync-install - call with NO arguments, so a subset can never BE
    # the gate; this is so a green one is never mistaken for it.
    echo "SUBSET RUN: NOT the full gate - run with no arguments before"
    echo "pushing.  Modules: $run_modules"
else
    run_modules="$MODULES"
fi

# run_suite.py, not `-m unittest`: same runner and module names, but it
# leaves via os._exit once the result is in hand. Without that, a helper
# wedged in uninterruptible I/O makes PySide's shutdown wait on it and
# the run hangs for twenty minutes after printing OK.
if [ "$isolated" = "1" ]; then
    for module in $run_modules; do
        echo "---------------------------"
        echo "Testing $module"
        echo "---------------------------"
        hython "$tests_dir/run_suite.py" "$module" || status=$?
    done
else
    hython "$tests_dir/run_suite.py" $run_modules || status=$?
fi

echo "---------------------------"
"$python" "$tests_dir/check_log_leak.py" "$before" || status=1
exit "$status"
