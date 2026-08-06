"""The shell gates, tested like code - because they are code.

Four shell files decide whether a build reaches the live install and
whether a commit reaches the remote. They had zero tests while the
Python had 203, and it showed: in ONE hour, three separate gates were
written that LOOKED like they worked. All three were the same bug -
a command that returns non-zero on a perfectly ordinary outcome,
under `set -e`:

    out="$(failing_cmd)"          # aborts before its own error handling
    [ "$x" -eq 0 ] && echo ...    # returns 1 when the test is false
    n="$(... | grep -c PAT)"      # grep -c EXITS 1 when the count is 0

shellcheck catches NONE of the three (measured). Two of them abort
SILENTLY: the script stops mid-way and the exit status looks plausible,
so a green run and a dead run are indistinguishable from the outside.

So these tests never ask "did it exit 0". They ask three things:
  1. the right STATUS, and
  2. the right WORDS (a gate that refuses silently is a gate nobody
     obeys), and
  3. a TERMINAL MARKER - the last thing the script prints on that path.
     A marker is what turns "aborted at line 93" from invisible into a
     failing test, whatever the cause.

The state that shipped broken is covered explicitly: a suite that
cannot run at all must make the gate REFUSE, not report success.

SAFETY - these run in the suite, repeatedly, on a developer machine
that has the real install and the real library on it:
  * Everything happens in a tmpdir. A fake repo, a fake install, a
    fake $HFS, a private git repo with a private "remote" ref.
  * $AMAZE is ALWAYS set to the fixture install. It is never left
    empty: with it empty, sync-install.sh reads the real Houdini
    package file and would rsync this fixture over the REAL install.
    That one path is deliberately untested. Do not "improve" it.
  * The suite itself is a STUB (see _STUB below) that prints a green,
    red, or dead run on demand. The real 15s suite never runs, the
    real library is never opened, nothing is ever pushed - the git
    fixture gets its upstream from `git update-ref`, so no `git push`
    is executed anywhere in this file.
  * The gate scripts are COPIED FROM THE REAL FILES at setUp, so this
    tests the real logic; a hash test asserts the copy is byte-for-byte
    identical, so the fixture cannot quietly drift into a museum piece.
"""

import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.tests import test_support  # noqa: E402,F401 - redirects the log

# tests/ -> amaze/ -> python/ -> scripts/ -> repo root: FIVE levels.
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

#: The real files under test. Relative path in the fixture -> real path.
#:
#: houdini-env.sh is not itself a gate, but all three gates SOURCE it,
#: so a fixture without it is a fixture where every script dies on line
#: one - which is how it was noticed: 29 of these tests went red at once
#: with `No such file or directory`, the silent `set -e` abort they are
#: built to catch, caught on themselves.
GATE_SCRIPTS = {
    os.path.join("tools", "houdini-env.sh"):
        os.path.join(REPO, "tools", "houdini-env.sh"),
    os.path.join("tools", "sync-install.sh"):
        os.path.join(REPO, "tools", "sync-install.sh"),
    os.path.join("tools", "run-tests.sh"):
        os.path.join(REPO, "tools", "run-tests.sh"),
    os.path.join("tools", "git-hooks", "pre-push"):
        os.path.join(REPO, "tools", "git-hooks", "pre-push"),
}

#: Not copied - replaced by the stub. Named here so a rename breaks a
#: test instead of silently leaving the stub un-substituted.
REAL_RUNNER = os.path.join(
    REPO, "scripts", "python", "amaze", "tests", "start_test.sh")
REAL_LEAK_CHECK = os.path.join(
    REPO, "scripts", "python", "amaze", "tests", "check_log_leak.py")

#: Where the stub lives inside the fixture - the path BOTH gates reach
#: (sync-install.sh calls it directly, pre-push reaches it through
#: run-tests.sh), so one stub drives every test in this file.
RUNNER_REL = os.path.join("scripts", "python", "amaze", "tests",
                          "start_test.sh")

#: Terminal markers: the LAST thing each script prints on each path.
#: If one of these is missing the script did not reach its end - which
#: is precisely what a `set -e` abort looks like from outside. Both
#: scripts now carry an explicit "DONE" line for the success path; the
#: refusal paths `exit 1` before it, so their marker is the last line
#: of the refusal message.
SYNC_GREEN_MSG = "sync-install: suite green - the install is safe to open."
SYNC_END = "sync-install: DONE"
SYNC_RED_END = "git stash && tools/sync-install.sh"
PUSH_GREEN_MSG = "tests OK, real debug log clean."
PUSH_END = "pre-push: DONE"
PUSH_RED_END = "Fix, or push --no-verify."


