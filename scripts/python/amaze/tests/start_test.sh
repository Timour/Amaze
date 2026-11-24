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
        [ -f "$tests_dir/${module%%.*}.py" ] || missing="$missing $module"
    done
    if [ -n "$missing" ]; then
        echo "start_test.sh: no such test module(s):$missing" >&2
        echo "Modules are <name>.py in $tests_dir, a test <name>.<Class>.<test>" >&2
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
    HFS="$(amaze_houdini)"    # the production build, never a daily beside it
    export HFS
fi

# AMAZE_HOUDINI too: a hython started without houdini_setup runs plugins differently
# ▸r/octane-builder-removal-crash
if [ -n "${AMAZE_HOUDINI:-}" ] || ! command -v hython >/dev/null 2>&1; then
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
if ! "$python" "$tests_dir/../../../../tools/check-requirements.py"; then
    echo "requirements check FAILED - fix before the suite runs" >&2
    exit 1
fi

MODULES="test_asset_editing test_qt_models test_thumbnail_shutdown test_addons \
test_library_storage test_check_library test_karma_batch test_shell_gates test_file_moves \
test_hip_section test_harness_reset test_node_menu test_versions test_file_section \
test_shaderball_assets test_cancel_conversions test_qml_pane test_no_live_data \
test_thumbnail_paths test_panel_correctness test_conversion test_area_bindings \
test_grid_engine test_husk_job test_dead_cover test_empty_state test_snippet_run \
test_drop_into_scene test_info_pane test_material_conversion test_gallery_import \
test_fixture_guard test_packages test_saving_and_loading test_comments \
test_open_and_switch test_preferences_and_users test_log_and_alerts test_online_sources \
test_updates \
test_impact_map"

# NOT in a default run: the gate scripts' slower cases, each a hook in a
# throwaway repo, 5-20 s a test on Windows. A push that changes tools/ runs
# them (GATE_TESTS in tools/select-tests.py), and naming one runs it by hand.
# shellcheck disable=SC2034  # read by test_shell_gates and select-tests.py
GATE_MODULES="test_shell_gates_more"

# Vulkan viewport multithreading OFF, every platform: ten panel modules
# crash 10/10 with it on. Suite-only - a live Houdini keeps its defaults.
# ▸r/vulkan-threading
export HOUDINI_VULKAN_VIEWER_MULTITHREADING=0
# A houdini.env line beats the shell and silently re-armed the crash.
# ▸r/vulkan-threading
export HOUDINI_NO_ENV_FILE_OVERRIDES=1
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
    # A full run in one hython maps what each module runs, for run-tests.sh --affected.
    if [ "$isolated" = "0" ] && [ -z "${AMAZE_IMPACT_MAP:-}" ]; then
        common="$(git -C "$tests_dir" rev-parse --path-format=absolute \
            --git-common-dir 2>/dev/null || true)"
        [ -z "$common" ] || export AMAZE_IMPACT_MAP="$common/amaze-test-impact.json"
    fi
fi

# A subset's requirement tests run first on Houdini's own Python, seconds instead of a hython start.
# The full run stays in one hython, which maps every module. hython gets what needs Houdini.
ci_tests="$tests_dir/../../../../tools/ci-tests.py"
root="${HFS:-$(dirname "$(dirname "$(command -v hython)")")}"
if [ -n "$wanted_modules" ] && [ -f "$ci_tests" ] && fast="$(amaze_plain_python "$root")"; then
    left="$AMAZE_LOG_DIR/for-hython.txt"
    # shellcheck disable=SC2086  # a list of module names, split on purpose
    HFS="$root" "$fast" "$ci_tests" --rest "$left" $run_modules || status=$?
    run_modules="$(cat "$left" 2>/dev/null || printf '%s' "$run_modules")"
fi

# `run_suite.py`, never `-m unittest`: it owns its exit, so a helper
# wedged in uninterruptible I/O cannot hang the run after printing OK.
if [ -z "$run_modules" ]; then
    echo "suite: every test of this subset ran without Houdini"
elif [ "$isolated" = "1" ]; then
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
