#!/bin/bash
# Sabotage-verify the personal-data gate, in BOTH directions - a gate
# that only refuses gets bypassed, one that only passes is decoration.
#
# NAMES NOBODY: every probe string is derived from the private pattern
# list at run time, so this file is safe in a public repo and a new
# pattern gains a test for free.
#
# The BYPASS section is a regression suite - every case was a real hole.
#
# Run after touching any hook, and on a fresh machine to prove the gate
# is wired:  tools/git-hooks/test-gate.sh

set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd)"

list="${AMAZE_PRIVATE_NAMES:-$repo/../AmazeNotes/private-names.txt}"
if [ ! -f "$list" ]; then
    echo "no private name list at $list - nothing to test against" >&2
    exit 1
fi
export AMAZE_PRIVATE_NAMES="$list"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cd "$work" || exit 1
git init -q .
git config core.hooksPath "$here"
git config user.email "gate-test@example.invalid"
git config user.name "Gate Test"
# An origin the scanner can discover, so the "our own URL is exempt"
# rule has something to be exempt ABOUT without this file naming it.
#
# THE OWNER MUST CONTAIN THE PROBE NAME, or the own-url cases test
# nothing: with an owner spelling no listed pattern, those lines name
# nobody and pass whether the exemption works or not. That is the fault
# already recorded for the LOOKALIKE case a few lines down, sitting
# unnoticed in its neighbour - and it hid a real gap, where the same
# address in the host's API spelling was refused. Built after `probe`
# is derived, which is why the remote is added down here rather than
# with the other git config above.

pass=0
fail=0
check() {   # description, expected status, actual status
    if [ "$2" -eq "$3" ]; then
        printf '  PASS  %s\n' "$1"; pass=$((pass + 1))
    else
        printf '  FAIL  %s (expected exit %s, got %s)\n' "$1" "$2" "$3"
        fail=$((fail + 1))
    fi
}
reset_tree() { git reset -q; git clean -qfdx >/dev/null 2>&1; }

echo "seed" > seed.txt && git add seed.txt && git commit -qm "Seed"

patterns="$(sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' "$list" \
            | grep -v '^#' | awk 'NF')"
probe="$(printf '%s\n' "$patterns" | head -1 | tr -d '\\')"
git remote add origin "https://github.com/$probe/gate-test-repo.git"

echo "REFUSES - every pattern in the list, in content and in a message"
while read -r pattern; do
    [ -n "$pattern" ] || continue
    p="${pattern//\\/}"
    printf 'x = 1  # %s wrote this\n' "$p" > probe.py
    git add probe.py
    "$here/pre-commit" >/dev/null 2>&1
    check "content carrying a listed pattern is refused" 1 $?
    reset_tree
    printf 'A technical subject\n\nReported by %s.\n' "$p" > msg.txt
    "$here/commit-msg" msg.txt >/dev/null 2>&1
    check "message carrying a listed pattern is refused" 1 $?
done <<< "$patterns"

echo "REFUSES - bypasses reproduced against the earlier shell drafts"

# B1: a C-quoted filename skipped the content scan entirely.
printf '%s wrote this and it is a real leak\n' "$probe" > "$(printf 'no\ntes.md')"
git add -A
"$here/pre-commit" >/dev/null 2>&1
check "a filename with a newline cannot hide its content" 1 $?
reset_tree

# B2: a stage-spec-shaped filename made the gate scan a DIFFERENT file.
printf 'perfectly innocent technical text\n' > notes.md
printf '%s said it stalled and ate 86GB\n' "$probe" > '0:notes.md'
git add -A
"$here/pre-commit" >/dev/null 2>&1
check "a 0:-prefixed filename is not resolved as a stage spec" 1 $?
reset_tree

# B3: one NUL past byte 8000 hid a file git itself calls TEXT.
{ printf '# Release notes\n\nWritten by %s\n' "$probe"
  for i in $(seq 1 400); do printf 'Line %d of ordinary notes text.\n' "$i"; done
  printf '<!-- \000 -->\n'; } > RELEASE.md
git add -A
"$here/pre-commit" >/dev/null 2>&1
check "a NUL past byte 8000 does not make a text file invisible" 1 $?
reset_tree

# B4: the About-box exemption applied to commit MESSAGES too.
printf 'Fix the capture stall\n\n<p>By %s<br>\n' "$probe" > msg.txt
"$here/commit-msg" msg.txt >/dev/null 2>&1
check "the About-box shape does not excuse a commit message" 1 $?

