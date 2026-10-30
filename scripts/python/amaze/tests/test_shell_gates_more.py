"""The gate scripts' slower cases - each runs a hook in a throwaway git repo - kept out of the default run and run when tools/ changes. ▸p/gate-fixture-safety"""

import json
import os
import subprocess
import unittest

from amaze.tests import impact_map
from amaze.tests import test_support  # noqa: F401 - arms the sandbox
from amaze.tests.test_shell_gates import (
    GateFixture,
    PUSH_END,
    PUSH_GREEN_MSG,
    PUSH_RED_END,
    SYNC_END,
    SYNC_GREEN_MSG,
    SYNC_RED_END,
    _write)


class SyncInstallGateTest(GateFixture):
    """`sync-install.sh`'s slower cases; the refusals that keep the real install safe stay in the default run."""

    def test_green_suite_ships_and_says_so(self):
        result = self.sync("green")
        self.assertEqual(result.returncode, 0, self.both(result))
        self.assertIn(SYNC_GREEN_MSG, result.stdout)
        self.assertEqual(len(self.suite_calls()), 1,
                         "the suite ran %r times" % self.suite_calls())
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        self.assertEqual(lines[-1], SYNC_END,    # an exit status cannot tell a finish from a set -e death
                         "sync-install stopped early:\n%s" % result.stdout)
        for relative in (os.path.join("scripts", "python", "amaze", "widget.py"),
                         "OPmenu.xml",
                         os.path.join("toolbar", "Amaze.shelf")):    # the shelf carries the hotkey
            self.assertTrue(
                os.path.isfile(os.path.join(self.install, relative)),
                "%s did not land in the install" % relative)

    def test_a_scratch_destination_takes_a_dirty_tree(self):
        """A sabotage is a dirty tree, so it gets a different DESTINATION rather than an exemption."""
        _write(os.path.join(self.repo, "scripts", "python", "amaze",
                            "stray.py"), "# sabotaged, never committed\n")
        scratch = self._scratch()

        result = self.sync("green", AMAZE_SCRATCH_INSTALL=scratch)

        self.assertEqual(result.returncode, 0, self.both(result))
        self.assertTrue(
            os.path.exists(os.path.join(scratch, "scripts", "python",
                                        "amaze", "stray.py")),
            "the dirty tree did not reach the scratch install, so a "
            "sabotage would be judged on code that does not hold it")
        self.assertFalse(
            os.path.exists(os.path.join(self.install, "OPmenu.xml")),
            "the REAL install was written during a scratch sync - "
            "knowingly-broken code just reached the tree a live Houdini "
            "reads")

    def test_a_populated_directory_is_not_treated_as_scratch(self):
        """Without the marker, a scratch destination holding somebody's files would be mirrored over."""
        scratch = self._scratch()
        _write(os.path.join(scratch, "someones_work.txt"), "do not lose me\n")

        result = self.sync("green", AMAZE_SCRATCH_INSTALL=scratch)

        self.assertEqual(result.returncode, 1, self.both(result))
        self.assertIn("not empty", self.both(result))
        self.assertTrue(
            os.path.exists(os.path.join(scratch, "someones_work.txt")),
            "it refused and overwrote the directory anyway")

    def test_a_committed_change_ships_without_being_pushed(self):
        """COMMITTED, not PUSHED - the runner syncs before it tests, so requiring a push would make the suite unrunnable before pushing."""
        _write(os.path.join(self.repo, "scripts", "python", "amaze",
                            "widget.py"), "# edited\n")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "an unpushed commit")
        self.assertNotEqual(
            self.base_sha, self._git("rev-parse", "HEAD"),
            "the fixture did not actually commit anything")

        result = self.sync("green")

        self.assertEqual(result.returncode, 0, self.both(result))
        self.assertIn(SYNC_GREEN_MSG, result.stdout)

    def test_red_suite_refuses_and_names_the_failures(self):
        result = self.sync("red")
        self.assertEqual(result.returncode, 1, self.both(result))
        self.assertNotIn(SYNC_END, result.stdout)
        self.assertIn("SUITE FAILED", result.stderr)
        self.assertIn("FAIL: test_tile_is_composed", result.stderr)
        self.assertIn("ERROR: test_restore", result.stderr)
        self.assertReachedEnd(result, SYNC_RED_END)    # the rollback line prints last

    def test_a_suite_that_cannot_run_is_refused(self):
        """No FAIL line and no `Ran` line is not the same as nothing wrong - the state that shipped broken."""
        for mode, says in (("crash", "The suite did not run at all"),
                           ("no_tests", ""),    # `Ran 0 tests ... OK` verifies nothing
                           ("silent", ""),
                           ("leak", "")):    # a zero exit that wrote the real debug log
            with self.subTest(mode=mode):
                result = self.sync(mode)
                self.assertNotEqual(result.returncode, 0,
                                    "a %s suite was reported as a good "
                                    "ship:\n%s" % (mode, self.both(result)))
                self.assertNotIn(SYNC_END, result.stdout)
                self.assertIn(says, result.stderr)
                self.assertReachedEnd(result, SYNC_RED_END)

    def test_no_verify_skips_the_suite_entirely(self):
        """`run-tests.sh` sets this to break the recursion, or the suite runs twice per command."""
        result = self.sync("crash", AMAZE_SYNC_NO_VERIFY="1")
        self.assertEqual(result.returncode, 0, self.both(result))
        self.assertEqual(self.suite_calls(), [],
                         "the suite ran despite AMAZE_SYNC_NO_VERIFY")

    def test_it_wires_the_push_gate_in_a_fresh_clone(self):
        """A fresh clone has no hook until this wires it, and losing that silently re-opens the hole the push gate closes."""
        self.assertEqual(
            subprocess.run(("git", "-C", self.repo, "config", "--get",
                            "core.hooksPath"), capture_output=True, text=True,
                           env=self.git_env).returncode, 1,
            "the fixture already had a hooksPath")
        result = self.sync("green")
        self.assertIn("wired the pre-push gate", result.stdout)
        self.assertEqual(self._git("config", "--get", "core.hooksPath"),
                         "tools/git-hooks")
        self.assertNotIn("wired the pre-push gate", self.sync("green").stdout)


