"""The two host engines own their branches, checked on source with comments and strings removed."""

import os
import sys
import tokenize
import unittest

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.tests import test_support  # noqa: F401

_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _code_only(path):
    """Source without comments and strings, rejoined by line so a line-wise search can still match."""
    with open(path, "rb") as fh:
        try:
            toks = list(tokenize.tokenize(fh.readline))
        except (tokenize.TokenError, IndentationError, SyntaxError):
            fh.seek(0)
            return fh.read().decode("utf-8", "replace")
    rows = {}
    for tok in toks:
        if tok.type in (tokenize.COMMENT, tokenize.STRING,
                        tokenize.NL, tokenize.NEWLINE, tokenize.INDENT,
                        tokenize.DEDENT, tokenize.ENCODING,
                        tokenize.ENDMARKER):
            continue
        rows.setdefault(tok.start[0], []).append(tok.string)
    out = []
    for row in sorted(rows):
        line = ""
        for piece in rows[row]:
            if line and (line[-1].isalnum() or line[-1] == "_") and \
                    (piece[0].isalnum() or piece[0] == "_"):
                line += " "  # a space only between two word-ish tokens
            line += piece
        out.append(line)
    return "\n".join(out)


def _modules(exclude):
    """Every shipped .py, minus the tests and the named owner."""
    for root, dirs, files in os.walk(_PKG):
        dirs[:] = [d for d in dirs
                   if d not in ("tests", "__pycache__", "res", "ui")]
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            if os.path.basename(path) in exclude:
                continue
            yield os.path.relpath(path, _PKG), path


class TestHostEngineOwnership(unittest.TestCase):

    def _offenders(self, owner, needles):
        found = []
        checked = 0
        for rel, path in _modules({owner}):
            checked += 1
            code = _code_only(path)
            for line_no, line in enumerate(code.splitlines(), 1):
                if any(n in line for n in needles):
                    found.append("%s: %s" % (rel, line.strip()[:90]))
        self.assertGreater(
            checked, 10,
            "only %d modules were scanned - the walk is not reaching the "
            "package and this test is not exercising the case it was "
            "written for" % checked)
        return found

    def test_no_module_branches_on_the_houdini_version(self):
        """Every version difference goes through hostver as a named capability, never a raw compare."""
        offenders = self._offenders(
            "hostver.py",
            ("applicationVersion()[", "applicationVersion ()["))
        self.assertEqual(
            [], offenders,
            "raw Houdini version comparisons outside hostver.py - move "
            "the knowledge into a named capability there:\n  %s"
            % "\n  ".join(offenders))

    def test_no_module_tests_the_platform_directly(self):
        """hostos.py's own rule, finally checked."""
        offenders = self._offenders(
            "hostos.py", ("sys.platform", "platform.system("))
        self.assertEqual(
            [], offenders,
            "platform tests outside hostos.py:\n  %s"
            % "\n  ".join(offenders))

    def test_the_scan_survives_the_owner_being_excluded(self):
        """Sabotage: without the exclusion the scan must find hostver.py, or the greens mean nothing."""
        hits = self._offenders("no_such_file.py", ("applicationVersion()[",))
        self.assertTrue(
            any("hostver.py" in h for h in hits),
            "the scan cannot even find the comparison inside hostver.py, "
            "so a green result above means nothing. Found: %s" % hits)


class TestHostVerAnswers(unittest.TestCase):
    """The engine hands out ANSWERS, not version numbers."""

    def test_every_capability_is_a_bool(self):
        from amaze.helpers import hostver
        self.assertIsInstance(hostver.obj_pick_wants_device_pixels(2.0), bool)
        self.assertIsInstance(hostver.has_new_cops(), bool)

    def test_a_broken_hou_does_not_take_the_app_down(self):
        """houdini_version() feeds every capability Env; if hou raises, a gesture degrades, not crashes."""
        import hou
        from amaze.helpers import hostver
        real = hou.applicationVersion
        self.addCleanup(setattr, hou, "applicationVersion", real)

        def _boom():
            raise RuntimeError("no application")

        hou.applicationVersion = _boom
        self.assertEqual((), hostver.houdini_version())
        self.assertIsInstance(hostver.obj_pick_wants_device_pixels(2.0), bool)