# The body of 1.0.18, which every pattern missed: no pronoun, no name.
printf '1.0.18 - the update messages say what happens\n\nThe offer carried reassurance about the library not being touched,\nwhich is noise in front of someone who is already unsure.\n' > unnamed.txt
"$here/commit-msg" unnamed.txt >/dev/null 2>&1
check "an unnamed person in the body is refused" 1 $?
printf 'Fix the capture stall\n\nThe capture blocked 22s on one scene and never returned on the next,\nconsuming 86GB. Suite 2649 green.\n' > plain.txt
"$here/commit-msg" plain.txt >/dev/null 2>&1
check "      a body of pure function still passes" 0 $?

# ITS OWN BYPASS: pre-commit's must not reach the message gate.
head_now="$(git rev-parse HEAD)"
AMAZE_ALLOW_PRIVATE="$head_now" "$here/commit-msg" unnamed.txt >/dev/null 2>&1
check "AMAZE_ALLOW_PRIVATE does NOT disarm the message gate" 1 $?
AMAZE_ALLOW_MESSAGE="$head_now" "$here/commit-msg" unnamed.txt >/dev/null 2>&1
check "      AMAZE_ALLOW_MESSAGE does" 0 $?

# B4b: the credit pattern was wide enough to swallow prose.
printf '    "<p>By %s and he said the render stalled again<br>"\n' "$probe" > wide.py
git add -A
"$here/pre-commit" >/dev/null 2>&1
check "an About-shaped line padded with prose is refused" 1 $?
reset_tree

# B5: stripping ANY url deleted the evidence of a real leak.
printf 'AUTHOR_PAGE = "https://www.linkedin.com/in/%s"\n' "$probe" > links.py
git add -A
"$here/pre-commit" >/dev/null 2>&1
check "a name inside a FOREIGN url is refused" 1 $?
reset_tree

# Invisible-character obfuscation renders as the name on GitHub.
printf 'note = "%s\xe2\x80\x8b more text"\n' "$probe" > zw.py
git add -A
"$here/pre-commit" >/dev/null 2>&1
check "a zero-width space inside the name does not hide it" 1 $?
reset_tree

echo "PASSES - legitimate content must not be blocked"
printf 'x = 1  # the capture blocked until a render was stopped\n' > ok.py
git add -A && "$here/pre-commit" >/dev/null 2>&1
check "ordinary technical prose passes" 0 $?
reset_tree

printf '            "<p>By %s.<br>"\n' "$probe" > credit.py
git add -A && "$here/pre-commit" >/dev/null 2>&1
check "the About-box product credit passes" 0 $?
reset_tree

printf 'URL = "https://github.com/%s/gate-test-repo/issues/1"\n' "$probe" > url.py
git add -A && "$here/pre-commit" >/dev/null 2>&1
check "our OWN repo url passes" 0 $?
reset_tree

printf 'x = [u for u in x if "github.com/%s" not in u]\n' "$probe" > owner.py
git add -A && "$here/pre-commit" >/dev/null 2>&1
check "our own host/owner prefix passes as a bare literal" 0 $?
reset_tree

# The SAME address in the host's API spelling. `remote.origin.url` is
# the browse form, and the product reaches the release feed through
# `api.<host>/repos/<owner>/<repo>` - one address, two spellings, and
# only the browse one was exempt. Every commit touching the updater was
# refused on a literal that has to be there for it to work.
printf 'URL = "https://api.github.com/repos/%s/gate-test-repo/releases/latest"\n' "$probe" > api.py
git add -A && "$here/pre-commit" >/dev/null 2>&1
check "our own repo url in the API spelling passes" 0 $?
reset_tree

# And the exemption must not widen with the spelling: the lookalike is
# refused in the API form exactly as in the browse form.
printf 'REF = "https://api.github.com/repos/%s-personal-notes/private/issues"\n' "$probe" > apilookalike.py
git add -A && "$here/pre-commit" >/dev/null 2>&1
check "an API-spelled LOOKALIKE owner is still refused" 1 $?
reset_tree

# The lookalike must CONTAIN the name, or it tests nothing - the
# first version used an owner with no name in it at all and passed
# for that reason.
printf 'REF = "github.com/%s-personal-notes/private"\n' "$probe" > lookalike.py
git add -A && "$here/pre-commit" >/dev/null 2>&1
check "a LOOKALIKE owner is still refused" 1 $?
reset_tree

printf 'A technical subject\n\nThe check blocked on OBJ and the message lectured.\n' > msg.txt
"$here/commit-msg" msg.txt >/dev/null 2>&1
check "a technical commit message passes" 0 $?

echo "REFUSES - a message carrying more than the change"
# These name nobody, so the identity list cannot see them. Every one is
# a SHAPE found in the published history by audit - and the wording is
# invented to fit that shape, never lifted. A fixture quoting a real
# report publishes it here instead, which is the leak this file exists
# to catch.

