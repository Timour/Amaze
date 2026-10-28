#!/bin/bash
# SOURCED, never executed: the one place that knows where Houdini is and
# how to mirror a directory. Every caller sources this - a private copy
# is a platform that silently has no suite, no ship step and no gate.
# Prose archived: AmazeNotes/code-prose.md ▸ houdini-env.sh

# Git Bash and MSYS2 report MINGW64_NT-*; Cygwin reports CYGWIN_NT-*.
amaze_is_windows() {
    case "$(uname -s)" in
        MINGW*|MSYS*|CYGWIN*) return 0 ;;
        *) return 1 ;;
    esac
}

# Every install, oldest first. Counted by holding bin/hython, never by
# name. NOT `ls -d <glob>` - that exits non-zero on no match and kills
# the caller under pipefail.
amaze_houdini_roots() {
    # zsh ABORTS on an unmatched glob where bash carries it as a literal, and this file is sourced from interactive zsh too - nonomatch, function-scoped, gives every shell the bash reading (measured 2026-08-21: `/opt/hfs*` killed the sourcing shell on a Mac).
    [ -n "${ZSH_VERSION:-}" ] && setopt localoptions nonomatch 2>/dev/null
    local d found=""
    if amaze_is_windows; then
        local vendor
        vendor="$(cygpath -u "${PROGRAMFILES:-C:/Program Files}" 2>/dev/null \
                  || printf '%s' "/c/Program Files")/Side Effects Software"
        for d in "$vendor"/*; do
            if [ -x "$d/bin/hython.exe" ]; then found="$found$d"$'\t'"$d"$'\n'; fi
        done
    else
        for d in /Applications/Houdini/Houdini*/Frameworks/Houdini.framework/Versions/Current/Resources; do
            if [ -x "$d/bin/hython" ]; then found="$found$d"$'\t'"$d"$'\n'; fi
        done
        # Linux: /opt/hfsMAJOR.MINOR is SideFX's symlink to the current
        # build, so the glob matches every install twice. Keep the
        # symlink, drop the directory it resolves to, and KEY IT ON THE
        # BUILD - keyed on itself, hfs22.0 sorts below every point-build
        # beside it and tail -1 answers a stale leftover.
        local resolved covered=$'\n'
        for d in /opt/hfs*; do
            if [ -L "$d" ] && [ -x "$d/bin/hython" ]; then
                resolved="$(cd "$d" 2>/dev/null && pwd -P)"
                found="$found${resolved:-$d}"$'\t'"$d"$'\n'
                covered="$covered$resolved"$'\n'
            fi
        done
        for d in /opt/hfs*; do
            if [ ! -L "$d" ] && [ -x "$d/bin/hython" ]; then
                resolved="$(cd "$d" 2>/dev/null && pwd -P)"
                case "$covered" in *$'\n'"$resolved"$'\n'*) continue ;; esac
                found="$found$d"$'\t'"$d"$'\n'
            fi
        done
    fi
    if [ -n "$found" ]; then printf '%s' "$found" | sort -V | cut -f2; fi
}

# The build every default run uses: the LOWEST install of the newest major,
# because a newer build beside it is a daily. `--all-versions` runs them all.
amaze_houdini() {
    local roots major root
    roots="$(amaze_houdini_roots)"
    [ -n "$roots" ] || return 0
    major="$(amaze_houdini_major "$(printf '%s\n' "$roots" | tail -1)")"
    while IFS= read -r root; do
        if [ "$(amaze_houdini_major "$root")" = "$major" ]; then
            printf '%s\n' "$root"
            return 0
        fi
    done <<< "$roots"
}

# A root's major version from its own spelling: Houdini22.0.x, Houdini 22.0.x, hfs22.0.
amaze_houdini_major() {
    printf '%s' "$1" | sed -nE 's/.*([Hh]oudini ?|hfs)([0-9]+).*/\2/p'
}

amaze_hython() {
    local root="${1:-}"
    if [ -x "$root/bin/hython.exe" ]; then
        printf '%s\n' "$root/bin/hython.exe"
    elif [ -x "$root/bin/hython" ]; then
        printf '%s\n' "$root/bin/hython"
    else
        return 1
    fi
}

# Houdini's own Python, not Houdini: hython's version, started in well under a second.
amaze_plain_python() {
    [ -n "${ZSH_VERSION:-}" ] && setopt localoptions nonomatch 2>/dev/null
    local root="${1:-}" candidate
    for candidate in \
            "$root/../../../../Python.framework/Versions/Current/bin/python3" \
            "$root/python/bin/python3" \
            "$root"/python3*/python.exe; do
        # EXECUTED before it is trusted: one present but unable to start falls through to hython
        if [ -x "$candidate" ] && "$candidate" -c '' >/dev/null 2>&1; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

# Package files that may define $AMAZE, most authoritative LAST, and ONE
# list for every platform - per-OS branches are how the Linux pref-dir
# glob ended up inside the Windows branch. A glob that misses simply
# matches no file: Documents is the Windows stray,
# ~/houdini* is the pref dir on BOTH Windows (via Git Bash $HOME) and
# Linux and outranks it, and the /Applications and ~/Library pair is
# macOS - ~/Library goes LAST because it is the only glob that can
# match beside ~/houdini* on one machine, and there (macOS) it is the
# real pref dir while ~/houdini* can only be a stray (INSTALL.md).
amaze_package_files() {
    [ -n "${ZSH_VERSION:-}" ] && setopt localoptions nonomatch 2>/dev/null
    local f
    for f in "$HOME"/Documents/houdini*/packages/Amaze.json \
             /Applications/Houdini/sidefx_packages/Amaze.json \
             "$HOME"/houdini*/packages/Amaze.json \
             "$HOME"/Library/Preferences/houdini/*/packages/Amaze.json; do
        if [ -f "$f" ]; then printf '%s\n' "$f"; fi
    done
}

# Windows ships stub aliases that exist, are executable, and fail when
# run, so each candidate is EXECUTED before it is trusted.
amaze_python() {
    local c
    for c in python3 python; do
        if command -v "$c" >/dev/null 2>&1 && "$c" -c '' >/dev/null 2>&1; then
            printf '%s\n' "$c"
            return 0
        fi
    done
    return 1
}

# Mirror src into dst, extra files deleted, non-zero on failure -
# robocopy on Windows, where Git Bash has no rsync and the exit codes,
# argument rewriting and retry default are all traps. The two paths may
# differ because sync-install.sh diffs the trees afterwards.
amaze_mirror() {
    local src="${1:-}" dst="${2:-}" exclude="${3:-}"
    if [ ! -d "$src" ]; then
        echo "amaze_mirror: no such source: $src" >&2
        return 1
    fi
    if amaze_is_windows; then
        local args rc=0
        args=(/MIR /NJH /NJS /NP /NDL /NFL /R:2 /W:1)
        if [ -n "$exclude" ]; then args+=(/XD "$exclude"); fi
        MSYS_NO_PATHCONV=1 robocopy \
            "$(cygpath -w "$src")" "$(cygpath -w "$dst")" \
            "${args[@]}" >/dev/null 2>&1 || rc=$?
        if [ "$rc" -ge 8 ]; then
            echo "amaze_mirror: robocopy failed ($rc): $src -> $dst" >&2
            return 1
        fi
        return 0
    fi
    if [ -n "$exclude" ]; then
        rsync -a --delete --exclude "$exclude" "$src/" "$dst/"
    else
        rsync -a --delete "$src/" "$dst/"
    fi
}