class PrePushGateTest(GateFixture):
    """`pre-push`'s slower cases; the process gate and the red-suite refusal stay in the default run."""

    def test_green_suite_allows_the_push_and_says_so(self):
        self._commit(os.path.join("scripts", "python", "amaze", "widget.py"))
        result = self.push("green")
        self.assertEqual(result.returncode, 0, self.both(result))
        self.assertIn("203 " + PUSH_GREEN_MSG, result.stdout)
        self.assertEqual(len(self.suite_calls()), 1,
                         "the suite ran %r times" % self.suite_calls())
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        self.assertEqual(lines[-1], PUSH_END,
                         "pre-push stopped early:\n%s" % result.stdout)

    def test_a_suite_that_cannot_run_is_refused(self):
        self._commit(os.path.join("scripts", "python", "amaze", "widget.py"))
        for mode in ("crash", "no_tests", "silent", "leak"):    # dead, empty, mute, or a leak
            with self.subTest(mode=mode):
                result = self.push(mode)
                self.assertNotEqual(result.returncode, 0,
                                    "the push gate passed a %s suite:\n%s"
                                    % (mode, self.both(result)))
                self.assertNotIn(PUSH_END, result.stdout)
                self.assertIn("PUSH REFUSED", result.stderr)
                self.assertReachedEnd(result, PUSH_RED_END)

    def test_a_stale_escape_hatch_does_not_disable_the_gate(self):
        """Exported and forgotten - set, but to a sha that is no longer HEAD, so the suite still runs."""
        self._commit(os.path.join("scripts", "python", "amaze", "widget.py"))
        result = self.push("red", AMAZE_SKIP_TESTS=self.base_sha)
        self.assertEqual(result.returncode, 1, self.both(result))
        self.assertEqual(len(self.suite_calls()), 1,
                         "a stale AMAZE_SKIP_TESTS disabled the gate")


WIDGET = "scripts/python/amaze/widget.py"
BRANDING = "scripts/python/amaze/branding.py"
SIZE = "test_widget.W.test_size"


