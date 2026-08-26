"""The comment sweep, ratcheted: the count may fall, never rise. ▸p/comment-standard"""

import ast
import os
import unittest

_ROOT = os.path.abspath(__file__)
for _ in range(5):
    _ROOT = os.path.dirname(_ROOT)

COMMENT_LINES = 12
DOCSTRING_LINES = 20

SCANNED = (".py", ".sh", ".shelf", ".xml")

BUDGET = 40


def _blocks(path):
    """(size, line, what) for every block in one file over the cap."""
    with open(path, encoding="utf-8") as handle:
        source = handle.read()
    found = []
    run = start = 0
    for number, line in enumerate(source.splitlines(), 1):
        if line.strip().startswith("#"):
            start = number if run == 0 else start
            run += 1
            continue
        if run >= COMMENT_LINES:
            found.append((run, start, "comment"))
        run = 0
    if run >= COMMENT_LINES:
        found.append((run, start, "comment"))

    if not path.endswith(".py"):
        return found
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return found
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        doc = ast.get_docstring(node, clean=False)
        if doc and len(doc.splitlines()) >= DOCSTRING_LINES:
            found.append((len(doc.splitlines()),
                          node.body[0].lineno if node.body else 1,
                          "docstring %s" % getattr(node, "name", "<module>")))
    return found


def over_the_cap():
    """Every block in the package over the cap, fattest first."""
    found = []
    for folder, dirs, files in os.walk(_ROOT):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in sorted(files):
            if not name.endswith(SCANNED):
                continue
            path = os.path.join(folder, name)
            for size, line, what in _blocks(path):
                found.append((size, "%s:%d" % (
                    os.path.relpath(path, _ROOT), line), what))
    found.sort(reverse=True)
    return found


class TheCommentBudget(unittest.TestCase):

    def test_no_block_is_added_that_the_sweep_has_not_cut(self):
        found = over_the_cap()
        verdict = ("a fat block was added - say what it DOES and what to "
                   "watch when calling it, and put the rest in the wiki"
                   if len(found) > BUDGET else
                   "the sweep advanced - lower BUDGET to %d" % len(found))
        self.assertEqual(
            BUDGET, len(found),
            "%d blocks over the cap, pinned at %d: %s.\n%s"
            % (len(found), BUDGET, verdict,
               "\n".join("  %4d  %s  %s" % row for row in found[:10])))

    def test_the_scan_can_find_a_block(self):
        """A budget test that scans nothing passes forever."""
        self.assertTrue(
            over_the_cap(),
            "the scan found no block at all, so it cannot fail when one "
            "is added - the counter is broken, not the package clean")
