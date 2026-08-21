#!/bin/bash
# Sourced, never executed: one place that knows where Houdini is and how
# to mirror a directory, for every caller that needs either. The lookup
# was written four times, each a macOS-only glob, so a machine matching
# none of them silently had no suite, no ship step and no push gate
# (practice.md > A LOOKUP WRITTEN FOUR TIMES IS A PLATFORM SILENTLY
# UNGATED, and research.md > Windows for every platform fact below).

# Git Bash and MSYS2 report MINGW64_NT-*; Cygwin reports CYGWIN_NT-*.
amaze_is_windows() {
    case "$(uname -s)" in
        MINGW*|MSYS*|CYGWIN*) return 0 ;;
        *) return 1 ;;
    esac
}

# Every install, oldest first, so `tail -1` is the newest and
# --all-versions visits them in order. A directory counts only if it
# holds bin/hython, never by name, and the loop replaces `ls -d <glob>`,
# which exits non-zero on no match and kills the caller under pipefail.
amaze_houdini_roots() {
    local d found=""
    if amaze_is_windows; then
        local vendor
        vendor="$(cygpath -u "${PROGRAMFILES:-C:/Program Files}" 2>/dev/null \
                  || printf '%s' "/c/Program Files")/Side Effects Software"
        for d in "$vendor"/*; do
            if [ -x "$d/bin/hython.exe" ]; then found="$found$d"$'\n'; fi
        done
    else
        for d in /Applications/Houdini/Houdini*/Frameworks/Houdini.framework/Versions/Current/Resources; do
            if [ -x "$d/bin/hython" ]; then found="$found$d"$'\n'; fi
        done
        # Linux: /opt/hfsMAJOR.MINOR is SideFX's symlink to the current
        # build, so the bare glob matches every install twice - keep the
        # symlink (a hard-coded build number goes stale, INSTALL.md 0d)
        # and drop any real directory a kept symlink already resolves to.
        local resolved covered=""
        for d in /opt/hfs*; do
            if [ -L "$d" ] && [ -x "$d/bin/hython" ]; then
                found="$found$d"$'\n'
                resolved="$(cd "$d" 2>/dev/null && pwd -P)"
                covered="$covered$resolved"$'\n'
            fi
        done
        for d in /opt/hfs*; do
            if [ ! -L "$d" ] && [ -x "$d/bin/hython" ]; then
                resolved="$(cd "$d" 2>/dev/null && pwd -P)"
                case "$covered" in *"$resolved"$'\n'*) continue ;; esac
                found="$found$d"$'\n'
            fi
        done
    fi
    if [ -n "$found" ]; then printf '%s' "$found" | sort -V; fi
}

amaze_newest_houdini() {
    amaze_houdini_roots | tail -1
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

# Package files that may define $AMAZE, most authoritative LAST and ONE
# list for every platform - a dev machine is any machine, and the per-OS
# branches put the Linux pref-dir glob inside the WINDOWS branch, so
# Linux resolved nothing and every sync there needed $AMAZE by hand
# (practice.md > p/linux-tooling-blind). The globs that miss on a
# platform simply match no file: Documents is the Windows stray, the
# /Applications and ~/Library pair is macOS, and ~/houdini* is the pref
# dir on BOTH Windows (via Git Bash $HOME) and Linux - it stays last so
# the real pref dir outranks the Documents copy (INSTALL.md).
amaze_package_files() {
    local f
    for f in "$HOME"/Documents/houdini*/packages/Amaze.json \
             /Applications/Houdini/sidefx_packages/Amaze.json \
             "$HOME"/Library/Preferences/houdini/*/packages/Amaze.json \
             "$HOME"/houdini*/packages/Amaze.json; do
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