class PrePushSelectionTest(GateFixture):
    """A push runs the tests it reaches, or the whole suite when unsure. ▸p/suite-selects"""

    def _mapped(self):
        """A committed widget with two defs, and the map a green full run of it wrote."""
        _write(os.path.join(self.repo, *WIDGET.split("/")),
               "def size():\n    return 1\n\n\ndef label():\n    return 'a'\n")
        _write(os.path.join(self.repo, *BRANDING.split("/")), 'APP_VERSION = "1.0.0"\n')
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "widget")
        self.base_sha = self._git("rev-parse", "HEAD")
        recorder = impact_map.Recorder(self.repo)
        recorder.tests = [SIZE, "test_widget.W.test_label", "test_other.O.test_x"]
        recorder.ran = {SIZE: {WIDGET: {"size"}}, "test_widget.W.test_label": {WIDGET: {"label"}}}
        files = impact_map.snapshot(self.repo, impact_map.repository_files(self.repo))
        with open(os.path.join(self.repo, ".git", "amaze-test-impact.json"), "w",
                  encoding="utf-8") as handle:
            json.dump(recorder.build(files, 3), handle)

    def _change(self, old, new, path=WIDGET):
        full = os.path.join(self.repo, *path.split("/"))
        with open(full, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn(old, text)
        _write(full, text.replace(old, new, 1))
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "change " + path)

    def assertWhole(self, result, why):
        self.assertIn("running the suite (%s)" % why, result.stdout, self.both(result))
        self.assertEqual(["green"], [call.strip() for call in self.suite_calls()],
                         "the whole suite was not what ran")

    def _houdinis(self, *names):
        """Fake installs in the copied houdini-env.sh, committed by `_mapped`: never this machine's."""
        roots = [os.path.join(self.tmp, name) for name in names]
        with open(os.path.join(self.repo, "tools", "houdini-env.sh"), "a",
                  encoding="utf-8") as handle:
            handle.write("amaze_houdini_roots() { printf '%%s\\n' %s; }\n"
                         % " ".join("'%s'" % root for root in roots))
        return roots

    def test_a_push_runs_only_the_tests_its_change_reaches(self):
        self._mapped()
        self._change("return 1", "return 2")
        result = self.push("green")
        self.assertEqual(result.returncode, 0, self.both(result))
        self.assertIn("running the tests this push reaches", result.stdout)
        self.assertEqual(["green " + SIZE], self.suite_calls())
        self.assertFalse(os.path.exists(os.path.join(self.install, *WIDGET.split("/"))),
                         "a run of some tests updated the live install")
        self.assertIn(PUSH_END, result.stdout)

    def test_a_red_selection_refuses_the_push(self):
        self._mapped()
        self._change("return 1", "return 2")
        result = self.push("red")
        self.assertEqual(result.returncode, 1, self.both(result))
        self.assertIn("PUSH REFUSED", result.stderr)
        self.assertEqual(["red " + SIZE], self.suite_calls())

    def test_a_push_that_reaches_no_test_runs_none(self):
        self._mapped()
        self._commit(os.path.join("docs", "a.md"))
        result = self.push("green")
        self.assertEqual(result.returncode, 0, self.both(result))
        self.assertIn("reaches no test", result.stdout)
        self.assertEqual([], self.suite_calls())
        self.assertIn(PUSH_END, result.stdout)

    def test_a_new_minor_version_runs_the_whole_suite_on_one_houdini(self):
        """An older major installed beside it is not run: only the newest is tested."""
        self._houdinis("Houdini21", "Houdini22")
        self._mapped()
        self._change('"1.0.0"', '"1.1.0"', BRANDING)
        self.assertWhole(self.push("green"), "a new minor or major version")

    def test_a_new_major_version_runs_the_whole_suite_on_one_houdini(self):
        self._houdinis("Houdini21", "Houdini22")
        self._mapped()
        self._change('"1.0.0"', '"2.0.0"', BRANDING)
        self.assertWhole(self.push("green"), "a new minor or major version")

    def test_a_run_by_hand_on_every_houdini_refuses_a_test_skipped_on_all(self):
        """The push no longer runs every Houdini; `run-tests.sh --all-versions` keeps the check."""
        self._houdinis("Houdini21", "Houdini22")
        self._mapped()
        script = os.path.join(self.repo, "tools", "run-tests.sh")
        result = subprocess.run(
            ["bash", script, "--all-versions"], capture_output=True, text=True, cwd=self.tmp,
            env=self._env("green", FAKE_SKIPPED='[["%s", "needs a GPU"]]' % SIZE))
        self.assertNotEqual(result.returncode, 0, self.both(result))
        self.assertIn("DEAD COVER", result.stdout + result.stderr)

    def test_a_whole_run_for_any_other_reason_tests_one_houdini(self):
        self._houdinis("Houdini21", "Houdini22")
        self._mapped()
        self._commit(os.path.join("scripts", "python", "amaze", "fresh.py"))
        self.assertWhole(self.push("green"), "the map cannot answer")

    def test_a_patch_runs_only_what_it_reaches(self):
        self._mapped()
        self._change('"1.0.0"', '"1.0.1"', BRANDING)
        result = self.push("green")
        self.assertEqual(result.returncode, 0, self.both(result))
        self.assertNotIn("running the suite", result.stdout)
        self.assertIn(PUSH_END, result.stdout)

    def test_a_change_the_map_cannot_answer_runs_the_whole_suite(self):
        self._mapped()
        self._commit(os.path.join("scripts", "python", "amaze", "fresh.py"))
        self.assertWhole(self.push("green"), "the map cannot answer")

    def test_no_map_runs_the_whole_suite(self):
        self._commit(os.path.join("scripts", "python", "amaze", "widget.py"))
        self.assertWhole(self.push("green"), "the map cannot answer")

    def test_uncommitted_files_run_the_whole_suite(self):
        self._mapped()
        self._change("return 1", "return 2")
        _write(os.path.join(self.repo, "docs", "draft.md"), "draft\n")
        self.assertWhole(self.push("green"), "uncommitted files")

    def test_a_ref_that_is_not_head_runs_the_whole_suite(self):
        self._mapped()
        self._change("return 1", "return 2")
        self.assertWhole(self.push("green", stdin=self.ref_line(self.base_sha)),
                         "a pushed ref is not the checked-out commit")

    def test_a_new_branch_runs_the_whole_suite(self):
        self._mapped()
        self._change("return 1", "return 2")
        stdin = self.ref_line(self._git("rev-parse", "HEAD"), remote_sha="0" * 40)
        self.assertWhole(self.push("green", stdin=stdin), "a new branch")

    def test_no_refs_run_the_whole_suite(self):
        self._mapped()
        self._change("return 1", "return 2")
        self.assertWhole(self.push("green", stdin=""), "no refs on stdin")

    def test_a_selector_that_fails_runs_the_whole_suite(self):
        self._mapped()
        self._git("rm", "-q", os.path.join("tools", "select-tests.py"))
        self._git("commit", "-q", "-m", "no selector")
        self.assertWhole(self.push("green"), "the selection failed")