#: Stands in for start_test.sh. Reproduces the OUTPUT CONTRACT the gates
#: parse - unittest's "Ran N tests" / "FAILED" lines and check_log_leak's
#: "LOG LEAK" - without hython, a licence, or 15 seconds.
#: (test_the_stub_still_matches_the_real_runner keeps this honest.)
_STUB = r"""#!/bin/bash
# STUB. Not the real runner - see test_shell_gates.py.
mode="${FAKE_SUITE_MODE:-green}"
echo "$mode $*" >> "$FAKE_SUITE_CALLS"

case "$mode" in
green)
    echo "......................................................."
    echo "----------------------------------------------------------------------"
    echo "Ran 203 tests in 15.204s"
    echo
    echo "OK"
    echo "---------------------------"
    echo "debug log clean"
    exit 0
    ;;
red)
    echo "======================================================================"
    echo "FAIL: test_tile_is_composed (test_tile_icons.GeometryTest)"
    echo "----------------------------------------------------------------------"
    echo "AssertionError: (151, 126) != (0, 0)"
    echo "======================================================================"
    echo "ERROR: test_restore (test_restore_drill.TestRestoreDrill)"
    echo "----------------------------------------------------------------------"
    echo "RuntimeError: boom"
    echo "----------------------------------------------------------------------"
    echo "Ran 203 tests in 15.412s"
    echo
    echo "FAILED (failures=1, errors=1)"
    exit 1
    ;;
crash)
    # The suite could not run AT ALL: no licence, no hython, an import
    # error in a module, a segfault. No FAIL line, no "Ran" line - the
    # shape that reads as "nothing wrong here" to a careless gate.
    echo "hython: unable to obtain a licence" >&2
    exit 1
    ;;
no_tests)
    # Ran, exited zero, verified NOTHING.
    echo "Ran 0 tests in 0.001s"
    echo
    echo "OK"
    exit 0
    ;;
silent)
    # Exit 0, not one byte of output.
    exit 0
    ;;
leak)
    # Everything green EXCEPT the real debug log got written to. The
    # gates check this separately; this mode proves that arm is alive.
    echo "Ran 203 tests in 15.204s"
    echo
    echo "OK"
    echo "LOG LEAK: a headless run wrote to your real debug log" >&2
    exit 0
    ;;
esac
echo "stub: unknown mode $mode" >&2
exit 99
"""


