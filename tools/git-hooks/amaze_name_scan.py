#!/usr/bin/env python3
"""Scan a staged commit, or a commit message, for personal data.

Three things are refused, not one:

  * the author's IDENTITY, from the private pattern list, in staged
    content and in the message;
  * ATTRIBUTION - a person referred to without being named. The identity
    list cannot see these, because they name nobody: measured against
    the published history, 31 of 445 commits on main carry one, and
    every attribution written on 2026-08-04 passed this gate while the
    rule it breaks was being quoted correctly in the same session;
  * QUOTED SPEECH in a commit message. Machine text - an error string, a
    UI label, an identifier - goes in backticks, which 157 published
    commits already do, so quotation marks around a sentence mean a
    person was quoted.

A commit message carries the FUNCTION of the code and the RESULT of the
tests. Not the conversation that produced it.

NAMES NOBODY. This file lives in the PUBLIC repo, so a deny-list of an
identity committed here would be the leak it exists to prevent. The
patterns come from a file in the private notes repo; this side only
knows how to find it and how to apply it. The attribution patterns name
nobody either - they are generic English - so unlike the identity list
they belong here, where they can be read and tested in the open.

WHY PYTHON. The first two drafts were shell, and an adversarial review
walked through both by exploiting how a PATH becomes a STRING:

  * `core.quotePath=false` suppresses quoting of bytes >= 0x80 only.
    Control characters, `"` and `\\` are C-quoted ALWAYS, so a file
    named "no\\ntes.md" arrived as a 14-byte literal, `git show ":..."`
    could not find it, and `|| continue` read that as "nothing to
    scan".
  * A file named `0:notes.md` made `git show ":0:notes.md"` resolve as
    *stage 0 of notes.md* - so the gate scanned a DIFFERENT file and
    reported the leaking one clean. A false clean, not a skip.
  * The report was built with `sed "s|^|$path:|"`, so a path
    containing `|` produced a sed error and an empty refusal body.

None of those shapes exist here: `--raw -z` gives raw unquoted paths
and the destination blob OID, and the content is read BY OID. A path is
never interpolated into a command or a pattern.

FAILS CLOSED. A missing list, an empty list, a pattern that will not
compile, or any git call that errors all refuse.

KNOWN LIMITATIONS, stated rather than pretended away:
  * BINARY content is not scanned (.hip/.otl/.png embed the OS user
    name). Their PATHS are checked; their bytes are not.
  * cherry-pick and rebase run no content hook - git provides none.
"""
import os
import re
import subprocess
import sys

#: Match git's own binary heuristic exactly. git sniffs the FIRST 8000
#: bytes for a NUL; scanning the whole blob instead meant a file with a
#: NUL at byte 16000 was "binary" here and TEXT to git - so it diffed,
#: grepped and rendered as ordinary markdown everywhere except in the
#: gate, which skipped it.
SNIFF = 8000

#: Zero-width and soft-hyphen characters render as nothing, so a name
#: split by one still READS as the name on GitHub.
INVISIBLE = re.compile(r"[­​-‍﻿]")


def run(*args):
    """git, with the status captured. Returns (ok, stdout_bytes)."""
    try:
        proc = subprocess.run(args, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL)
    except OSError:
        return False, b""
    return proc.returncode == 0, proc.stdout


def refuse(headline, *detail):
    sys.stderr.write("COMMIT REFUSED - %s\n" % headline)
    for line in detail:
        sys.stderr.write("  %s\n" % line)
    sys.exit(1)


def load_patterns(repo):
    explicit = os.environ.get("AMAZE_PRIVATE_NAMES")
    if explicit:
        # Used as given or not at all - a silent fallback made a wrong
        # path look like success.
        path = explicit if os.path.isfile(explicit) else None
    else:
        guess = os.path.join(repo, "..", "AmazeNotes", "private-names.txt")
        path = guess if os.path.isfile(guess) else None
    if path is None:
        refuse("the private name list was not found, so the gate cannot run.",
               "Expected at ../AmazeNotes/private-names.txt, or the path in",
               "$AMAZE_PRIVATE_NAMES (used as given - there is no fallback).",
               "Clone the private notes repo. See INSTALL.md 6a.")
    with open(path, encoding="utf-8", errors="replace") as handle:
        raw = [line.strip() for line in handle]
    parts = [p for p in raw if p and not p.startswith("#")]
    if not parts:
        refuse("the private name list is empty: %s" % path)
    try:
        return re.compile("|".join(parts), re.IGNORECASE), path
    except re.error as exc:
        refuse("the private name list does not compile to a valid regex.",
               "List: %s" % path, "Error: %s" % exc,
               "A typo here used to make the gate pass everything silently.")


