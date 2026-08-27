#!/usr/bin/env python3
"""Refuse a staged commit or message carrying personal data. ▸p/name-gate"""
import ast
import os
import re
import subprocess
import sys

SNIFF = 8000

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
    """The compiled identity pattern and its path; refuses if unusable."""
    explicit = os.environ.get("AMAZE_PRIVATE_NAMES")
    if explicit:
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
    """The repo's OWN address, discovered not hardcoded. ▸p/name-gate"""
    ok, out = run("git", "config", "--get", "remote.origin.url")
    if not ok:
        return None
    url = out.decode("utf-8", "replace").strip()
    url = re.sub(r"^[a-z+]*://", "", url)
    url = re.sub(r"^[^@]*@", "", url).replace(":", "/")
    url = re.sub(r"\.git$", "", url).rstrip("/")
    return url or None


CREDIT = re.compile(r'^\s*"<p>By [A-Za-z.]+(?: [A-Za-z.]+){0,3}<br>"\s*$')


def api_owner(owner):
    """The same host/owner prefix in the API spelling, or None. ▸p/name-gate"""
    if not owner:
        return None
    host, _, name = owner.partition("/")
    return "api.%s/repos/%s" % (host, name) if host and name else None


def raw_owner(owner):
    """The same account prefix in the raw-content spelling, or None - a package-feed constant is our own url as much as the origin is. ▸p/name-gate"""
    if not owner:
        return None
    host, _, name = owner.partition("/")
    return "raw.githubusercontent.com/%s" % name if host == "github.com" and name else None


def sanitize(line, allow_credit):
    """A line with our own url, owner and invisible marks removed. ▸p/name-gate"""
    line = INVISIBLE.sub("", line)
    url = sanitize.url
    if url:
        line = re.sub(r"[a-z+]*://" + re.escape(url) + r"\S*", "", line)
        line = re.sub(re.escape(url) + r"\S*", "", line)
    for owner in (sanitize.owner, sanitize.api_owner, sanitize.raw_owner):
        if owner:
            line = re.sub(re.escape(owner) + r"(?![A-Za-z0-9._-])", "", line)
    if allow_credit and CREDIT.match(line):
        return ""
    return line


sanitize.url = None
sanitize.owner = None
sanitize.api_owner = None
sanitize.raw_owner = None


def scan_text(text, pattern, allow_credit):
    hits = []
    for number, line in enumerate(text.splitlines(), 1):
        if pattern.search(sanitize(line, allow_credit)):
            hits.append((number, line.strip()[:120]))
    return hits


MAX_SUBJECT_CHARS = 72
MAX_BODY_LINES = 4

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
    (re.compile(r"\b(?:someone|somebody|anyone|anybody|whoever)\b", re.I),
     "an unnamed person described instead of the change"),
    (re.compile(r"\b(?:unsure|stressed|confused|worried|anxious|nervous|"
                r"frustrated|scared|reassur\w+|comforting|alarming)\b", re.I),
     "a reader's state of mind, which is not what the code does"),
    (re.compile(r"\bas (?:he|she|they) (?:put it|said|described)\b"
                r"|\bper (?:his|her|their) (?:call|chat|instruction|request)\b"
                r"|\bI (?:told|asked)\b"
                r"|\bwe (?:agreed|discussed|decided)\b"
                r"|\byou (?:asked|said|wanted|told me|reported)\b"
                r"|\bas discussed\b|\bper the chat\b|\breported by\b", re.I),
     "a conversation recorded instead of a reason"),
)

BACKTICK = re.compile(r"`[^`]*`")
FENCE = re.compile(r"^\s*```")

QUOTED = (
    re.compile(r'"([^"\n]{2,400})"'),
    re.compile("“([^”\n]{2,400})”"),
    re.compile(r"(?<![A-Za-z])'([^'\n]{2,400})'(?![A-Za-z])"),
    re.compile("‘([^’\n]{2,400})’"),
)
HAS_LETTER = re.compile(r"[A-Za-z]")

QUOTE_MIN_WORDS = 3

