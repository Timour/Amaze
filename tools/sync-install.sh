#!/bin/bash
# Sync the dev tree into the live Houdini install. Runnable from ANY
# directory: it resolves the repo from its own location and the install
# from $AMAZE (or the Houdini package file that defines it), so a wrong
# working directory cannot half-copy or silently no-op - which is
# exactly how "rsync from the wrong cwd" kept wasting runs.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Where Houdini is, and how to mirror a tree. One resolver, because this
# script alone had grown two copies of the lookup.
# shellcheck source=tools/houdini-env.sh
. "$repo/tools/houdini-env.sh"

install="${AMAZE:-}"
if [ -z "$install" ]; then
    # The LAST readable package file wins - amaze_package_files yields
    # them newest-last, and on macOS there is only ever one. The path is
    # passed as an ARGUMENT, not interpolated into the source: a Windows
    # package path is full of backslashes, and one of them inside a
    # Python string literal is an escape.
    while IFS= read -r pkg; do
        [ -n "$pkg" ] || continue
        found="$("$(amaze_python || echo python3)" -c "
import json,sys
for e in json.load(open(sys.argv[1])).get('env', []):
    if 'AMAZE' in e:
        print(e['AMAZE']); break
" "$pkg" 2>/dev/null || true)"
        if [ -n "$found" ]; then install="$found"; fi
    done < <(amaze_package_files)
fi
if [ -z "$install" ] || [ ! -d "$install" ]; then
    echo "sync-install: cannot find the install (set \$AMAZE)" >&2
    exit 1
fi

# The push gate is per-CLONE config, so a fresh clone silently has no
# gate until someone runs one command. Anything that syncs or tests
# passes through here, so wire it here rather than trusting a doc.
if git -C "$repo" rev-parse --git-dir >/dev/null 2>&1 \
   && [ "$(git -C "$repo" config --get core.hooksPath 2>/dev/null)" != "tools/git-hooks" ]; then
    git -C "$repo" config core.hooksPath tools/git-hooks
    echo "sync-install: wired the pre-push gate (core.hooksPath)"
fi

amaze_mirror "$repo/scripts" "$install/scripts" '__pycache__'
amaze_mirror "$repo/python_panels" "$install/python_panels"
amaze_mirror "$repo/toolbar" "$install/toolbar"
cp "$repo/OPmenu.xml" "$install/OPmenu.xml"
# BYTECODE: purge, then rebuild HASH-VALIDATED.
#
# The old rule was "never cache bytecode", because a synced .py can
# arrive with a preserved or older mtime, and timestamp-validated .pyc
# then looks current while holding the PREVIOUS version - measured, and
# it crashed the panel with no interface. Correct diagnosis, blunt cure:
# it made every panel open recompile ~42k lines from source, three times
# over (the import, the reload chain, the pypanel's own reload).
#
# Hash-validated .pyc (PEP 552) removes the CAUSE instead. The check is
# the source's content hash, so an mtime that lies proves nothing and a
# real edit still invalidates. Probed 2026-08-02 under hython: a module
# imported with its mtime forced to 1970 loaded from cache and returned
# the CURRENT value, and a genuine content edit under the same stale
# mtime still re-compiled. Measured on this package: 372ms -> 115ms.
#
# --force matters: it overwrites any timestamp-validated .pyc left in
# the install from before this change, which is the one file that could
# still lie. Compiled with the SAME interpreter Houdini runs, or the
# magic number would not match and every file would be recompiled at
# import anyway.
find "$install" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
_hython=""
if [ -n "${HFS:-}" ]; then
    _hython="$(amaze_hython "$HFS" || true)"
fi
if [ -z "$_hython" ]; then
    _root="$(amaze_newest_houdini)"
    if [ -n "$_root" ]; then _hython="$(amaze_hython "$_root" || true)"; fi
fi
if [ -n "$_hython" ] && [ -x "$_hython" ]; then
    "$_hython" -c "
import compileall, py_compile, sys
ok = compileall.compile_dir(
    '$install/scripts', quiet=1, force=True,
    invalidation_mode=py_compile.PycInvalidationMode.CHECKED_HASH)
sys.exit(0 if ok else 1)
" && echo "sync-install: bytecode rebuilt (hash-validated)" \
      || echo "sync-install: bytecode compile failed - the install still works, it just recompiles at load" >&2
else
    echo "sync-install: no hython found - skipping bytecode precompile" >&2
fi

# Verify the whole of scripts/, not just python/amaze: the rsync above
# copies "$repo/scripts/", so anything added beside python/amaze would
# ship UNVERIFIED. Latent today (scripts/ holds only python/amaze), and
# the cheapest possible moment to close it.
if diff -rq "$repo/scripts" "$install/scripts" \
        --exclude=__pycache__ >/dev/null \
   && diff -rq "$repo/python_panels" "$install/python_panels" >/dev/null \
   && diff -rq "$repo/toolbar" "$install/toolbar" >/dev/null \
   && diff -q "$repo/OPmenu.xml" "$install/OPmenu.xml" >/dev/null; then
    echo "sync-install: $install is identical to the repo"
