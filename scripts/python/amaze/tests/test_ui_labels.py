"""No user-facing string names a retired control - string LITERALS only, across the package and MANUAL.md. Add a rename to RETIRED; leave out any name that still has a live reading ▸p/quoted-strings-go-stale"""

import ast
import os
import sys
import unittest

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(PACKAGE)))

RETIRED = {    # retired label -> what the app calls it now, which the failure message quotes; three near-misses are deliberately absent ▸p/quoted-strings-go-stale
    "Rerender Thumbnail": "Update Preview",
    "Render Thumbnail": "Update Preview",
    "Delete Entry": "Delete",
    "Edit Info": "Info",
    "Toggle Favorite": "Favorite",
    "Edit Icon": "Customize",
    "New Snippet": "New File",
    "Apply to Selected Node": "Apply",
    "Import to MAT": "Copy To /mat",    # CASE is what separates this from the live "Import to Materials" - lower-case it and the match swallows an entry that still exists
    "Import to LOP": "Copy To /stage",
}

DEFERRED = set()    # (module, label) waived while its file is too expensive to open; empty since A11 stage C paid panel.py's sweep ▸p/line-keyed-register


def _literals(path):
    """(lineno, text) for every string literal that is NOT a docstring."""
    with open(path, encoding="utf-8") as handle:
        source = handle.read()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []                # not ours to police; py_compile owns syntax
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef,
                             ast.FunctionDef, ast.AsyncFunctionDef)):
            text = ast.get_docstring(node, clean=False)
            if text is not None:
                docs.add(text)
    return [(node.lineno, node.value) for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value not in docs]


def _waiver(path, label):
    return (os.path.relpath(path, PACKAGE).replace(os.sep, "/"), label)


def _package_modules():
    for root, dirs, files in os.walk(PACKAGE):
        dirs[:] = [d for d in dirs if d != "tests"]    # RETIRED lives here
        for name in sorted(files):
            if name.endswith(".py"):
                yield os.path.join(root, name)


class RetiredLabelsAreGone(unittest.TestCase):

    def _report(self, hits):
        return "\n".join(
            "  %s:%d names %r - the control is %r"
            % (os.path.relpath(path, REPO), line, old, RETIRED[old])
            for path, line, old in hits)

    def test_no_app_message_names_a_retired_control(self):
        hits = [(path, line, old)
                for path in _package_modules()
                for line, text in _literals(path)
                for old in RETIRED if old in text]
        live = [h for h in hits if _waiver(h[0], h[2]) not in DEFERRED]
        self.assertEqual(
            [], live,
            "a message tells the user to use a control that does not "
            "exist:\n%s\nRename it, or if the control came back, take it "
            "out of RETIRED here." % self._report(live))

    def test_no_deferral_outlives_the_string_it_covers(self):
        """A waiver kept past its fix is a hole nobody is watching, so each one must still find its string ▸p/quoted-strings-go-stale"""
        covered = {_waiver(path, old)
                   for path in _package_modules()
                   for _line, text in _literals(path)
                   for old in RETIRED if old in text}
        self.assertEqual(
            set(), DEFERRED - covered,
            "DEFERRED waives a string that is already gone: %s. The "
            "cleanup landed - delete the entry, and strike ROADMAP line "
            "30 > A11's label clause with it."
            % sorted(DEFERRED - covered))

    def test_no_manual_passage_names_a_retired_control(self):
        manual = os.path.join(REPO, "MANUAL.md")
        self.assertTrue(os.path.exists(manual), manual)
        with open(manual, encoding="utf-8") as handle:
            hits = [(manual, number, old)
                    for number, text in enumerate(handle, 1)
                    for old in RETIRED if old in text]
        self.assertEqual(
            [], hits,
            "the shipped manual documents a control that does not "
            "exist:\n%s" % self._report(hits))

    def test_the_scanner_can_actually_see_a_bad_string(self):
        """Passing by finding nothing is what a scanner reading NO files also reports, so plant one - on the literal, not the docstring or the comment beside it."""
        planted = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "_planted_probe.py")
        with open(planted, "w", encoding="utf-8") as handle:
            handle.write('"""A docstring naming Rerender Thumbnail."""\n'
                         '# a comment naming Rerender Thumbnail\n'
                         'MESSAGE = "use Rerender Thumbnail"\n')
        self.addCleanup(os.remove, planted)
        seen = [line for line, text in _literals(planted)
                if "Rerender Thumbnail" in text]
        self.assertEqual([3], seen)

    def test_every_retired_label_has_a_current_replacement(self):
        """A failure message that names no live control sends the reader nowhere."""
        for old, new in RETIRED.items():
            self.assertTrue(new and new.strip(), old)
            self.assertNotIn(old, new, "%r cannot replace itself" % old)


if __name__ == "__main__":
    unittest.main()