ADVERTISING = re.compile(
    r"co-authored-by:\s*(?:claude|[^<]*anthropic)"
    r"|generated with \[?claude"
    r"|noreply@anthropic\.com"
    r"|\bclaude(?:\.ai|\s*code|\s*opus|\s*sonnet|\s*haiku)?\b"
    r"|\banthropic\b"
    r"|\b(?:written|made|authored|generated|created)\s+(?:with|by)\s+"
    r"(?:an?\s+)?(?:ai|llm|assistant|agent|bot)\b", re.I)


def quoted_speech(text):
    """The first quoted span of QUOTE_MIN_WORDS words or more. ▸p/name-gate"""
    for pattern in QUOTED:
        for match in pattern.finditer(BACKTICK.sub(" ", text)):
            inner = match.group(1)
            if len([w for w in inner.split() if HAS_LETTER.search(w)]) \
                    >= QUOTE_MIN_WORDS:
                return inner
    return None


def paragraphs(text):
    """[(first_line, joined_text)] per blank-line block, JOINED. ▸p/name-gate"""
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
    return sorted(hits, key=lambda hit: hit[0])


def read_blobs(oids):
    """{oid: bytes} for every oid, in ONE git process. ▸r/git-hook-surface"""
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
            return None
        size = int(header[2])
        blobs[header[0].decode()] = out[pos:pos + size]
        pos += size + 1
    return blobs


def staged_entries():
    """(status, dst_oid, paths) per staged change. ▸r/git-hook-surface"""
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


ATTRIBUTABLE = (".py", ".md", ".sh", ".txt", ".ui", ".qss", ".xml",
                ".pypanel")

MAX_COMMENT_SENTENCES = 10

SENTENCE_END = re.compile(r"[.!?](?:\s|$)")

TRIPLE = re.compile(r'"""|\'\'\'')

PROSE_MARKUP = (".md", ".txt")

MARKUP = (".xml", ".ui", ".qss", ".pypanel", ".json")
CODE_COMMENT = re.compile(r'^\s*(?:#|"""|\'\'\'|\*)')

SELF = "tools/git-hooks/amaze_name_scan.py"


def prose_of(path, line):
    """The prose in an added line, or None when the line is not prose."""
    if path.endswith(MARKUP):
        return None
    if path.endswith(PROSE_MARKUP) or CODE_COMMENT.match(line):
        return TRIPLE.sub(" ", line)
    return None


def countable_prose(path, lines):
    """The prose the sentence ceiling measures, summaries out. ▸p/name-gate"""
    if path.endswith(PROSE_MARKUP):
        return " ".join(t for t in (prose_of(path, b) for b in lines)
                        if t is not None)
    out, in_doc, summary = [], False, False
    for body in lines:
        marks = len(TRIPLE.findall(body))
        opening = bool(marks) and not in_doc
        inside = in_doc and not opening
        text = prose_of(path, body)
        if text is None and inside:
            text = TRIPLE.sub(" ", body)
        if opening:
            in_doc, summary = (marks % 2 == 1), True
        elif marks and in_doc:
            in_doc = False
        if text is None:
            summary = False
            continue
        if summary:
            end = SENTENCE_END.search(text)
            if end:
                text, summary = text[end.end():], False
            else:
                text = ""
        out.append(text)
    return " ".join(out)


def added_blocks():
    """[(path, first_line, [text, ...])] per run of added lines."""
    ok, out = run("git", "diff", "--cached", "-U0", "--no-color")
    if not ok:
        refuse("git diff --cached failed, so the added lines are unscanned.")
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


MAX_COMMENT_LINES = 1

DIRECTIVE = re.compile(
    r'^\s*#\s*(?:!|-\*-|type:|noqa|pylint|pragma|shellcheck|:type|:rtype)')