class RunTestsWrapperTest(GateFixture):

    def test_it_syncs_then_runs_the_suite_exactly_once(self):
        """Without `AMAZE_SYNC_NO_VERIFY` the suite runs twice on every push, which is how a gate earns being bypassed."""
        result = self._run(os.path.join("tools", "run-tests.sh"), "green",
                           cwd=self.tmp)
        self.assertEqual(result.returncode, 0, self.both(result))
        self.assertEqual(len(self.suite_calls()), 1,
                         "the suite ran %r times" % self.suite_calls())
        self.assertTrue(os.path.isfile(os.path.join(
            self.install, "scripts", "python", "amaze", "widget.py")),
            "run-tests.sh did not sync before testing")

    def test_it_passes_its_arguments_through(self):
        script = os.path.join(self.repo, "tools", "run-tests.sh")
        result = subprocess.run(["bash", script, "--isolated"],
                                capture_output=True, text=True, cwd=self.tmp,
                                env=self._env("green"))
        self.assertEqual(result.returncode, 0, self.both(result))
        self.assertEqual(self.suite_calls(), ["green --isolated"])

    def test_a_red_suite_propagates(self):
        result = self._run(os.path.join("tools", "run-tests.sh"), "red",
                           cwd=self.tmp)
        self.assertNotEqual(result.returncode, 0, self.both(result))


if __name__ == "__main__":
    unittest.main()
