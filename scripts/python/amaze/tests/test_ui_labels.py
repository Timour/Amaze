"""No user-facing string names a retired control - string LITERALS only, across the package and MANUAL.md. Add a rename to RETIRED; leave out any name that still has a live reading ▸p/quoted-strings-go-stale"""

import ast
import os
import sys
import unittest

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.tests import test_support  # noqa: E402,F401

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

    def test_no_message_or_manual_passage_names_a_retired_control(self):
        """A planted literal must be found first, or a scan reading no files would pass."""
        planted = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "_planted_probe.py")
        with open(planted, "w", encoding="utf-8") as handle:
            handle.write('"""A docstring naming Rerender Thumbnail."""\n'
                         '# a comment naming Rerender Thumbnail\n'
                         'MESSAGE = "use Rerender Thumbnail"\n')
        self.addCleanup(os.remove, planted)
        self.assertEqual([3], [line for line, text in _literals(planted)
                               if "Rerender Thumbnail" in text])
        hits = [(path, line, old)
                for path in _package_modules()
                for line, text in _literals(path)
                for old in RETIRED if old in text]
        live = [h for h in hits if _waiver(h[0], h[2]) not in DEFERRED]
        with self.subTest(source="package"):
            self.assertEqual(
                [], live,
                "a message tells the user to use a control that does not "
                "exist:\n%s\nRename it, or if the control came back, take "
                "it out of RETIRED here." % self._report(live))
        manual = os.path.join(REPO, "MANUAL.md")
        self.assertTrue(os.path.exists(manual), manual)
        with open(manual, encoding="utf-8") as handle:
            hits = [(manual, number, old)
                    for number, text in enumerate(handle, 1)
                    for old in RETIRED if old in text]
        with self.subTest(source="MANUAL.md"):
            self.assertEqual(
                [], hits,
                "the shipped manual documents a control that does not "
                "exist:\n%s" % self._report(hits))

    def test_every_picture_the_docs_show_is_a_file_that_exists(self):
        """A deleted or renamed art file leaves a blank picture in the manual."""
        import re
        pictures = re.compile(r'<img[^>]*\bsrc="([^"]+)"|!\[[^\]]*\]\(([^)\s]+)\)')
        missing, seen = [], 0
        for doc in ("MANUAL.md", "README.md"):
            with open(os.path.join(REPO, doc), encoding="utf-8") as handle:
                for number, text in enumerate(handle, 1):
                    for found in pictures.findall(text):
                        src = found[0] or found[1]
                        seen += 1
                        if "://" not in src and not os.path.exists(os.path.join(REPO, src)):
                            missing.append("%s:%d %s" % (doc, number, src))
        self.assertGreater(seen, 10, "the scan found almost no pictures - it is not reading them")
        self.assertEqual([], missing, "the docs show pictures that are not there")


if __name__ == "__main__":
    unittest.main()