printf 'Widen the tick column\n\nHis call: the mark decides the width.\n' > msg.txt
"$here/commit-msg" msg.txt >/dev/null 2>&1
check "a decision credited to a person is refused" 1 $?

printf 'Widen the tick column\n\nHe asked for the mark to decide the width.\n' > msg.txt
"$here/commit-msg" msg.txt >/dev/null 2>&1
check "a person reported as speaking is refused" 1 $?

printf 'Widen the tick column\n\nReported as "the swatch renders upside down" in testing.\n' > msg.txt
"$here/commit-msg" msg.txt >/dev/null 2>&1
check "a quoted sentence is refused" 1 $?

# THE WRAPPING CASES. A message wraps at 72 columns, so an attribution
# and a quotation both straddle the break - and neither half matches on
# its own. A scan reading one line at a time passes both of these, which
# is what the published history proved: a quotation that opens on one
# line and closes on the next survived the gate.
printf 'Widen the tick column\n\nThe width rule is the one we\nagreed on for every column.\n' > msg.txt
"$here/commit-msg" msg.txt >/dev/null 2>&1
check "an attribution straddling a line break is refused" 1 $?

printf 'Widen the tick column\n\nThe field was restyled, reported as "the swatch\nrenders upside down" during the pass.\n' > msg.txt
"$here/commit-msg" msg.txt >/dev/null 2>&1
check "a quotation straddling a line break is refused" 1 $?

# Tool advertising arrives by DEFAULT and nothing refused it, which is
# how 195 of the 445 commits on main came to carry it in three variants.
printf 'Widen the tick column\n\nThe mark decides the width.\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>\n' > msg.txt
"$here/commit-msg" msg.txt >/dev/null 2>&1
check "a co-author trailer advertising the tool is refused" 1 $?

printf 'Widen the tick column\n\nThe mark decides the width.\n\nGenerated with [Claude Code](https://claude.com/claude-code)\n' > msg.txt
"$here/commit-msg" msg.txt >/dev/null 2>&1
check "a generated-with advertising line is refused" 1 $?

printf 'Widen the tick column so the mark decides its width and the header stops reserving arrow space\n\nShort body.\n' > msg.txt
"$here/commit-msg" msg.txt >/dev/null 2>&1
check "a subject over 72 characters is refused" 1 $?

{ printf 'Widen the tick column\n\n'
  for i in $(seq 1 11); do printf 'Body line %d of ordinary technical text.\n' "$i"; done
} > msg.txt
"$here/commit-msg" msg.txt >/dev/null 2>&1
check "a body over ten lines is refused" 1 $?

echo "PASSES - a message stating the change and nothing else"

printf 'Widen the tick column\n\nThe mark decides the width; the header no longer reserves space\nfor a sort arrow. 203 tests pass on H21 and H22.\n' > msg.txt
"$here/commit-msg" msg.txt >/dev/null 2>&1
check "the function of the code plus a test result passes" 0 $?

# Machine text is why the quote rule cannot simply refuse every quote:
# an error string is not speech, and backticks are where it goes.
printf 'Guard the loader\n\nThe panel logged `IndexError: tuple index out of range` before the\nguard; `_FileLoader` now checks the index first.\n' > msg.txt
"$here/commit-msg" msg.txt >/dev/null 2>&1
check "machine text in backticks passes" 0 $?

printf 'Rename the section\n\nThe "Notes" pane is now Comments; identifiers unchanged.\n' > msg.txt
"$here/commit-msg" msg.txt >/dev/null 2>&1
check "a short quoted label passes" 0 $?

{ printf 'Widen the tick column\n\n'
  for i in $(seq 1 4); do printf 'Body line %d of ordinary technical text.\n' "$i"; done
} > msg.txt
"$here/commit-msg" msg.txt >/dev/null 2>&1
check "a body of exactly four lines passes" 0 $?

{ printf 'Widen the tick column\n\n'
  for i in $(seq 1 5); do printf 'Body line %d of ordinary technical text.\n' "$i"; done
} > msg.txt
"$here/commit-msg" msg.txt >/dev/null 2>&1
check "a body of five lines refuses" 1 $?

echo "REFUSES - a gate that cannot trust itself must not pass"
printf 'x = 1  # a plain technical comment\n' > m2.py
git add -A
AMAZE_PRIVATE_NAMES=/nonexistent/nope.txt "$here/pre-commit" >/dev/null 2>&1
check "an explicitly-set missing list refuses (no silent fallback)" 1 $?
: > "$work/empty-list"
AMAZE_PRIVATE_NAMES="$work/empty-list" "$here/pre-commit" >/dev/null 2>&1
check "an empty list refuses" 1 $?
printf '%s (unbalanced\n' "$probe" > "$work/badlist"
AMAZE_PRIVATE_NAMES="$work/badlist" "$here/pre-commit" >/dev/null 2>&1
check "a list that will not compile refuses (fails closed)" 1 $?
reset_tree

