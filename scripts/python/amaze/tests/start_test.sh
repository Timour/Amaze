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

# ARGUMENTS ARE CHECKED FIRST, before Houdini is even looked for, so a
# typo costs nothing instead of an interpreter start.
#
# NAMED MODULES RUN THROUGH THE FRONT DOOR (2026-08-05). Every argument
# except --isolated used to fall straight through to the full MODULES
# list, so `run-tests.sh test_grid_operations` ran all 55 and read as a
# targeted run that passed - two wasted full runs before the script was
# read. Refusing the argument was the first fix and it was the wrong
# one: it sends you to a bare `hython -m unittest`, which skips the
# sync, the isolated AMAZE_LOG_DIR, the shell lint and the log-leak
# check. Every guard, to save two minutes.
#
# A NAME THAT DOES NOT EXIST IS AN ERROR, not an empty run - a subset
# that silently shrinks is the exact shape this change is about.
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

# THE SANDBOX. Every JSON write in the package goes through
# hostos.write_json_atomic, and with this armed it refuses any path
# outside a temporary directory - loudly, with an exception. The suite
# already asserts afterwards that it touched no live data
# (test_no_live_data); this stops it BEFORE the write, which is the
# difference between an assertion and a guard. Added 2026-08-05, after a
# probe script wrote two files into the real synced library because it
# pointed a Prefs at a scratch directory one line after load().
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
        # No houdini_setup is sourced here. Windows ships
        # houdini_setup_bash, but hython.exe does not need it: with
        # $HFS/bin on PATH it imports hou and reports its own version
        # correctly (measured 2026-08-06 in Git Bash against 22.0.399).
        # One fewer thing sourced is one fewer way the two platforms can
        # end up in different environments.
        PATH="$HFS/bin:$PATH"
        export PATH
    else
        cd "$HFS"
        source houdini_setup
    fi
fi

cd "$tests_dir"

# NAME the environment in the output. The runner picks the newest
# installed Houdini, so updating Houdini silently MOVES the gate: on
# 2026-07-28 an update from 21.0.780/22.0.393 to 21.0.790/22.0.394 took
# the suite from Python 3.11 under H21 to Python 3.13 under H22 without
# a word, and "389 tests OK" meant something different afterwards. A
# green result has to say which host produced it - the project supports
# two Houdini versions and its bugs have been version-specific.
#
# AMAZE_HOUDINI=/path/to/Resources runs the suite against a specific
# install; tools/run-tests.sh --all-versions runs every one in turn.
hython -c 'import hou, sys; print("suite host: Houdini %s, Python %s"
          % (hou.applicationVersionString(), sys.version.split()[0]))' \
    2>/dev/null | grep "suite host:" || \
    echo "suite host: UNKNOWN - hython could not report its version"

status=0
# Lint the shell before running anything. It does NOT catch this
# project's recurring bug (a silent `set -e` abort - measured: it sees
# none of the three forms written on 2026-07-27), so it is a secondary
# net for quoting and word-splitting, not the primary defence. The
# primary defence is test_shell_gates.py plus the DONE markers.
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
test_drop_targets test_cop_root test_prefs_equality test_karma_batch \
test_nodes_section test_tile_icons test_category_colors \
test_shell_gates test_delegates test_folder_sections \
test_viewport_pick test_host_engines test_log_export \
test_hip_section test_library_policy test_atomic_write \
test_gradient_guard test_absent_database test_harness_reset \
test_db_hardening test_stale_proxy_index test_alert_sink \
test_versions test_grid_scroll test_file_section test_notes \
test_repair test_toolbar_filter test_shaderball_assets \
test_list_columns test_designed_dialog test_no_live_data \
test_write_ordering test_thumbnail_paths test_panel_correctness \
test_prefs_and_sources test_prefs_shared test_unbound_names test_conversion test_keyed_store test_library_prefs test_area_bindings test_grid_order test_sidebar_area test_toolbar_area test_comments_area test_grid_operations test_grid_badges test_sidebar_colour test_grid_menu test_sidebar_menu test_grid_columns test_matx_translate \
test_redshift_terminal test_dead_cover test_updater test_preview_boundary \
test_empty_state"

# Windows: the Vulkan viewport's multithreaded update/draw is switched
# off for the suite. Nine panel modules crashed hython inside Houdini's
# own draw - a TBB parallel phase exiting into viewport teardown - and
# the cause was isolated by measurement, not read off the stack: the
# same module crashes on NVIDIA, on AMD and on SwiftShader, and passes
# on all of them with this one variable off, so it is a thread race in
# the viewport code and not any GPU's driver (research.md > Windows).
# This replaced a nine-module exclusion; the suite is whole again.
# Suite-only on purpose - a live Houdini keeps its own defaults.
if amaze_is_windows; then
    export HOUDINI_VULKAN_VIEWER_MULTITHREADING=0
    echo "WINDOWS: viewport draw single-threaded for this run" \
         "(HOUDINI_VULKAN_VIEWER_MULTITHREADING=0)"
fi

# ONE hython process by default. The original measurement, when this
# was 13 modules and 203 tests: 13 separate launches cost ~110s,
# almost all of it Houdini starting up 13 times, against ~15s in one
# process. MODULES now holds 55 and the suite is 1537 tests at ~130s
# (2026-08-04) - the ratio is what matters and it has only grown,
# which is what makes it affordable to gate every sync and every push
# on the full suite instead of on a subset.
#
# --isolated restores the per-module run. Keep it for two cases: a
# failure you suspect is cross-module pollution (one process shares
# module state that separate processes do not), and anything that
# assumes a fresh interpreter. The shared run passes today, but it is
# strictly weaker isolation and worth re-checking before a release.
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

# run_suite.py, not `-m unittest`: same runner, same module names, but
# it leaves via os._exit once the result is in hand. A helper wedged in
# uninterruptible I/O used to make PySide's shutdown wait on it - three
# runs printed OK and then sat for eleven, twenty and twenty-six
# minutes. sys.path[0] is this directory either way, so the bare module
# names resolve exactly as before.
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
