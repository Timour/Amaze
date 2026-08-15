#!/bin/bash
# Sync the dev tree into the live Houdini install, from ANY directory:
# the repo resolves from this file's location and the install from
# $AMAZE, so a wrong cwd cannot half-copy or silently no-op.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Where Houdini is, and how to mirror a tree. The ONE resolver.
# shellcheck source=tools/houdini-env.sh
. "$repo/tools/houdini-env.sh"

install="${AMAZE:-}"
if [ -z "$install" ]; then
    # The LAST readable package file wins. Pass the path as an ARGUMENT,
    # never interpolated: a Windows package path is full of backslashes
    # and one of them inside a Python literal is an escape.
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

# A SABOTAGE GETS ITS OWN INSTALL - a different DESTINATION, never an
# exception to the committed-code rule below. Knowingly-broken code
# must not reach the real install even for the seconds it runs.
scratch=""
if [ -n "${AMAZE_SCRATCH_INSTALL:-}" ]; then
    scratch="$AMAZE_SCRATCH_INSTALL"
    if [ ! -d "$scratch" ]; then
        echo "sync-install: AMAZE_SCRATCH_INSTALL is not a directory:" >&2
        echo "    $scratch" >&2
        exit 1
    fi
    # REFUSE ANYTHING THAT COULD BE A REAL INSTALL. A typo here would
    # otherwise aim a sabotage at the one tree this is protecting, and
    # the marker means a populated directory is never overwritten.
    if [ "$scratch" = "$install" ]; then
        echo "sync-install: AMAZE_SCRATCH_INSTALL is the REAL install." >&2
        echo "  Refusing - a scratch install must be somewhere else." >&2
        exit 1
    fi
    if [ ! -e "$scratch/.amaze-scratch-install" ] \
       && [ -n "$(ls -A "$scratch" 2>/dev/null)" ]; then
        echo "sync-install: AMAZE_SCRATCH_INSTALL is not empty and carries" >&2
        echo "  no .amaze-scratch-install marker, so it is somebody's" >&2
        echo "  directory rather than a scratch one. Refusing:" >&2
        echo "    $scratch" >&2
        exit 1
    fi
    : > "$scratch/.amaze-scratch-install"
    install="$scratch"
    echo "sync-install: SCRATCH install at $install"
    echo "sync-install: the real install is NOT touched by this run"
fi

# The push gate is per-CLONE config, so a fresh clone silently has no
# gate until someone runs one command. Anything that syncs or tests
# passes through here, so wire it here rather than trusting a doc.
if git -C "$repo" rev-parse --git-dir >/dev/null 2>&1 \
   && [ "$(git -C "$repo" config --get core.hooksPath 2>/dev/null)" != "tools/git-hooks" ]; then
    git -C "$repo" config core.hooksPath tools/git-hooks
    echo "sync-install: wired the pre-push gate (core.hooksPath)"
fi

# THE INSTALL ONLY EVER RECEIVES COMMITTED CODE - it is the one tree a
# live Houdini reads, beside real libraries. Committed, not pushed:
# run-tests.sh syncs before it tests.
#
# Check BY CONTENT (`diff HEAD`), never `git status` - status compares
# stat first and once listed 208 modified files with an empty diff, so
# it would refuse a clean repo. Untracked files are asked for
# separately and do count.
#
# Only a SCRATCH destination is exempt; the real path has no bypass.
if [ -z "$scratch" ] \
   && git -C "$repo" rev-parse --git-dir >/dev/null 2>&1; then
    dirty="$(
        git -C "$repo" diff --name-only HEAD 2>/dev/null
        git -C "$repo" ls-files --others --exclude-standard 2>/dev/null
    )"
    if [ -n "$dirty" ]; then
        echo "sync-install: REFUSING - the repo has uncommitted changes," >&2
        echo "  so the install would hold code that exists in no commit." >&2
        echo >&2
        printf '%s\n' "$dirty" | sed 's/^/    /' >&2
        echo >&2
        echo "  Commit them, then run this again. A push is NOT needed." >&2
        exit 1
    fi
else
    # A zip download has no .git. Say so rather than claiming a check
    # that did not happen - silence here would read as a clean tree.
    echo "sync-install: no git repo here, so the commit check was skipped" >&2
fi

amaze_mirror "$repo/scripts" "$install/scripts" '__pycache__'
amaze_mirror "$repo/python_panels" "$install/python_panels"
amaze_mirror "$repo/toolbar" "$install/toolbar"
cp "$repo/OPmenu.xml" "$install/OPmenu.xml"
# BYTECODE: purge, then rebuild HASH-VALIDATED (PEP 552).
#
# A synced .py can arrive with a preserved or older mtime, so a
# TIMESTAMP-validated .pyc looks current while holding the previous
# version - it crashed the panel with no interface. Hash validation
# checks the source's content, so a lying mtime proves nothing.
#
# --force overwrites any timestamp-validated .pyc left from before, the
# one file that could still lie. Compile with the SAME interpreter
# Houdini runs, or the magic number mismatches and every import
# recompiles anyway.
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

# Verify the whole of scripts/, not just python/amaze: the rsync copies
# "$repo/scripts/", so anything added beside it would ship UNVERIFIED.
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

# VERIFY WHAT WAS JUST SHIPPED - this is the path that reaches a live
# Houdini, so a broken build would sit here until someone opened the
# panel.
#
# It CANNOT refuse before syncing: the suite reads $AMAZE, so the tests
# only mean anything after. Sync, test, then say loudly what happened
# and name the command that undoes it.
#
# run-tests.sh sets AMAZE_SYNC_NO_VERIFY to break the recursion.
if [ -n "${AMAZE_SYNC_NO_VERIFY:-}" ]; then
    exit 0
fi
# A scratch install is never verified by running the suite: the code in
# it is usually sabotaged ON PURPOSE, so a red result is the point
# rather than a reason to refuse.
if [ -n "$scratch" ]; then
    exit 0
fi

if ! command -v hython >/dev/null 2>&1 && [ -z "${HFS:-}" ]; then
    # Never a bare `ls -d <glob>` here: under `set -euo pipefail` it
    # exits non-zero when nothing matches and kills this script with NO
    # output, on the fresh machine these lines exist for.
    # amaze_newest_houdini returns "" instead, which is reportable.
    HFS="$(amaze_newest_houdini)"
    export HFS
fi
if ! command -v hython >/dev/null 2>&1 && [ ! -d "${HFS:-}" ]; then
    echo "sync-install: REFUSING to report success - no Houdini found," >&2
    echo "  so the code just shipped to the install was never tested." >&2
    exit 1
fi

echo "sync-install: verifying what was just shipped..."
# set +e, NOT `|| true`: under `set -e` a failing suite aborts here
# silently, but `|| true` throws away the status and then "no FAILED
# line" reads as green - which a licence hiccup or a crash inside the
# runner also produces. Check all three: status, FAILED, and a leak.
set +e
out="$(bash "$repo/scripts/python/amaze/tests/start_test.sh" 2>&1)"
rc=$?
set -e
# `|| true` on every one: grep -c EXITS 1 when the count is zero, so a
# green suite would kill the script here under `set -e`.
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
    # `|| true`: with no match grep exits 1, pipefail carries it past
    # head, and set -e kills the script INSIDE the failure branch,
    # losing the rollback instructions below.
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
# END MARKER. Under `set -e` an exit code alone cannot tell "finished"
# from "aborted partway", so keep a terminal line and check for it.
echo "sync-install: DONE"