def own_url():
    """The repo's OWN address, discovered rather than hardcoded - this
    file cannot name the org any more than it can name the author.

    Only this URL is exempt. Stripping ANY url exempted a name inside an
    unrelated one: a personal profile link and a mailto query both
    sailed through, which is the exemption deleting the evidence."""
    ok, out = run("git", "config", "--get", "remote.origin.url")
    if not ok:
        return None
    url = out.decode("utf-8", "replace").strip()
    url = re.sub(r"^[a-z+]*://", "", url)
    url = re.sub(r"^[^@]*@", "", url).replace(":", "/")
    url = re.sub(r"\.git$", "", url).rstrip("/")
    return url or None


#: The About-box product credit, ANCHORED and letters-only. The first
#: version matched anywhere on a line and accepted enough characters to
#: swallow an email address, a phone number and a sentence of prose.
CREDIT = re.compile(r'^\s*"<p>By [A-Za-z.]+(?: [A-Za-z.]+){0,3}<br>"\s*$')


def sanitize(line, allow_credit):
    line = INVISIBLE.sub("", line)
    url = sanitize.url
    if url:
        line = re.sub(r"[a-z+]*://" + re.escape(url) + r"\S*", "", line)
        line = re.sub(re.escape(url) + r"\S*", "", line)
    owner = sanitize.owner
    if owner:
        # The host/owner prefix of our OWN url is public by design and
        # appears in the code as a bare literal. Stripped only at a
        # BOUNDARY: `host/owner-personal-notes` is a different account
        # and must stay visible, which is why `-` and `.` do not end the
        # token. Getting this wrong re-opens the "a name inside a
        # foreign url" bypass.
        line = re.sub(re.escape(owner) + r"(?![A-Za-z0-9._-])", "", line)
    if allow_credit and CREDIT.match(line):
        return ""
    return line


sanitize.url = None
sanitize.owner = None


def scan_text(text, pattern, allow_credit):
    hits = []
    for number, line in enumerate(text.splitlines(), 1):
        if pattern.search(sanitize(line, allow_credit)):
            hits.append((number, line.strip()[:120]))
    return hits


# ---------------------------------------------------------- message rules
#
# A commit message carries the FUNCTION of the code and the RESULT of the
# tests. Everything below is what kept arriving instead, and none of it
# is reachable by the identity list.

#: Measured over the 445 commits on main before this gate: a median body
#: of 22 lines and 185 words, 78% of them past ten lines, the longest at
#: 141 lines and 1380 words. Length is the only mechanical handle on
#: narrative, and narrative is what makes a history unreadable to anyone
#: arriving new. The diff already says what changed; the dev log in the
#: private notes already carries the story.
MAX_SUBJECT_CHARS = 72
MAX_BODY_LINES = 10

#: A person, referred to without being named - so the identity list
#: cannot see any of it. Generic English, naming nobody, which is why
#: these live in the public repo where they can be read and tested.
ATTRIBUTION = (
    (re.compile(r"\b(?:he|him|his|she|her|hers|himself|herself)\b", re.I),
     "a pronoun standing in for a person"),
    (re.compile(r"\b(?:he|she|they)\s+(?:asked|said|told|wanted|wants|"
                r"reported|noticed|complained|confirmed|insisted|approved|"
                r"rejected|prefers|hates|likes|tried|thinks|thought|"
                r"decided|agreed|meant|called|found|put)\b", re.I),
     "a person reported as speaking"),
    (re.compile(r"\b(?:his|her|their|my|our)\s+(?:call|test|report|shot|"
                r"idea|point|request|words|wording|preference|feedback|"
                r"complaint|decision|note|notes|suggestion|objection|"
                r"verdict|ask|framing|diagnosis|instruction|instructions|"
                r"follow-up)\b", re.I),
     "a decision credited to a person"),
    (re.compile(r"\bas (?:he|she|they) (?:put it|said|described)\b"
                r"|\bper (?:his|her|their) (?:call|chat|instruction|request)\b"
                r"|\bI (?:told|asked)\b"
                r"|\bwe (?:agreed|discussed|decided)\b"
                r"|\byou (?:asked|said|wanted|told me|reported)\b"
                r"|\bas discussed\b|\bper the chat\b|\breported by\b", re.I),
     "a conversation recorded instead of a reason"),
)

