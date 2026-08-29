#!/bin/bash
# Runs the hython test modules from anywhere.  HFS=/opt/hfs22.0 ./start_test.sh
# Prose archived: AmazeNotes/code-prose.md ▸ start_test.sh

set -e

# BEFORE any cd - dirname "$0" only means anything from the original cwd.
tests_dir="$(cd "$(dirname "$0")" && pwd)"

# shellcheck source=../../../../tools/houdini-env.sh
. "$tests_dir/../../../../tools/houdini-env.sh"

# ARGUMENTS FIRST, before Houdini is looked for, so a typo costs no
# interpreter start. NEVER refuse a named module and send the caller to a
# bare `hython -m unittest`: that skips the sync, the isolated log dir,
# the lint and the leak check. An unknown name is an ERROR, never an
# empty run - a subset that silently shrinks reads as a run that passed.
isolated=0
if [ "${1:-}" = "--isolated" ]; then
    isolated=1
    shift
fi
wanted_modules=""
if [ $# -gt 0 ]; then
    missing=""
    for module in "$@"; do
        # `[ ] || assign` ends 0 either way, so errexit-safe. ▸r/shell-errexit
        [ -f "$tests_dir/$module.py" ] || missing="$missing $module"
    done
    if [ -n "$missing" ]; then
        echo "start_test.sh: no such test module(s):$missing" >&2
        echo "Modules are <name>.py in $tests_dir" >&2
        exit 2
    fi
    wanted_modules="$*"
fi

# The suite gets its OWN debug log, or tests that raise on purpose write
# genuine-looking crash records into the real one. `debug.py` reads this
# once at import, so exporting it here reaches every module.
# A FULL TEMPLATE, never `-t <prefix>`: `-t` is a prefix to BSD mktemp and
# a deprecated template to GNU's, which refuses one carrying no X.
AMAZE_LOG_DIR="$(mktemp -d "${TMPDIR:-/tmp}/amaze_test_log.XXXXXX")"
export AMAZE_LOG_DIR
trap 'rm -rf "$AMAZE_LOG_DIR"' EXIT

# THE SANDBOX: armed, every JSON write outside a temp dir is refused
# BEFORE it lands, rather than asserted after.
export AMAZE_SANDBOX=1

# Where the real log ENDS before the run, so the leak check reads only
# what this run appended. Stdlib only - Houdini is not set up yet here.
python="$(amaze_python || echo python3)"
real_log="$("$python" "$tests_dir/check_log_leak.py" --path 2>/dev/null || true)"
before=0
if [ -n "$real_log" ] && [ -f "$real_log" ]; then
    before="$(wc -c <"$real_log" | tr -d ' ')"
fi

# Find Houdini rather than demanding $HFS - a hook or a sync script
# inherits almost no environment.
if [ -n "${AMAZE_HOUDINI:-}" ]; then
    HFS="$AMAZE_HOUDINI"
    # A DRIVE LETTER CANNOT RIDE IN PATH: it splits on the colon, so
    # `C:/...` shatters into two dead entries and hython vanishes.
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

# NAME the host: the newest install wins, so updating Houdini silently
# moves the gate and these bugs are version-specific. $AMAZE_HOUDINI pins
# one; `run-tests.sh --all-versions` runs every one in turn.
hython -c 'import hou, sys; print("suite host: Houdini %s, Python %s"
          % (hou.applicationVersionString(), sys.version.split()[0]))' \
    2>/dev/null | grep "suite host:" || \
    echo "suite host: UNKNOWN - hython could not report its version"

status=0
# A secondary net only: shellcheck catches NO form of the silent `set -e`
# abort. test_shell_gates.py and the DONE markers are the real defence.
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
test_headless_dialogs \
test_versions test_grid_scroll test_file_section test_notes \
test_repair test_toolbar_filter test_shaderball_assets \
test_cancel_conversions \
test_list_columns test_designed_dialog test_no_live_data test_screen_dpr \
test_write_ordering test_thumbnail_paths test_panel_correctness \
test_prefs_and_sources test_prefs_shared test_prefs_per_user test_unbound_names test_conversion test_keyed_store test_library_prefs test_area_bindings test_grid_order test_sidebar_area test_sidebar_order test_toolbar_area test_comments_area test_grid_operations test_grid_badges test_sidebar_colour test_grid_menu test_sidebar_menu test_grid_columns test_matx_translate \
test_redshift_terminal test_dead_cover test_updater test_preview_boundary \
test_empty_state test_role_numbers test_comment_budget test_ui_labels \
test_design_document test_drawn_binding test_messages \
test_fresh_library test_grouped_import test_row_addressing \
test_device_pixmap test_switch_rereads test_upgrade_tool \
test_fixture_guard test_packages test_texstore test_event_pumps \
test_bug_report"

# Vulkan viewport multithreading OFF, every platform: ten panel modules
# crash 10/10 with it on. Suite-only - a live Houdini keeps its defaults.
# ▸r/vulkan-threading
export HOUDINI_VULKAN_VIEWER_MULTITHREADING=0
echo "suite: viewport draw single-threaded for this run" \
     "(HOUDINI_VULKAN_VIEWER_MULTITHREADING=0)"

# ONE hython process by default, which is what makes gating every sync
# and push on the FULL suite affordable. `--isolated` restores the
# per-module run - weaker isolation, so reach for it on a failure you
# suspect is cross-module pollution, and re-check before a release.
if [ -n "$wanted_modules" ]; then
    run_modules="$wanted_modules"
    echo "SUBSET RUN: NOT the full gate - run with no arguments before"
    echo "pushing.  Modules: $run_modules"
else
    run_modules="$MODULES"
fi

# `run_suite.py`, never `-m unittest`: it owns its exit, so a helper
# wedged in uninterruptible I/O cannot hang the run after printing OK.
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