def comment_lines_by_scope(source):
    """{scope: [line numbers]}, `#` lines and docstrings alike. ▸p/comment-standard"""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    lines = source.splitlines()
    starts = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            first = min([node.lineno]
                        + [d.lineno for d in node.decorator_list])
            starts.append((first, node.name, node))
    starts.sort()

    def owner(number):
        name = "<module>"
        for first, scope_name, node in starts:
            if first <= number <= getattr(node, "end_lineno", first):
                name = scope_name
        return name

    found = {}
    for number, line in enumerate(lines, 1):
        if line.strip().startswith("#") and not DIRECTIVE.match(line):
            found.setdefault(owner(number), []).append(number)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        doc = ast.get_docstring(node, clean=False)
        if not doc:
            continue
        name = getattr(node, "name", "<module>")
        first = node.body[0].lineno
        found.setdefault(name, []).extend(
            range(first, first + len(doc.splitlines())))
    return found


def comment_budget_offences():
    """[(path, line, reason, text)] per scope over the cap, WHOLE-file."""
    entries = staged_entries()
    if entries is None:
        return None
    wanted = {}
    for status, oid, paths in entries:
        if status[:1] == "D" or set(oid) == {"0"}:
            continue
        path = paths[-1].decode("utf-8", "replace")
        if path.endswith(".py"):
            wanted[oid] = path
    blobs = read_blobs(list(wanted))
    if blobs is None:
        return None
    hits = []
    for oid, path in sorted(wanted.items(), key=lambda kv: kv[1]):
        try:
            source = blobs[oid].decode("utf-8")
        except (KeyError, UnicodeDecodeError):
            return None
        for scope, numbers in sorted(comment_lines_by_scope(source).items()):
            if len(numbers) > MAX_COMMENT_LINES:
                hits.append((path, min(numbers),
                             "%s carries %d comment lines, over %d"
                             % (scope, len(numbers), MAX_COMMENT_LINES),
                             "one line, then an id into AmazeNotes"))
    return hits


def added_text_offences():
    """[(path, line, reason, text)] for ADDED lines only. ▸p/name-gate"""
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
        joined = countable_prose(path, lines)
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
        sanitize.api_owner = api_owner(sanitize.owner)
        sanitize.raw_owner = raw_owner(sanitize.owner)

    if len(sys.argv) > 2 and sys.argv[1] == "--message":
        path = sys.argv[2]
        if not os.path.isfile(path):
            refuse("no commit message file was given, so it cannot be checked.")
        with open(path, encoding="utf-8", errors="replace") as handle:
            message = handle.read()
        # allow_credit=False: the About-box exemption is for a dialog only.
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
            "  AT IT:\n\n"
            "      # ...one guarded write each (research.md \u25b8 Widget teardown)\n\n"
            "  research.md for facts about the world, practice.md for\n"
            "  facts about the work, the dev log for what happened.\n"
            "  Move the paragraph there and leave the address.\n\n"
            "  ADDED lines only, so the history already in these files\n"
            "  does not block you - only what this commit puts there.\n\n"
            "  Genuine false positive (a credit, curated content):\n"
            "      AMAZE_ALLOW_MESSAGE=$(git rev-parse HEAD) git commit ...   (message only)\n"
            % MAX_COMMENT_SENTENCES)
        return 1

    budget = comment_budget_offences()
    if budget is None:
        refuse("the staged content could not be read, so it is unscanned.")
    if budget:
        sys.stderr.write(
            "COMMIT REFUSED - a scope carries more than %d comment "
            "line:\n\n" % MAX_COMMENT_LINES)
        for where, number, reason, text in budget:
            sys.stderr.write("  %s:%d  %s\n      %s\n"
                             % (where, number, reason, text))
        sys.stderr.write(
            "\n  ONE LINE per module, class and function. Say what it\n"
            "  DOES and what to watch when calling it. Everything else\n"
            "  goes to AmazeNotes and the code keeps the id:\n\n"
            "      # ...cannot take a hotkey. ▸r/hotkeys\n\n"
            "  Whole-file, not added lines: a file you touch is a file\n"
            "  you bring under the cap.\n")
        return 1
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception as exc:                             # noqa: BLE001
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
            "      AMAZE_ALLOW_MESSAGE=$(git rev-parse HEAD) git commit ...   (message only)\n")
    sys.exit(code)