#: Machine text goes in backticks, which 157 published commits already
#: do. Their contents are removed before the quote rule looks, so an
#: error string or an identifier is never read as speech.
BACKTICK = re.compile(r"`[^`]*`")
FENCE = re.compile(r"^\s*```")

QUOTED = (
    re.compile(r'"([^"\n]{2,400})"'),
    re.compile("“([^”\n]{2,400})”"),
    # A single quote needs non-letter boundaries, or the apostrophe in a
    # possessive opens a span that runs to the next one.
    re.compile(r"(?<![A-Za-z])'([^'\n]{2,400})'(?![A-Za-z])"),
    re.compile("‘([^’\n]{2,400})’"),
)
HAS_LETTER = re.compile(r"[A-Za-z]")

#: Below three words a quoted span is a label or an identifier; at three
#: and above it is a sentence, and a sentence in quotation marks is
#: somebody being quoted.
QUOTE_MIN_WORDS = 3

#: Tool advertising. A message records the change; what typed it is not
#: part of the change, and a published history is not advertising space.
#: 195 of the 445 commits on main carry one of these, in three variants,
#: because it arrives by default and nothing refused it.
ADVERTISING = re.compile(
    r"co-authored-by:\s*(?:claude|[^<]*anthropic)"
    r"|generated with \[?claude"
    r"|noreply@anthropic\.com"
    r"|\bclaude(?:\.ai|\s*code|\s*opus|\s*sonnet|\s*haiku)?\b"
    r"|\banthropic\b"
    r"|\b(?:written|made|authored|generated|created)\s+(?:with|by)\s+"
    r"(?:an?\s+)?(?:ai|llm|assistant|agent|bot)\b", re.I)


def quoted_speech(text):
    """The first quoted span of QUOTE_MIN_WORDS words or more, or None.

    Words are WHITESPACE-separated. Counting runs of letters instead
    read a slash-separated path as seven words, which made every icon
    path in the manual look like a reproduced sentence.
    """
    for pattern in QUOTED:
        for match in pattern.finditer(BACKTICK.sub(" ", text)):
            inner = match.group(1)
            if len([w for w in inner.split() if HAS_LETTER.search(w)]) \
                    >= QUOTE_MIN_WORDS:
                return inner
    return None


def paragraphs(text):
    """[(first_line_number, joined_text)] per blank-line-separated block.

    JOINED, because a message wraps at 72 columns and both an
    attribution and a quotation routinely straddle the break. A scan
    reading one line at a time sees two clean lines and passes - found
    by audit in published commits, where a quotation opens on one line
    and closes on the next, and in source where a two-word attribution
    is split by a comment marker.

    Fenced blocks are skipped: they are pasted output, not prose.
    """
    blocks, start, buf, fenced = [], 0, [], False
    for number, line in enumerate(text.splitlines(), 1):
        if FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        if line.strip():
            if not buf:
                start = number
            buf.append(line.strip())
        elif buf:
            blocks.append((start, " ".join(buf)))
            buf = []
    if buf:
        blocks.append((start, " ".join(buf)))
    return blocks


def message_body(text):
    """The body lines that are the author's, template comments removed."""
    lines = text.splitlines()[1:]
    kept = [line for line in lines if not line.lstrip().startswith("#")]
    while kept and not kept[0].strip():
        kept.pop(0)
    while kept and not kept[-1].strip():
        kept.pop()
    return kept