class TestOpinionComposition(unittest.TestCase):
    """base value + opinions that apply to THIS environment."""

    def _hv(self):
        from amaze.helpers import hostver
        return hostver

    def _env(self, **kw):
        hv = self._hv()
        base = dict(houdini=(21, 0, 790), macos=True, windows=False,
                    linux=False, scale=2.0)
        base.update(kw)
        return hv.Env(**base)

    def test_every_condition_must_hold(self):
        """ALL conditions, not any - a macOS workaround once reached Windows."""
        hv = self._hv()
        cap = hv.Capability(
            base="documented", base_evidence="e" * 50,
            opinions=(hv.Opinion(
                "workaround",
                (("houdini", lambda env: bool(env.houdini)),
                 ("macos", lambda env: env.macos)),
                "e" * 50),))
        self.assertEqual("workaround", cap.resolve(self._env(macos=True)))
        self.assertEqual("documented",
                         cap.resolve(self._env(macos=False, windows=True)))

    def test_the_strongest_applying_opinion_wins(self):
        hv = self._hv()
        always = lambda env: True                        # noqa: E731
        cap = hv.Capability(
            base="base", base_evidence="e" * 50,
            opinions=(hv.Opinion("weak", (("a", always),), "e" * 50,
                                 strength=0),
                      hv.Opinion("strong", (("b", always),), "e" * 50,
                                 strength=10)))
        self.assertEqual("strong", cap.resolve(self._env()))

    def test_explain_names_the_condition_that_vetoed(self):
        """explain() names which condition vetoed, not just that one did."""
        hv = self._hv()
        report = hv.OBJ_PICK_DEVICE_PIXELS.explain(
            self._env(macos=False, windows=True))
        self.assertFalse(report["resolved"])
        vetoes = [o["vetoed_by"] for o in report["opinions"]
                  if not o["applied"]]
        self.assertTrue(any("macOS" in (v or "") for v in vetoes),
                        "explain() did not name the macOS veto: %s" % vetoes)
        judged = hv.OBJ_PICK_DEVICE_PIXELS.explain(self._env())["env"]
        self.assertIn("21", judged)
        self.assertIn("macos", judged)

    def test_only_the_h21_mac_retina_case_takes_the_workaround(self):
        hv = self._hv()
        for env, wanted in (({}, True),
                            ({"houdini": (22, 0, 390)}, False),    # no 22.0 build split off by the changelog
                            ({"houdini": (23, 0, 1)}, False),    # the base is the documented answer
                            ({"houdini": ()}, False),
                            ({"scale": 1.0}, False)):
            with self.subTest(env=env):
                self.assertEqual(
                    wanted,
                    hv.OBJ_PICK_DEVICE_PIXELS.resolve(self._env(**env)),
                    "%s got the answer it was never measured to need" % env)

    def test_a_raising_predicate_vetoes_instead_of_propagating(self):
        """Consulted inside a mouse handler, a broken predicate degrades to the base, never kills it."""
        hv = self._hv()

        def _boom(env):
            raise RuntimeError("nope")

        cap = hv.Capability(
            base="base", base_evidence="e" * 50,
            opinions=(hv.Opinion("never", (("boom", _boom),), "e" * 50),))
        self.assertEqual("base", cap.resolve(self._env()))
        report = cap.explain(self._env())
        self.assertIn("raised", report["opinions"][0]["vetoed_by"])

    def test_every_opinion_and_base_carries_real_evidence(self):
        """Every base and opinion carries evidence; a version branch without it is a guess."""
        hv = self._hv()
        caps = [(n, getattr(hv, n)) for n in dir(hv)
                if n.isupper() and isinstance(getattr(hv, n), hv.Capability)]
        self.assertTrue(caps, "no capabilities found - this test is not "
                              "exercising the case it was written for")
        for name, cap in caps:
            self.assertGreater(
                len(cap.base_evidence or ""), 40,
                "%s base has no real evidence" % name)
            for opinion in cap.opinions:
                self.assertGreater(
                    len(opinion.evidence or ""), 40,
                    "%s opinion %r has no real evidence"
                    % (name, opinion.describe()))
                self.assertTrue(
                    opinion.conditions,
                    "%s has an unconditional opinion - that is a base, "
                    "not an opinion" % name)


class AFailedWriteSaysWhichFailure(unittest.TestCase):
    """`hostos.why_failed` answers from the measured errno, never a guessed cause. ▸r/failed-write"""

    def _cause(self, number):
        from amaze.helpers import hostos

        cause, sentence = hostos.why_failed(
            OSError(number, os.strerror(number)), "/lib/notes.json")
        self.assertTrue(sentence.strip(), "no sentence for errno %s"
                        % number)
        return cause, sentence

    def test_each_measured_errno_gets_its_own_cause(self):
        import errno

        from amaze.helpers import hostos

        for number, cause, says, never in (
                (errno.ENOENT, hostos.FAILED_UNREACHABLE, "cannot be reached",
                 ("another program",)),
                (errno.EACCES, hostos.FAILED_READ_ONLY, "folder", ()),    # POSIX rename asks the FOLDER
                (errno.EROFS, hostos.FAILED_READ_ONLY, "", ()),
                (errno.ENOSPC, hostos.FAILED_FULL, "", ()),
                (999, hostos.FAILED_UNKNOWN, "",    # unmeasured: claim no cause at all
                 ("another program", "read-only", "full", "cannot be reached"))):
            with self.subTest(errno=number):
                got, sentence = self._cause(number)
                self.assertEqual(cause, got)
                self.assertIn(says, sentence)
                for invented in never:
                    self.assertNotIn(invented, sentence,
                                     "errno %s was given a cause it does "
                                     "not have" % number)

    def _windows_cause(self, winerror):
        """A held file the way WINDOWS raises it, which no POSIX host can produce."""
        import errno

        from amaze.helpers import hostos

        exc = OSError(errno.EACCES, os.strerror(errno.EACCES))
        exc.winerror = winerror  # OSError drops a winerror off Windows, so set it by hand
        return hostos.why_failed(exc, "/lib/notes.json")

    def test_a_held_file_is_recognised_in_its_WINDOWS_spelling(self):
        """A held destination is real only on Windows, and there it arrives as EACCES, not EBUSY."""
        from amaze.helpers import hostos

        for winerror, cause in ((32, hostos.FAILED_HELD), (33, hostos.FAILED_HELD),
                                (5, hostos.FAILED_READ_ONLY)):    # EACCES alone is ambiguous
            with self.subTest(winerror=winerror):
                got, sentence = self._windows_cause(winerror)
                self.assertEqual(cause, got,
                                 "winerror %d was misread" % winerror)
                self.assertEqual(cause == hostos.FAILED_HELD,
                                 "another program" in sentence)


if __name__ == "__main__":
    unittest.main()