echo "REFUSES - paths, renames and merges"
printf 'nothing to see\n' > plain.txt
git add -A && git commit -qm "Add a plain file"
git mv plain.txt "${probe}-notes.txt"
"$here/pre-commit" >/dev/null 2>&1
check "a rename to a name-carrying path is refused" 1 $?
reset_tree; git checkout -q -- . 2>/dev/null
: > "${probe}-empty.txt"
git add -A && "$here/pre-commit" >/dev/null 2>&1
check "an EMPTY file with a name-carrying path is refused" 1 $?
reset_tree

git checkout -q -b topic
printf '%s wrote this file\n' "$probe" > merged.txt
git add -A && git -c core.hooksPath=/dev/null commit -qm "Add a file" >/dev/null 2>&1
git checkout -q -
git merge --no-ff -m "Merge topic" topic >/dev/null 2>&1
check "merged CONTENT is scanned (pre-merge-commit)" 1 $?
git merge --abort >/dev/null 2>&1 || true
git branch -qD topic >/dev/null 2>&1 || true
reset_tree

echo "THE SENTENCE CEILING - it measures STORY, not function"

# One-line docstrings must NOT count, or the ceiling scales with the
# number of functions rather than with the amount of story.
{ printf 'x = 1\n'
  for i in $(seq 1 14); do
      printf 'def f%d():\n    """A summary sentence for f%d."""\n    return %d\n' "$i" "$i" "$i"
  done; } > many_docstrings.py
git add many_docstrings.py
"$here/pre-commit" >/dev/null 2>&1
check "one-line docstrings do not fill the sentence ceiling" 0 $?
reset_tree

# Story under the summary must still be caught.
{ printf 'def g():\n    """A summary line.\n\n'
  for i in $(seq 1 14); do printf '    Sentence %d of the story.\n' "$i"; done
  printf '    """\n    return 1\n'; } > long_story.py
git add long_story.py
"$here/pre-commit" >/dev/null 2>&1
check "story UNDER the summary is still refused" 1 $?
reset_tree

echo "ONE COMMENT LINE PER SCOPE - whole-file, docstrings counted too"

# AT the cap. Every scope here HAS a comment, so a broken counter shows
# up as a refusal rather than as a pass with nothing to count. The
# shebang is a machine directive and must not consume the module's line.
{ printf '#!/usr/bin/env python3\n'
  printf '"""A module summary line."""\n'
  printf 'import os\n\n\n'
  printf 'class Thing:\n    """A class summary line."""\n\n'
  printf '    def method(self):\n        """A method summary line."""\n'
  printf '        return os.sep\n\n\n'
  printf 'def alone():\n    """A function summary line."""\n    return 2\n'
} > at_cap.py
git add at_cap.py
"$here/pre-commit" >/dev/null 2>&1
check "a file at one comment line per scope passes" 0 $?
reset_tree

# OVER by one line, in a function, with nothing else wrong - no
# pronoun, no quotation, two sentences. So the refusal can only be the
# cap, and the message is checked to prove it.
{ printf 'def widen(value):\n'
  printf '    # Clamp to the grid pitch before drawing.\n'
  printf '    # A raw value lands between rows and renders blurred.\n'
  printf '    return max(8, value - value %% 8)\n'
} > over_cap.py
git add over_cap.py
"$here/pre-commit" 2> over_cap.err >/dev/null
check "a scope over the cap is refused" 1 $?
grep -q "widen carries 2 comment lines, over 1" over_cap.err
check "and the CAP is what refused it, not another rule" 0 $?
reset_tree

# The directive exemption, on material the rule CAN match: two comment
# lines in one scope, one of them a directive. If the exemption broke,
# this refuses.
{ printf 'def tagged():\n'
  printf '    # noqa: E501\n'
  printf '    # A real summary line.\n'
  printf '    return 1\n'
} > directive.py
git add directive.py
"$here/pre-commit" >/dev/null 2>&1
check "a machine directive does not consume the scope's line" 0 $?
reset_tree

echo "END TO END - real commits, through git itself"
printf 'x = 1  # %s wanted this\n' "$probe" > real.py
git add -A && git commit -qm "A technical message" >/dev/null 2>&1
check "git commit is blocked by the content gate" 1 $?
reset_tree
printf 'x = 1  # a plain technical comment\n' > clean.py
git add -A && git commit -qm "A technical message" >/dev/null 2>&1
check "git commit succeeds when everything is clean" 0 $?

echo
echo "RESULT: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