def scan_message(text):
    """[(line_number, reason, excerpt)] for everything but the identity."""
    hits = []
    lines = text.splitlines()
    subject = lines[0].strip() if lines else ""
    if len(subject) > MAX_SUBJECT_CHARS:
        hits.append((1, "the subject is %d characters, over %d"
                     % (len(subject), MAX_SUBJECT_CHARS), subject))

    # Checked on the RAW lines: a trailer is its own line, and it must be
    # caught whether or not it sits in a paragraph.
    for number, line in enumerate(lines, 1):
        if ADVERTISING.search(line):
            hits.append((number, "tool advertising", line.strip()[:110]))

    body = message_body(text)
    if len(body) > MAX_BODY_LINES:
        hits.append((2, "the body is %d lines, over %d" % (len(body),
                                                           MAX_BODY_LINES),
                     body[0][:110] if body else ""))

    for number, para in paragraphs(text):
        for pattern, reason in ATTRIBUTION:
            match = pattern.search(para)
            if match:
                hits.append((number, reason, match.group(0)))
                break
        spoken = quoted_speech(para)
        if spoken:
            hits.append((number, "quoted speech - machine text goes in "
                                 "backticks", spoken[:110]))
    # Reported in the order they appear, so the list can be worked down
    # the message from the top rather than jumped around.
    return sorted(hits, key=lambda hit: hit[0])