else
    echo "sync-install: MISMATCH after sync - investigate" >&2
    exit 1
fi

# ---------------------------------------------------------------------
# VERIFY WHAT WAS JUST SHIPPED.
#
# This is the path that reaches a live Houdini. The pre-push hook gates
# `git push`, which changes nobody's working environment; THIS changes
# the one that matters, and it had no check at all - a broken build
# would sit in the install until someone happened to open the panel.
#
# It cannot refuse before syncing: the suite reads $AMAZE, so the tests
# only mean anything AFTER the sync. So it syncs, then tests, then says
# loudly what it just did - and names the one command that undoes it.
#
# run-tests.sh sets AMAZE_SYNC_NO_VERIFY to break the recursion (it
# syncs first, then runs the same suite itself).
# ---------------------------------------------------------------------
if [ -n "${AMAZE_SYNC_NO_VERIFY:-}" ]; then
    exit 0
fi

if ! command -v hython >/dev/null 2>&1 && [ -z "${HFS:-}" ]; then
    # The old form here was a bare `ls -d <glob>`, which under
    # `set -euo pipefail` exits non-zero when nothing matches and killed
    # this script with NO OUTPUT - on a fresh machine with no Houdini,
    # the exact case these lines exist to handle. amaze_newest_houdini
    # returns an empty string instead, which the check below can report.
    HFS="$(amaze_newest_houdini)"
    export HFS
fi
if ! command -v hython >/dev/null 2>&1 && [ ! -d "${HFS:-}" ]; then
    echo "sync-install: REFUSING to report success - no Houdini found," >&2
    echo "  so the code just shipped to the install was never tested." >&2
    exit 1
fi

echo "sync-install: verifying what was just shipped..."
# set +e, not `|| true`: this runs under `set -e`, so a failing suite
# aborts here before the check below - silently. But `|| true` also
# THROWS AWAY the exit status, and then "no FAILED line" reads as
# green. A licence hiccup, a crash inside the runner, or a `set -e`
# abort all produce no FAILED line and no tests. Check all three
# conditions the push gate checks: status, FAILED, and a log leak.
set +e
out="$(bash "$repo/scripts/python/amaze/tests/start_test.sh" 2>&1)"
rc=$?
set -e
# `|| true` on every one: grep -c EXITS 1 when the count is zero, so
# under `set -e` a perfectly green suite kills the script right here -
# after printing "verifying...", before printing anything else. That
# is the third variant of this same trap today (the others: a failing
# command substitution, and a `[ ] && echo` that returns 1).
failed="$(printf '%s\n' "$out" | grep -cE '^FAILED( \(|$)' || true)"
leak="$(printf '%s\n' "$out" | grep -c 'LOG LEAK' || true)"
# The NUMBER, not the number of matching lines: "Ran 0 tests" is a
# line, so counting lines made an empty suite look like it had run.
ran="$(printf '%s\n' "$out" | sed -n 's/^Ran \([0-9][0-9]*\) test.*/\1/p' | tail -1 || true)"
ran="${ran:-0}"
if [ "$rc" -ne 0 ] || [ "$failed" -ne 0 ] || [ "$leak" -ne 0 ] || [ "$ran" -eq 0 ]; then
    echo >&2
    echo "=====================================================" >&2
    echo " SUITE FAILED - A BROKEN BUILD IS IN YOUR LIVE INSTALL" >&2
    echo "=====================================================" >&2
    # `|| true`: with no matching line, grep exits 1, pipefail carries it
    # past head, and set -e kills the script INSIDE the failure branch -
    # losing the rollback instructions below, in exactly the failures
    # that are hardest to diagnose. Same trap as three lines above.
    printf '%s\n' "$out" | grep -E '^(FAIL|ERROR):|^FAILED|LOG LEAK' | head -12 >&2 || true
    if [ "$ran" -eq 0 ]; then
        echo " The suite did not run at all (exit $rc)." >&2
    fi
    echo >&2
    echo " The live install now holds this failing build." >&2
    echo " Fix and re-run, or roll back with:" >&2
    echo "   cd $repo && git stash && tools/sync-install.sh" >&2
    echo >&2
    echo " (Auto-rollback was built and REMOVED: snapshotting the 113MB" >&2
    echo "  install cost 1m56s per sync against ~20s, and wrote a copy" >&2
    echo "  into the cloud-synced folder. Measured, not guessed.)" >&2
    exit 1
fi
echo "sync-install: suite green - the install is safe to open."
# END MARKER. Three bugs tonight made this script die partway and say
# nothing; the caller cannot tell "finished cleanly" from "aborted at
# line 40" by exit code alone under `set -e`. A terminal marker makes
# a silent abort detectable regardless of what caused it.
echo "sync-install: DONE"
