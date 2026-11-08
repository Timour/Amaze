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
    echo "sync-install: cannot find the install." >&2
    if [ -n "$install" ]; then
        echo "  \$AMAZE resolved to a path that is not a directory:" >&2
        echo "    $install" >&2
    else
        echo "  \$AMAZE is not set, and no readable Amaze.json package" >&2
        echo "  declared it. Package files found:" >&2
        pkgs="$(amaze_package_files)"
        # quoted, one path per line: an unquoted expansion word-splits a
        # "John Smith" home into two entries that name no real file
        if [ -n "$pkgs" ]; then printf '%s\n' "$pkgs" | sed 's/^/    /' >&2
        else echo "    (none, on any platform path)" >&2; fi
        echo "  Wire the package (INSTALL.md step 2) or export \$AMAZE." >&2
    fi
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

# The real install receives committed code only, checked by content with `diff HEAD`.
# Untracked files count too; only a scratch destination is exempt.
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
elif [ -n "$scratch" ]; then
    # The scratch exemption, said out loud - it fires on every suite run.
    echo "sync-install: scratch install, so the commit check does not apply" >&2
else
    # A zip download has no .git. Say so rather than claiming a check
    # that did not happen - silence here would read as a clean tree.
    echo "sync-install: no git repo here, so the commit check was skipped" >&2
fi

amaze_mirror "$repo/scripts" "$install/scripts" '__pycache__'
amaze_mirror "$repo/python_panels" "$install/python_panels"
amaze_mirror "$repo/toolbar" "$install/toolbar"
cp "$repo/OPmenu.xml" "$install/OPmenu.xml"
# Stale compiled copies go with the sources they came from; Python writes fresh ones on import.
find "$install" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true

# Verify the whole of scripts/, not just python/amaze: the rsync copies
# "$repo/scripts/", so anything added beside it would ship UNVERIFIED.
if diff -rq "$repo/scripts" "$install/scripts" \
        --exclude=__pycache__ --exclude=.DS_Store >/dev/null \
   && diff -rq "$repo/python_panels" "$install/python_panels" \
        --exclude=.DS_Store >/dev/null \
   && diff -rq "$repo/toolbar" "$install/toolbar" \
        --exclude=.DS_Store >/dev/null \
   && diff -q "$repo/OPmenu.xml" "$install/OPmenu.xml" >/dev/null; then
    echo "sync-install: $install is identical to the repo"
else
    echo "sync-install: MISMATCH after sync - investigate" >&2
    exit 1
fi

# No suite here: the push and run-tests.sh test the commit this copies. ▸p/sync-runs-no-suite
# END MARKER. Under `set -e` an exit code alone cannot tell "finished"
# from "aborted partway", so keep a terminal line and check for it.
echo "sync-install: DONE"
