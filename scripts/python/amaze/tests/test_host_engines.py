"""The two host engines own their branches - enforced, not requested.

hostos.py has said "nothing else in the codebase may test sys.platform"
since it was written, and nothing checked. A rule that lives only in a
docstring is a rule until the first hurry.

These are SOURCE-DERIVED tests: the property is structural, and driving
it would need three operating systems and two Houdini installs, so the
assertion is made against the files themselves. Comments and strings
are tokenized out first - an earlier source-derived test in this project
failed on the comment that documented the very fix it was checking.
"""

import os
import sys
import tokenize
import unittest

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _code_only(path):
    """The file's source with comments and strings removed, so a rule
    documented in prose cannot fail the rule it documents.

    Tokens are reassembled BY LINE. The first version of this joined
    every token with a newline, which put `hou`, `.`,
    `applicationVersion`, `(`, `)` and `[` on six separate lines - so a
    line-wise search for `applicationVersion()[` could never match
    anything, and every test built on it passed while searching text
    that cannot contain what it looks for. The inline sabotage test
    below is what exposed it.
    """
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
            # A space only between two word-ish tokens, so `import os`
            # survives while `hou.applicationVersion()[0]` stays intact.
            if line and (line[-1].isalnum() or line[-1] == "_") and \
                    (piece[0].isalnum() or piece[0] == "_"):
                line += " "
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
        """Every version difference goes through hostver, as a named
        capability. A raw comparison at a call site is invisible to
        anyone not running that version - which is how a y-flip aimed
        the H21 viewport pick at the wrong end of the screen for days."""
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
        """Sabotage, inline. Both tests above pass trivially if the walk
        finds nothing or the tokenizer eats everything. Run the same
        scan WITHOUT the exclusion: hostver.py itself must show up, or
        the machinery is not searching real code."""
        hits = self._offenders("no_such_file.py", ("applicationVersion()[",))
        self.assertTrue(
            any("hostver.py" in h for h in hits),
            "the scan cannot even find the comparison inside hostver.py, "
            "so a green result above means nothing. Found: %s" % hits)

    def test_prose_about_the_rule_does_not_trip_the_rule(self):
        """The trap this file's own docstring names: a source-derived
        test that matches its explanatory comments fails on the fix it
        documents. hostos.py's docstring says the words 'sys.platform'."""
        code = _code_only(os.path.join(_PKG, "helpers", "hostos.py"))
        self.assertNotIn(
            "nothing else in the codebase", code,
            "the tokenizer is no longer stripping docstrings")


class TestHostVerAnswers(unittest.TestCase):
    """The engine hands out ANSWERS, not version numbers."""

    def test_it_exposes_capabilities_rather_than_comparisons(self):
        from amaze.helpers import hostver
        for name in ("obj_pick_wants_device_pixels", "has_new_cops"):
            self.assertTrue(callable(getattr(hostver, name, None)),
                            "hostver.%s is missing" % name)

    def test_every_capability_is_a_bool(self):
        from amaze.helpers import hostver
        self.assertIsInstance(hostver.obj_pick_wants_device_pixels(2.0), bool)
        self.assertIsInstance(hostver.has_new_cops(), bool)

    def test_a_broken_hou_does_not_take_the_app_down(self):
        """houdini_major() is consulted during a drag; if it raises, the
        gesture must degrade, not crash the panel."""
        import hou
        from amaze.helpers import hostver
        real = hou.applicationVersion
        self.addCleanup(setattr, hou, "applicationVersion", real)

        def _boom():
            raise RuntimeError("no application")

        hou.applicationVersion = _boom
        self.assertEqual(0, hostver.houdini_major())
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

    def test_an_environment_matching_nothing_takes_the_base(self):
        hv = self._hv()
        cap = hv.Capability(base="documented", base_evidence="e" * 50)
        self.assertEqual("documented", cap.resolve(self._env()))

    def test_an_applying_opinion_overrides_the_base(self):
        hv = self._hv()
        cap = hv.Capability(
            base="documented", base_evidence="e" * 50,
            opinions=(hv.Opinion("workaround",
                                 (("always", lambda env: True),),
                                 "e" * 50),))
        self.assertEqual("workaround", cap.resolve(self._env()))

    def test_every_condition_must_hold(self):
        """ALL conditions, not any - the macOS condition went missing
        once and a macOS workaround was applied to Windows."""
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
        """The payoff. A report from a machine nobody here can
        reproduce should arrive with its composition already resolved -
        not "the workaround did not apply" but "it did not apply
        because this is not macOS"."""
        hv = self._hv()
        report = hv.OBJ_PICK_DEVICE_PIXELS.explain(
            self._env(macos=False, windows=True))
        self.assertFalse(report["resolved"])
        vetoes = [o["vetoed_by"] for o in report["opinions"]
                  if not o["applied"]]
        self.assertTrue(any("macOS" in (v or "") for v in vetoes),
                        "explain() did not name the macOS veto: %s" % vetoes)

    def test_explain_reports_the_environment_it_judged(self):
        hv = self._hv()
        report = hv.OBJ_PICK_DEVICE_PIXELS.explain(self._env())
        self.assertIn("21", report["env"])
        self.assertIn("macos", report["env"])

    def test_the_h21_mac_retina_case_resolves_to_the_workaround(self):
        hv = self._hv()
        self.assertTrue(hv.OBJ_PICK_DEVICE_PIXELS.resolve(self._env()))

    def test_every_h22_build_takes_the_base(self):
        """No 22.0.x below 393 has ever run here, so the series is not
        split on the changelog's inference."""
        hv = self._hv()
        for build in ((22, 0, 0), (22, 0, 390), (22, 0, 391), (22, 0, 394)):
            self.assertFalse(
                hv.OBJ_PICK_DEVICE_PIXELS.resolve(self._env(houdini=build)),
                "%s got a workaround it was never measured to need"
                % (build,))

    def test_a_future_version_takes_the_base_not_the_workaround(self):
        """The reason the base is the DOCUMENTED behaviour rather than
        the oldest one: H23 must not inherit a Retina workaround from a
        version it has nothing to do with."""
        hv = self._hv()
        self.assertFalse(
            hv.OBJ_PICK_DEVICE_PIXELS.resolve(self._env(houdini=(23, 0, 1))))

    def test_an_unknown_houdini_takes_the_base(self):
        hv = self._hv()
        self.assertFalse(
            hv.OBJ_PICK_DEVICE_PIXELS.resolve(self._env(houdini=())))

    def test_an_unscaled_display_takes_the_base(self):
        hv = self._hv()
        self.assertFalse(
            hv.OBJ_PICK_DEVICE_PIXELS.resolve(self._env(scale=1.0)))

    def test_a_raising_predicate_vetoes_instead_of_propagating(self):
        """A capability is consulted inside a mouse handler. A broken
        predicate must degrade to the base, not kill the gesture."""
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
        """A version branch without evidence is a guess that outlives
        whoever guessed. Enforced, not requested."""
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


if __name__ == "__main__":
    unittest.main()