def _sha(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def _write(path, text, executable=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    if executable:
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP)


class GateFixture(unittest.TestCase):
    """A throwaway repo + install + git upstream, with the REAL gate
    scripts copied in and a stub suite."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="amaze_gates_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = os.path.join(self.tmp, "repo")
        self.install = os.path.join(self.tmp, "install")
        self.hfs = os.path.join(self.tmp, "fake_hfs")
        self.calls = os.path.join(self.tmp, "suite_calls.log")
        for path in (self.install, self.hfs,
                     os.path.join(self.repo, "python_panels"),
                     os.path.join(self.repo, "toolbar"),
                     os.path.join(self.repo, "docs")):
            os.makedirs(path)

        # The real logic, copied at test time - never a transcription.
        for relative, real in GATE_SCRIPTS.items():
            self.assertTrue(os.path.isfile(real),
                            "gate script has moved or been deleted: %s" % real)
            target = os.path.join(self.repo, relative)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(real, target)
            os.chmod(target, os.stat(target).st_mode | stat.S_IXUSR)

        _write(os.path.join(self.repo, RUNNER_REL), _STUB, executable=True)
        _write(os.path.join(self.repo, "OPmenu.xml"), "<menuDocument/>\n")
        _write(os.path.join(self.repo, "python_panels", "amaze.pypanel"),
               "<pythonPanelDocument/>\n")
        # The shelf is shipped like python_panels and OPmenu.xml. It is
        # NOT optional here: a sync that tolerates a missing toolbar/
        # would let the shelf exist only in the repo, which is the
        # under-sync failure this fixture exists to catch.
        _write(os.path.join(self.repo, "toolbar", "Amaze.shelf"),
               "<shelfDocument/>\n")
        _write(os.path.join(self.repo, "scripts", "python", "amaze",
                            "widget.py"), "VALUE = 1\n")

        self.git_env = dict(os.environ)
        self.git_env.update({
            "GIT_CONFIG_GLOBAL": os.path.join(self.tmp, "gitconfig"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "gate test",
            "GIT_AUTHOR_EMAIL": "gate@test.invalid",
            "GIT_COMMITTER_NAME": "gate test",
            "GIT_COMMITTER_EMAIL": "gate@test.invalid",
        })
        self.git_env.pop("GIT_DIR", None)
        self.git_env.pop("GIT_WORK_TREE", None)
        _write(os.path.join(self.tmp, "gitconfig"), "")
        self._make_git_repo()

    # -- fixture plumbing ----------------------------------------------

    def _git(self, *args):
        result = subprocess.run(("git", "-C", self.repo) + args,
                                capture_output=True, text=True,
                                env=self.git_env)
        self.assertEqual(result.returncode, 0,
                         "git %s failed:\n%s%s"
                         % (" ".join(args), result.stdout, result.stderr))
        return result.stdout.strip()

    def _make_git_repo(self):
        """A real repo with a real remote-tracking state - built with
        update-ref, so NOTHING is ever pushed, not even to a local bare
        repo. `nowhere.git` deliberately does not exist: a stray network
        or filesystem push would fail loudly rather than succeed."""
        self._git("init", "-q")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "base")
        self.branch = self._git("symbolic-ref", "--short", "HEAD")
        self.base_sha = self._git("rev-parse", "HEAD")
        self._git("remote", "add", "origin",
                  os.path.join(self.tmp, "nowhere.git"))
        self._git("update-ref", "refs/remotes/origin/%s" % self.branch, "HEAD")
        self._git("symbolic-ref", "refs/remotes/origin/HEAD",
                  "refs/remotes/origin/%s" % self.branch)
        self._git("branch", "--set-upstream-to=origin/%s" % self.branch,
                  self.branch)

    def _commit(self, *relative_paths):
        """Unpushed commits touching exactly these paths, so the range
        the hook computes is what the test says it is."""
        for relative in relative_paths:
            _write(os.path.join(self.repo, relative), "touched\n")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "change " + " ".join(relative_paths))
        # git reports paths with FORWARD slashes on every platform,
        # including Windows; the callers build theirs with os.path.join,
        # which uses the native separator. Comparing the two directly
        # made all seventeen pre-push tests fail in setup on Windows -
        # every one of them reporting the gate as broken when it was the
        # comparison that was.
        self.assertEqual(
            sorted(self._git("diff", "--name-only",
                             "%s..HEAD" % self.base_sha).splitlines()),
            sorted(p.replace(os.sep, "/") for p in relative_paths),
            "the fixture range is not what we set up")
        return self._git("rev-parse", "HEAD")

    def _env(self, mode, **extra):
        env = dict(os.environ)
        # Never inherit a real one of these from the calling suite.
        for name in ("AMAZE_SYNC_NO_VERIFY", "AMAZE_SKIP_TESTS"):
            env.pop(name, None)
        env.update(self.git_env)
        env.update({
            "AMAZE": self.install,       # NEVER empty - see module docstring
            "HFS": self.hfs,             # exists, so the "no Houdini" arm
                                         # is not taken on any machine
            "FAKE_SUITE_MODE": mode,
            "FAKE_SUITE_CALLS": self.calls,
        })
        env.update(extra)
        return env

    def _run(self, script_relative, mode="green", cwd=None, stdin="",
             **extra):
        script = os.path.join(self.repo, script_relative)
        self.assertNotIn(REPO, os.path.realpath(script),
                         "refusing to run the REAL gate script")
        return subprocess.run(["bash", script], capture_output=True,
                              text=True, cwd=cwd or self.tmp, input=stdin,
                              env=self._env(mode, **extra))

    def sync(self, mode="green", **extra):
        # Deliberately from an unrelated cwd: sync-install.sh claims to
        # be runnable from anywhere, and a wrong cwd is how it used to
        # half-copy.
        return self._run(os.path.join("tools", "sync-install.sh"),
                         mode, cwd=self.tmp, **extra)

    def ref_line(self, local_sha, local_ref=None, remote_ref=None,
                 remote_sha=None):
        """One line in git's own pre-push stdin format:
        <local ref> <local sha> <remote ref> <remote sha>.

        The hook derives what to gate from THIS, not from HEAD - the
        difference is a total bypass (`git push origin other:main`), so
        every push test must speak the real protocol."""
        branch_ref = "refs/heads/%s" % self.branch
        return "%s %s %s %s\n" % (local_ref or branch_ref, local_sha,
                                  remote_ref or branch_ref,
                                  self.base_sha if remote_sha is None
                                  else remote_sha)

    def push(self, mode="green", stdin=None, **extra):
        # A git hook runs with cwd = the repo root, and with git's ref
        # lines on stdin. Default: this branch, HEAD over the base.
        if stdin is None:
            stdin = self.ref_line(self._git("rev-parse", "HEAD"))
        return self._run(os.path.join("tools", "git-hooks", "pre-push"),
                         mode, cwd=self.repo, stdin=stdin, **extra)

    def suite_calls(self):
        if not os.path.exists(self.calls):
            return []
        with open(self.calls, encoding="utf-8") as handle:
            return [line for line in handle.read().splitlines() if line]

    def both(self, result):
        return result.stdout + result.stderr

    def assertReachedEnd(self, result, marker):
        self.assertIn(
            marker, self.both(result),
            "the script never reached its end - it aborted mid-way "
            "(the silent `set -e` failure).\nSTDOUT:\n%s\nSTDERR:\n%s"
            % (result.stdout, result.stderr))


# ----------------------------------------------------------------------
# The fixture must be testing the REAL scripts.
# ----------------------------------------------------------------------

class FixtureFidelityTest(GateFixture):

    def test_every_gate_script_exists_where_the_tests_expect_it(self):
        for real in list(GATE_SCRIPTS.values()) + [REAL_RUNNER,
                                                   REAL_LEAK_CHECK]:
            self.assertTrue(os.path.isfile(real), real)
            self.assertGreater(os.path.getsize(real), 0, real)

    def test_the_fixture_holds_the_real_scripts_byte_for_byte(self):
        """Copied at setUp, hashed here. If this ever fails, the copy
        step broke - and every other test in this file went from
        testing the gates to testing a fossil."""
        for relative, real in GATE_SCRIPTS.items():
            self.assertEqual(_sha(os.path.join(self.repo, relative)),
                             _sha(real),
                             "fixture copy of %s has drifted" % relative)

    def test_the_stub_still_matches_the_real_runner(self):
        """The stub fakes start_test.sh's OUTPUT. If the real runner
        stops producing that output the stub is a lie, and every green
        assertion below becomes meaningless."""
        with open(REAL_RUNNER, encoding="utf-8") as handle:
            runner = handle.read()
        self.assertIn("hython -m unittest", runner,
                      "the real runner no longer produces unittest's "
                      "'Ran N tests' / 'FAILED' lines - restub")
        self.assertIn("check_log_leak.py", runner,
                      "the real runner no longer runs the leak check")
        with open(REAL_LEAK_CHECK, encoding="utf-8") as handle:
            self.assertIn("LOG LEAK", handle.read(),
                          "the leak check no longer prints 'LOG LEAK' - "
                          "both gates grep for that literal")

    def test_the_fixture_never_points_at_the_real_install(self):
        env = self._env("green")
        self.assertEqual(env["AMAZE"], self.install)
        self.assertTrue(env["AMAZE"].startswith(tempfile.gettempdir())
                        or "/var/folders/" in env["AMAZE"]
                        or env["AMAZE"].startswith("/private/"),
                        "the fixture install is not in a tmpdir: %s"
                        % env["AMAZE"])
        self.assertNotIn("Cloud", env["AMAZE"])


# ----------------------------------------------------------------------
# THE DEPLOYMENT GATE
# ----------------------------------------------------------------------

class SyncInstallGateTest(GateFixture):

    def test_green_suite_ships_and_says_so(self):
        result = self.sync("green")
        self.assertEqual(result.returncode, 0, self.both(result))
        self.assertIn(SYNC_GREEN_MSG, result.stdout)
        self.assertEqual(len(self.suite_calls()), 1,
                         "the suite ran %r times" % self.suite_calls())

    def test_green_run_reaches_its_end(self):
        """The DONE marker must be the LAST line. Bug form 3 lives at
        the `grep -c` lines: on a green suite the count is zero, grep
        exits 1, and under `set -e` the script dies right after printing
        'verifying...' - having shipped, and having said nothing. Exit
        status alone cannot tell that apart from a clean finish."""
        result = self.sync("green")
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        self.assertTrue(lines, "sync-install printed nothing at all")
        self.assertEqual(lines[-1], SYNC_END,
                         "sync-install stopped early:\n%s" % result.stdout)

    def test_green_run_actually_synced_the_files(self):
        self.sync("green")
        self.assertTrue(os.path.isfile(os.path.join(
            self.install, "scripts", "python", "amaze", "widget.py")))
        self.assertTrue(os.path.isfile(os.path.join(
            self.install, "OPmenu.xml")))
        # The shelf is how a hotkey reaches Amaze at all. Shipped but
        # unsynced, it would exist only in the repo and the tools would
        # never appear in Houdini.
        self.assertTrue(
            os.path.isfile(os.path.join(
                self.install, "toolbar", "Amaze.shelf")),
            "the shelf did not land in the install")

    def test_red_suite_refuses_and_names_the_failures(self):
        result = self.sync("red")
        self.assertEqual(result.returncode, 1, self.both(result))
        self.assertNotIn(SYNC_END, result.stdout)
        self.assertIn("SUITE FAILED", result.stderr)
        self.assertIn("FAIL: test_tile_is_composed", result.stderr)
        self.assertIn("ERROR: test_restore", result.stderr)

    def test_red_run_reaches_its_end(self):
        """Refusing is half the job; the rollback command is the other
        half. It is the last thing printed, so it doubles as the marker
        proving the red path ran to completion."""
        result = self.sync("red")
        self.assertReachedEnd(result, SYNC_RED_END)

    def test_a_suite_that_cannot_run_is_refused(self):
        """THE STATE THAT SHIPPED BROKEN. No FAIL line and no 'Ran'
        line is not the same as 'nothing wrong'."""
        result = self.sync("crash")
        self.assertNotEqual(result.returncode, 0,
                            "a dead suite was reported as a good ship:\n%s"
                            % self.both(result))
        self.assertNotIn(SYNC_END, result.stdout)

    def test_a_suite_that_cannot_run_says_why(self):
        """Refusing without saying why sends the developer hunting. The
        script has the words for it ('The suite did not run at all') -
        it must actually reach them."""
        result = self.sync("crash")
        self.assertIn("The suite did not run at all", result.stderr,
                      "STDOUT:\n%s\nSTDERR:\n%s"
                      % (result.stdout, result.stderr))
        self.assertReachedEnd(result, SYNC_RED_END)

    def test_a_suite_that_ran_zero_tests_is_refused(self):
        """'Ran 0 tests ... OK' exits 0 with no failures. It verified
        nothing. Shipping on it is shipping unverified."""
        result = self.sync("no_tests")
        self.assertNotEqual(result.returncode, 0,
                            "shipped on a suite that ran ZERO tests:\n%s"
                            % self.both(result))
        self.assertNotIn(SYNC_END, result.stdout)

    def test_a_silent_suite_is_refused(self):
        result = self.sync("silent")
        self.assertNotEqual(result.returncode, 0, self.both(result))
        self.assertNotIn(SYNC_END, result.stdout)

    def test_a_log_leak_alone_is_refused(self):
        """Green tests, zero exit - but the run wrote to the user's real
        debug log. That arm of the condition must not be dead code."""
        result = self.sync("leak")
        self.assertNotEqual(result.returncode, 0, self.both(result))
        self.assertNotIn(SYNC_END, result.stdout)

    def test_no_verify_skips_the_suite_entirely(self):
        """run-tests.sh sets this to break the recursion. If it stopped
        working the suite would run twice per test command."""
        result = self.sync("crash", AMAZE_SYNC_NO_VERIFY="1")
        self.assertEqual(result.returncode, 0, self.both(result))
        self.assertEqual(self.suite_calls(), [],
                         "the suite ran despite AMAZE_SYNC_NO_VERIFY")

    def test_a_missing_install_is_refused_before_anything_is_copied(self):
        """$AMAZE pointing nowhere must stop the script at the guard.
        (The $AMAZE-EMPTY path is deliberately never exercised: it falls
        back to the Houdini package file, which on a real machine names
        the REAL install.)"""
        missing = os.path.join(self.tmp, "not_an_install")
        result = self.sync("green", AMAZE=missing)
        self.assertEqual(result.returncode, 1, self.both(result))
        self.assertIn("cannot find the install", result.stderr)
        self.assertFalse(os.path.exists(missing))
        self.assertEqual(self.suite_calls(), [])

    def test_it_wires_the_push_gate_in_a_fresh_clone(self):
        """A fresh clone has no hook until someone runs one command, so
        the sync path wires it. Silently losing this re-opens the hole
        the pre-push hook exists to close."""
        self.assertEqual(
            subprocess.run(("git", "-C", self.repo, "config", "--get",
                            "core.hooksPath"), capture_output=True, text=True,
                           env=self.git_env).returncode, 1,
            "the fixture already had a hooksPath")
        result = self.sync("green")
        self.assertIn("wired the pre-push gate", result.stdout)
        self.assertEqual(self._git("config", "--get", "core.hooksPath"),
                         "tools/git-hooks")
        # ...and does not say it twice.
        self.assertNotIn("wired the pre-push gate", self.sync("green").stdout)


# ----------------------------------------------------------------------
# THE PUSH GATE
# ----------------------------------------------------------------------

class PrePushGateTest(GateFixture):

    def test_green_suite_allows_the_push_and_says_so(self):
        self._commit(os.path.join("scripts", "python", "amaze", "widget.py"))
        result = self.push("green")
        self.assertEqual(result.returncode, 0, self.both(result))
        self.assertIn("203 " + PUSH_GREEN_MSG, result.stdout)
        self.assertEqual(len(self.suite_calls()), 1,
                         "the suite ran %r times" % self.suite_calls())

    def test_green_run_reaches_its_end(self):
        self._commit(os.path.join("scripts", "python", "amaze", "widget.py"))
        result = self.push("green")
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        self.assertTrue(lines, "pre-push printed nothing at all")
        self.assertEqual(lines[-1], PUSH_END,
                         "pre-push stopped early:\n%s" % result.stdout)

    def test_red_suite_refuses_and_names_the_failures(self):
        self._commit(os.path.join("scripts", "python", "amaze", "widget.py"))
        result = self.push("red")
        self.assertEqual(result.returncode, 1, self.both(result))
        self.assertIn("PUSH REFUSED", result.stderr)
        self.assertIn("FAIL: test_tile_is_composed", result.stderr)
        self.assertNotIn(PUSH_END, result.stdout)

    def test_red_run_reaches_its_end(self):
        self._commit(os.path.join("scripts", "python", "amaze", "widget.py"))
        result = self.push("red")
        self.assertReachedEnd(result, PUSH_RED_END)

    def test_a_suite_that_cannot_run_is_refused(self):
        """THE STATE THAT SHIPPED BROKEN, push side."""
        self._commit(os.path.join("scripts", "python", "amaze", "widget.py"))
        result = self.push("crash")
        self.assertNotEqual(result.returncode, 0,
                            "a dead suite was reported as a green push:\n%s"
                            % self.both(result))
        self.assertNotIn(PUSH_END, result.stdout)
        self.assertReachedEnd(result, PUSH_RED_END)

    def test_a_suite_that_ran_zero_tests_is_refused(self):
        """'Ran 0 tests ... OK': exit 0, no failures, nothing verified.
        A gate that passes this is not a gate."""
        self._commit(os.path.join("scripts", "python", "amaze", "widget.py"))
        result = self.push("no_tests")
        self.assertNotEqual(result.returncode, 0,
                            "the push gate passed a suite that ran ZERO "
                            "tests:\n%s" % self.both(result))
        self.assertNotIn(PUSH_END, result.stdout)

    def test_a_silent_suite_is_refused(self):
        self._commit(os.path.join("scripts", "python", "amaze", "widget.py"))
        result = self.push("silent")
        self.assertNotEqual(result.returncode, 0,
                            "the push gate passed a suite that printed "
                            "nothing:\n%s" % self.both(result))

    def test_a_log_leak_alone_is_refused(self):
        self._commit(os.path.join("scripts", "python", "amaze", "widget.py"))
        result = self.push("leak")
        self.assertNotEqual(result.returncode, 0, self.both(result))
        self.assertIn("PUSH REFUSED", result.stderr)

    # -- what is worth 15 seconds and what is not -----------------------


    def test_a_docs_only_push_still_runs_the_suite(self):
        """The docs-only skip was DELETED (2026-07-28): ~40 lines that
        existed to save 20 seconds produced five of the eight gate bugs
        of 2026-07-27, including two total bypasses. The suite runs on
        EVERY push now - this pins the deletion so the skip logic does
        not quietly come back."""
        self._commit(os.path.join("docs", "a.md"))
        result = self.push("green")
        self.assertIn("running the suite", self.both(result))
        self.assertEqual(len(self.suite_calls()), 1)
        self.assertEqual(result.returncode, 0, self.both(result))
        self.assertIn("pre-push: DONE", result.stdout)


    def test_a_push_touching_a_shell_script_does_not_skip(self):
        """The allowlist version of this test missed .sh - so a push
        that changed the TEST RUNNER ITSELF skipped the gate."""
        self._commit(os.path.join("tools", "new-helper.sh"))
        result = self.push("red")
        self.assertNotIn("suite skipped", result.stdout)
        self.assertEqual(len(self.suite_calls()), 1)
        self.assertEqual(result.returncode, 1, self.both(result))

    def test_a_push_touching_an_svg_does_not_skip(self):
        """...and missed .svg, the artwork the delegate loads."""
        self._commit(os.path.join("scripts", "python", "amaze", "assets",
                                  "icon.svg"))
        result = self.push("red")
        self.assertNotIn("suite skipped", result.stdout)
        self.assertEqual(len(self.suite_calls()), 1)
        self.assertEqual(result.returncode, 1, self.both(result))

    def test_docs_mixed_with_code_does_not_skip(self):
        self._commit(os.path.join("docs", "notes.md"),
                     os.path.join("scripts", "python", "amaze", "widget.py"))
        result = self.push("red")
        self.assertNotIn("suite skipped", result.stdout)
        self.assertEqual(result.returncode, 1, self.both(result))

    # -- it must gate WHAT IS BEING PUSHED, not what HEAD happens to be --

    def test_pushing_another_branch_is_gated_on_that_branch(self):
        """`git push origin feature:main` is a total bypass if the hook
        reads HEAD: the current branch can be docs-only while the ref
        being pushed carries code. No --no-verify needed."""
        self._commit(os.path.join("docs", "notes.md"))   # HEAD: docs only
        self._git("checkout", "-q", "-b", "feature", self.base_sha)
        code = self._commit(os.path.join("scripts", "python", "amaze",
                                         "widget.py"))
        self._git("checkout", "-q", self.branch)
        result = self.push("red", stdin=self.ref_line(
            code, local_ref="refs/heads/feature",
            remote_ref="refs/heads/%s" % self.branch))
        self.assertNotIn("suite skipped", result.stdout,
                         "a code push was skipped because HEAD was docs")
        self.assertEqual(result.returncode, 1, self.both(result))
        self.assertEqual(len(self.suite_calls()), 1)

    def test_every_ref_of_a_multi_ref_push_is_gated(self):
        """`git push --all` feeds several lines. One docs-only ref must
        not excuse a second ref that carries code."""
        docs = self._commit(os.path.join("docs", "notes.md"))
        self._git("checkout", "-q", "-b", "feature", self.base_sha)
        code = self._commit(os.path.join("scripts", "python", "amaze",
                                         "widget.py"))
        self._git("checkout", "-q", self.branch)
        result = self.push("red", stdin=(
            self.ref_line(docs)
            + self.ref_line(code, local_ref="refs/heads/feature",
                            remote_ref="refs/heads/feature")))
        self.assertNotIn("suite skipped", result.stdout)
        self.assertEqual(result.returncode, 1, self.both(result))

    def test_a_new_remote_branch_is_gated_against_the_remote(self):
        """An all-zero REMOTE sha means the branch does not exist there
        yet. There is still a diff worth gating - and if none can be
        found the hook must run the suite, not skip."""
        code = self._commit(os.path.join("scripts", "python", "amaze",
                                         "widget.py"))
        result = self.push("red", stdin=self.ref_line(
            code, local_ref="refs/heads/brand-new",
            remote_ref="refs/heads/brand-new", remote_sha="0" * 40))
        self.assertNotIn("suite skipped", result.stdout)
        self.assertEqual(result.returncode, 1, self.both(result))


    def test_no_refs_on_stdin_runs_the_suite(self):
        """Missing information must never be read as 'nothing to do'.
        This is also how the hook behaves when invoked by hand."""
        result = self.push("red", stdin="")
        self.assertNotIn("suite skipped", result.stdout)
        self.assertEqual(result.returncode, 1, self.both(result))
        self.assertEqual(len(self.suite_calls()), 1)

    def test_an_unreadable_range_runs_the_suite(self):
        """A sha the repo does not have cannot be diffed - and a FAILED
        diff must not be read as an EMPTY one.

        `git diff --name-only <unknown>..<sha> || true` yields nothing,
        exactly like a ref that really has no changes. If both land in
        the same "nothing to test" branch, a real code push skips the
        gate whenever the remote sha is not present locally (a force-
        push, a pruned commit, a shallow clone). Same shape as the three
        bugs this file exists for: an ordinary failure swallowed into a
        value that looks like success."""
        result = self.push("red", stdin=self.ref_line(
            "b" * 40, remote_sha="c" * 40))
        self.assertNotIn("nothing to test", result.stdout,
                         "an undiffable range was reported as 'nothing to "
                         "test' - the suite was skipped for a code push")
        self.assertEqual(result.returncode, 1, self.both(result))

    def test_a_branch_deletion_is_not_reported_as_docs_only(self):
        """An all-zero LOCAL sha is a deletion - there is nothing to
        test. Whatever it does, it must not claim the code was vetted."""
        result = self.push("red", stdin=self.ref_line(
            "0" * 40, local_ref="refs/heads/dead"))
        self.assertNotIn("docs only", result.stdout)

    # -- the escape hatch --------------------------------------------------

    def test_the_escape_hatch_needs_the_sha_being_pushed(self):
        """Deliberately not a boolean: a boolean gets exported once in a
        shell profile and disables the gate forever."""
        self._commit(os.path.join("scripts", "python", "amaze", "widget.py"))
        head = self._git("rev-parse", "HEAD")
        result = self.push("crash", AMAZE_SKIP_TESTS=head)
        self.assertEqual(result.returncode, 0, self.both(result))
        self.assertIn("AMAZE_SKIP_TESTS", result.stderr)
        self.assertEqual(self.suite_calls(), [])

    def test_a_stale_escape_hatch_does_not_disable_the_gate(self):
        """The exported-and-forgotten case: the variable is set, but to
        a sha that is no longer HEAD. The suite must still run."""
        self._commit(os.path.join("scripts", "python", "amaze", "widget.py"))
        result = self.push("red", AMAZE_SKIP_TESTS=self.base_sha)
        self.assertEqual(result.returncode, 1, self.both(result))
        self.assertEqual(len(self.suite_calls()), 1,
                         "a stale AMAZE_SKIP_TESTS disabled the gate")


# ----------------------------------------------------------------------
# The thin wrapper the push gate goes through
# ----------------------------------------------------------------------

class RunTestsWrapperTest(GateFixture):

    def test_it_syncs_then_runs_the_suite_exactly_once(self):
        """It syncs with AMAZE_SYNC_NO_VERIFY, then runs the suite
        itself. If that flag stopped being passed the suite would run
        twice - ~30s on every push, which is how gates get bypassed."""
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


class TargetedRunTest(unittest.TestCase):
    """`start_test.sh <module>` runs THAT module (2026-08-05).

    It used to ignore the argument and run all 55, which reads as a
    targeted run that passed - two wasted full runs before anyone read
    the script. The fix had to be the front door rather than a refusal:
    a refusal sends you to a bare `hython -m unittest`, which skips the
    sync, the isolated AMAZE_LOG_DIR, the shell lint and the log-leak
    check - every guard, to save two minutes.

    Driven against the SOURCE and the argument-checking prologue only.
    The prologue exits before Houdini is looked for, deliberately, so
    the bad-name cases below cost no interpreter start - which is also
    what makes them affordable to assert here at all.
    """

    def _script(self):
        return os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "start_test.sh")

    def _run(self, *args):
        """BOUNDED, and the bound is load-bearing.

        If the argument check ever regresses, these arguments fall
        through to the full MODULES list and this call starts the whole
        suite - from inside the suite, recursively. Measured while
        sabotage-testing this very guard: the run had to be killed at
        seven minutes. A refused argument returns in milliseconds, so
        any wait at all is the regression.
        """
        try:
            return subprocess.run(["bash", self._script(), *args],
                                  capture_output=True, text=True,
                                  timeout=60)
        except subprocess.TimeoutExpired:
            self.fail(
                "start_test.sh did not refuse %r within 60s - the "
                "argument check has regressed and this call was "
                "starting the whole suite recursively" % (args,))

    def test_a_name_that_is_not_a_module_is_refused(self):
        result = self._run("test_no_such_module_here")
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertIn("no such test module", result.stderr)

    def test_a_bad_name_AFTER_isolated_is_refused_too(self):
        """The first version of this guard only inspected `$1`, so
        `--isolated <junk>` sailed through with the junk dropped - the
        same silent-ignore bug one position over."""
        result = self._run("--isolated", "test_no_such_module_here")
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertIn("no such test module", result.stderr)

    def test_the_refusal_costs_no_interpreter_start(self):
        """The argument check must sit ABOVE the Houdini lookup, or a
        typo costs a Houdini start to be told it was a typo."""
        with open(self._script(), encoding="utf-8") as handle:
            source = handle.read()
        check = source.find("no such test module")
        houdini = source.find("AMAZE_HOUDINI")
        self.assertGreater(check, -1, "the argument check is gone")
        self.assertGreater(houdini, -1, "the Houdini lookup is gone")
        self.assertLess(
            check, houdini,
            "the argument check moved below the Houdini lookup, so a "
            "typo now pays for an interpreter start to be refused")

    def test_a_real_module_name_reaches_the_runner(self):
        """Structural, not executed: running it for real would cost a
        full Houdini start. What must hold is that the named modules -
        not MODULES - are what `hython -m unittest` is handed."""
        with open(self._script(), encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("hython -m unittest $run_modules", source,
                      "the runner no longer runs the resolved module "
                      "list, so a named module cannot reach it")
        self.assertIn('run_modules="$wanted_modules"', source,
                      "named modules are no longer what gets run")
        self.assertIn('run_modules="$MODULES"', source,
                      "an argument-less run no longer runs the full "
                      "gate, which is the one thing that must not "
                      "change")

    def test_a_subset_says_it_is_not_the_gate(self):
        with open(self._script(), encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("SUBSET RUN", source,
                      "a subset run no longer announces itself, so a "
                      "green one reads exactly like the full gate")


class TestEveryTestFileIsInTheGate(unittest.TestCase):
    """A test file the runner never names is not in the suite.

    MODULES in start_test.sh is hand-maintained, so a new test file
    runs only for whoever wrote it and is silently absent from every
    sync and every push afterwards. That is the "194 tests passed and
    the crash shipped" failure with an extra step: the tests exist, are
    green when run by hand, and gate nothing.

    Found by counting: a local sweep ran 381 tests while the push gate
    reported 367 - exactly the two files that had just been added.
    """

    #: Not tests. test_support is the shared fixture helper; the rest
    #: are one-shot tools that live here because they import the same
    #: harness.
    NOT_SUITES = {
        "test_support",
    }

    def _tests_dir(self):
        return os.path.dirname(os.path.abspath(__file__))

    def _listed(self):
        start = os.path.join(self._tests_dir(), "start_test.sh")
        with open(start) as fh:
            src = fh.read()
        match = re.search(r'MODULES="(.*?)"', src, re.S)
        self.assertIsNotNone(
            match, "MODULES= is gone from start_test.sh - this test can no "
                   "longer see what the gate runs")
        return set(match.group(1).replace("\\\n", " ").split())

    def _on_disk(self):
        found = set()
        for name in os.listdir(self._tests_dir()):
            if name.startswith("test_") and name.endswith(".py"):
                found.add(name[:-3])
        return found - self.NOT_SUITES

    def test_no_test_file_is_missing_from_the_runner(self):
        missing = sorted(self._on_disk() - self._listed())
        self.assertEqual(
            [], missing,
            "these test files exist but the push gate never runs them - "
            "add them to MODULES in start_test.sh: %s" % missing)

    def test_the_runner_names_no_file_that_is_gone(self):
        """The other direction: a renamed or deleted file left in
        MODULES makes hython fail to import and takes the whole gate
        down, which reads as 'the suite is broken', not 'the list is
        stale'."""
        stale = sorted(self._listed() - self._on_disk() - self.NOT_SUITES)
        self.assertEqual(
            [], stale,
            "MODULES names test files that no longer exist: %s" % stale)

    def test_both_sides_are_actually_populated(self):
        """Guards the guard: two empty sets are equal."""
        self.assertGreater(len(self._on_disk()), 10,
                           "the directory scan found almost nothing")
        self.assertGreater(len(self._listed()), 10,
                           "MODULES parsed to almost nothing - the regex "
                           "no longer matches the shell syntax")


if __name__ == "__main__":
    unittest.main()