def read_blobs(oids):
    """{oid: bytes} for every oid, in ONE git process.

    `git cat-file --batch` takes oids on stdin and answers
    "<oid> <type> <size>\\n<payload>\\n". One spawn instead of one per
    file: the previous draft ran THREE full blob reads per file and took
    33 seconds over a 300-file staged set - and a gate slow enough to be
    annoying is a gate that gets bypassed with --no-verify.
    """
    if not oids:
        return {}
    try:
        proc = subprocess.run(
            ["git", "cat-file", "--batch"],
            input=("\n".join(oids) + "\n").encode(),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    out, blobs, pos = proc.stdout, {}, 0
    while pos < len(out):
        end = out.find(b"\n", pos)
        if end < 0:
            break
        header = out[pos:end].split()
        pos = end + 1
        if len(header) < 3:
            # "<oid> missing" - fail closed rather than skip silently.
            return None
        size = int(header[2])
        blobs[header[0].decode()] = out[pos:pos + size]
        pos += size + 1
    return blobs


def staged_entries():
    """(status, dst_oid, paths) per staged change, from --raw -z.

    -z means raw unquoted paths; the OID means the content is fetched
    without the path ever being parsed as a revision."""
    # --abbrev=40 because --raw ABBREVIATES oids by default, while
    # `cat-file --batch` echoes the FULL oid in its header - so every
    # lookup missed and the scan refused everything. It failed closed,
    # which is the right direction, but it was still wrong.
    ok, out = run("git", "diff", "--cached", "--raw", "-z", "--abbrev=40")
    if not ok:
        refuse("git diff --cached failed, so the staged set is unknown.")
    fields = out.split(b"\0")
    entries, i = [], 0
    while i < len(fields):
        meta = fields[i]
        if not meta.startswith(b":"):
            i += 1
            continue
        bits = meta[1:].split()
        if len(bits) < 5:
            i += 1
            continue
        dst_oid, status = bits[3].decode(), bits[4].decode()
        count = 2 if status[:1] in ("R", "C") else 1
        paths = fields[i + 1:i + 1 + count]
        entries.append((status, dst_oid, paths))
        i += 1 + count
    return entries


#: Extensions the attribution pass reads. Binary is skipped by git's own
#: NUL rule for the identity scan; here the diff is already text, so the
#: filter is about NOISE - a .usd or a .jpg whose bytes happen to spell
#: pronoun-shaped bytes produced 1,137 of 1,218 raw matches.
ATTRIBUTABLE = (".py", ".md", ".sh", ".txt", ".ui", ".qss", ".xml",
                ".pypanel")


#: A comment block may run to this many sentences. Same ceiling as a
#: commit body, for the same reason: prose grows until something stops
#: it, and the dev log in the private notes is where the story goes.
MAX_COMMENT_SENTENCES = 10

SENTENCE_END = re.compile(r"[.!?](?:\s|$)")

#: A triple-quote OPENS or CLOSES a docstring; it is never speech. Left
#: in place, every added docstring read as a quotation and the gate
#: refused its own source.
TRIPLE = re.compile(r'"""|\'\'\'')

#: Prose, per file kind. In code only a `#` comment or a docstring line
#: is prose; the rest is code, where a string literal is not a
#: quotation and `a.b` is not a sentence. In markdown every line is.
PROSE_MARKUP = (".md", ".txt")

#: Markup, where a quotation mark is SYNTAX. An attribute value in
#: OPmenu.xml or a .ui file is not somebody being quoted.
MARKUP = (".xml", ".ui", ".qss", ".pypanel", ".json")
CODE_COMMENT = re.compile(r'^\s*(?:#|"""|\'\'\'|\*)')

#: This file must contain the patterns it matches, so it cannot be
#: scanned by them - the same reason the identity list lives in the
#: private repo instead of here.
SELF = "tools/git-hooks/amaze_name_scan.py"


def prose_of(path, line):
    """The prose in an added line, or None when the line is not prose."""
    if path.endswith(MARKUP):
        return None
    if path.endswith(PROSE_MARKUP) or CODE_COMMENT.match(line):
        return TRIPLE.sub(" ", line)
    return None


def added_blocks():
    """[(path, first_line, [text, ...])] per run of added lines."""
    ok, out = run("git", "diff", "--cached", "-U0", "--no-color")
    if not ok:
        refuse("git diff --cached failed, so the added lines are unscanned.")
    # DECODED here: run() answers bytes, and a str .startswith against
    # them raises rather than matching - the gate then failed closed on
    # its own TypeError, which is safe and useless.
    out = out.decode("utf-8", "replace")
    blocks, path, number, run_lines, start = [], None, 0, [], 0
    def flush():
        if run_lines and path and path.endswith(ATTRIBUTABLE):
            blocks.append((path, start, list(run_lines)))
        run_lines.clear()
    for raw in out.splitlines():
        if raw.startswith("+++ b/"):
            flush()
            path, number = raw[6:].strip(), 0
        elif raw.startswith("@@"):
            flush()
            try:
                number = int(raw.split("+", 1)[1].split(",", 1)[0]
                             .split(" ", 1)[0]) - 1
            except (IndexError, ValueError):
                number = 0
        elif raw.startswith("+") and not raw.startswith("+++"):
            number += 1
            if not run_lines:
                start = number
            run_lines.append(raw[1:])
        else:
            flush()
    flush()
    return blocks


def added_text_offences():
    """[(path, line, reason, text)] for what this commit ADDS.

    Three rules, and they are the whole policy for text I write:
    no quoted speech, no attribution, at most ten sentences.

    Added lines only. 81 attribution-shaped lines were already committed
    when this was written, so a whole-file rule would refuse every
    commit to those files and be switched off the same day.
    """
    hits = []
    for path, start, lines in added_blocks():
        if path == SELF:
            continue
        prose = []
        for offset, body in enumerate(lines):
            if ADVERTISING.search(body):
                hits.append((path, start + offset,
                             "names the tool that typed it",
                             body.strip()[:110]))
                continue
            for pattern, reason in ATTRIBUTION:
                if pattern.search(body):
                    hits.append((path, start + offset, reason,
                                 body.strip()[:110]))
                    break
            text = prose_of(path, body)
            if text is None:
                continue
            prose.append(text)
            spoken = quoted_speech(text)
            if spoken:
                hits.append((path, start + offset, "a quotation",
                             spoken[:110]))
        joined = " ".join(prose)
        sentences = len(SENTENCE_END.findall(joined))
        if sentences > MAX_COMMENT_SENTENCES:
            hits.append((path, start,
                         "%d sentences, over %d"
                         % (sentences, MAX_COMMENT_SENTENCES),
                         joined.strip()[:110]))
    return hits


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(os.path.dirname(here))
    pattern, _list_path = load_patterns(repo)
    sanitize.url = own_url()
    if sanitize.url and sanitize.url.count("/") >= 2:
        sanitize.owner = "/".join(sanitize.url.split("/")[:2])

    if len(sys.argv) > 2 and sys.argv[1] == "--message":
        path = sys.argv[2]
        if not os.path.isfile(path):
            refuse("no commit message file was given, so it cannot be checked.")
        with open(path, encoding="utf-8", errors="replace") as handle:
            message = handle.read()
        # allow_credit=False: that exemption exists for one string
        # literal in a dialog and has no business excusing a commit
        # message, which is where the breaches actually happened.
        named = scan_text(message, pattern, allow_credit=False)
        prose = scan_message(message)
        if named or prose:
            sys.stderr.write("COMMIT REFUSED - the message carries more "
                             "than the change:\n\n")
            for number, text in named:
                sys.stderr.write("  line %d: names the author\n" % number)
                sys.stderr.write("      %s\n" % text)
            for number, reason, excerpt in prose:
                sys.stderr.write("  line %d: %s\n" % (number, reason))
                if excerpt:
                    sys.stderr.write("      %s\n" % excerpt)
            return 1
        return 0

    entries = staged_entries()
    wanted = [oid for status, oid, _p in entries
              if status[:1] != "D" and set(oid) != {"0"}]
    blobs = read_blobs(sorted(set(wanted)))
    if blobs is None:
        refuse("the staged content could not be read, so it is unscanned.")

    offenders = []
    for status, dst_oid, paths in entries:
        for raw in paths:
            shown = raw.decode("utf-8", "replace")
            if pattern.search(sanitize(shown, allow_credit=False)):
                offenders.append(("path", shown, 0, shown))
        if status[:1] == "D" or set(dst_oid) == {"0"}:
            continue
        blob = blobs.get(dst_oid)
        if blob is None:
            refuse("could not read the staged content of %s"
                   % paths[-1].decode("utf-8", "replace"))
        if b"\0" in blob[:SNIFF]:
            continue                      # binary, per git's own rule
        text = blob.decode("utf-8", "replace")
        shown = paths[-1].decode("utf-8", "replace")
        for number, line in scan_text(text, pattern, allow_credit=True):
            offenders.append(("content", shown, number, line))

    if offenders:
        sys.stderr.write(
            "COMMIT REFUSED - the staged change names the author:\n\n")
        for kind, where, number, text in offenders:
            if kind == "path":
                sys.stderr.write("  path  %s\n" % where)
            else:
                sys.stderr.write("  %s:%d: %s\n" % (where, number, text))
        return 1

    attributed = added_text_offences()
    if attributed:
        sys.stderr.write(
            "COMMIT REFUSED - the text this commit ADDS breaks the "
            "rule:\n\n")
        for where, number, reason, text in attributed:
            sys.stderr.write("  %s:+%d  %s\n      %s\n"
                             % (where, number, reason, text))
        sys.stderr.write(
            "\n  THE RULE: text you add - comments, docstrings, commit\n"
            "  messages - carries NO quotations, names nobody, names no\n"
            "  tool that produced it, and runs to at most %d sentences.\n"
            "  Write what the code now DOES and what you changed, not\n"
            "  what you were asked for and not the discussion that led\n"
            "  there.\n\n"
            "  THE STORY GOES IN THE PRIVATE NOTES, AND THE CODE POINTS\n"
            "  AT IT. 33 comments in this repo already do it:\n\n"
            "      # ...one guarded write each (research.md \u25b8 Widget teardown)\n\n"
            "  research.md for facts about the world, practice.md for\n"
            "  facts about the work, the dev log for what happened.\n"
            "  Move the paragraph there and leave the address.\n\n"
            "  ADDED lines only, so the history already in these files\n"
            "  does not block you - only what this commit puts there.\n\n"
            "  Genuine false positive (a credit, curated content):\n"
            "      AMAZE_ALLOW_PRIVATE=$(git rev-parse HEAD) git commit ...\n"
            % MAX_COMMENT_SENTENCES)
        return 1
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception as exc:                             # noqa: BLE001
        # Fail CLOSED: an unexpected error must never read as clean.
        sys.stderr.write("COMMIT REFUSED - the name scan itself failed: %r\n"
                         % (exc,))
        code = 1
    if code:
        sys.stderr.write(
            "\n  A commit message carries the FUNCTION of the code and the\n"
            "  RESULT of the tests. Not who asked for it, not what was\n"
            "  said, not why it was considered - the diff already shows\n"
            "  what changed, and the dev log in the PRIVATE notes repo is\n"
            "  where the story goes. Machine text - an error string, a UI\n"
            "  label, an identifier - belongs in `backticks`, never in\n"
            "  quotation marks.\n\n"
            "  Fix the lines above, or - for a genuine false positive -\n"
            "  bypass with:\n"
            "      AMAZE_ALLOW_PRIVATE=$(git rev-parse HEAD) git commit ...\n")
    sys.exit(code)
