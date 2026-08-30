"""The shell gates, tested like code because they are code - never on an exit status, always on the words and a terminal marker, and `$AMAZE` is never left empty here. ▸p/gate-fixture-safety ▸archive/test_shell_gates.py"""

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

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

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

REAL_RUNNER = os.path.join(
    REPO, "scripts", "python", "amaze", "tests", "start_test.sh")
REAL_LEAK_CHECK = os.path.join(
    REPO, "scripts", "python", "amaze", "tests", "check_log_leak.py")

RUNNER_REL = os.path.join("scripts", "python", "amaze", "tests",
                          "start_test.sh")

SYNC_GREEN_MSG = "sync-install: suite green - the install is safe to open."
SYNC_END = "sync-install: DONE"
SYNC_RED_END = "git stash && tools/sync-install.sh"
PUSH_GREEN_MSG = "tests OK, real debug log clean."
PUSH_END = "pre-push: DONE"
PUSH_RED_END = "Fix, or push --no-verify."


_STUB = r"""#!/bin/bash
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
    echo "hython: unable to obtain a licence" >&2
    exit 1
    ;;
no_tests)
    echo "Ran 0 tests in 0.001s"
    echo
    echo "OK"
    exit 0
    ;;
silent)
    exit 0
    ;;
leak)
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
    """A throwaway repo, install and fake `$HFS`, with the real gate scripts copied in and a stub runner. ▸p/gate-fixture-safety"""

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
        # The shelf is NOT optional: tolerating a missing toolbar/ is the under-sync this catches.
        _write(os.path.join(self.repo, "toolbar", "Amaze.shelf"),
               "<shelfDocument/>\n")
        _write(os.path.join(self.repo, "scripts", "python", "amaze",
                            "widget.py"), "VALUE = 1\n")

        self.private_hooks = os.path.join(self.tmp, "private-hooks")   # a permissive stand-in for the private repo's process gate, so these tests keep pinning the suite gate; its refusals have their own tests
        os.makedirs(self.private_hooks)
        _write(os.path.join(self.private_hooks, "pre-push-gate"),
               "#!/bin/sh\nexit 0\n", executable=True)

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

    def _git(self, *args):
        result = subprocess.run(("git", "-C", self.repo) + args,
                                capture_output=True, text=True,
                                env=self.git_env)
        self.assertEqual(result.returncode, 0,
                         "git %s failed:\n%s%s"
                         % (" ".join(args), result.stdout, result.stderr))
        return result.stdout.strip()

    def _make_git_repo(self):
        """`nowhere.git` deliberately does not exist, so a stray push fails loudly instead of succeeding."""
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
        """Unpushed commits touching exactly these paths - git answers FORWARD slashes on every platform, `os.path.join` does not."""
        for relative in relative_paths:
            _write(os.path.join(self.repo, relative), "touched\n")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "change " + " ".join(relative_paths))
        self.assertEqual(
            sorted(self._git("diff", "--name-only",
                             "%s..HEAD" % self.base_sha).splitlines()),
            sorted(p.replace(os.sep, "/") for p in relative_paths),
            "the fixture range is not what we set up")
        return self._git("rev-parse", "HEAD")

    def _env(self, mode, **extra):
        """Never inherits a real bypass variable from the calling suite."""
        env = dict(os.environ)
        for name in ("AMAZE_SYNC_NO_VERIFY", "AMAZE_SKIP_TESTS",
                     "AMAZE_SCRATCH_INSTALL"):
            env.pop(name, None)
        env.update(self.git_env)
        env.update({
            "AMAZE": self.install,
            "HFS": self.hfs,
            "FAKE_SUITE_MODE": mode,
            "FAKE_SUITE_CALLS": self.calls,
            "AMAZE_PRIVATE_HOOKS": self.private_hooks,
        })
        env.update(extra)
        return env

    def _run_on_a_terminal(self, script, cwd, stdin, env):
        """The script with a real pty on fd 2, so its `[ -t 2 ]` is true. Drained on a thread, or a chatty run fills the pty buffer and blocks forever."""
        import pty
        import threading
        master, slave = pty.openpty()
        chunks = []

        def drain():
            while True:
                try:
                    data = os.read(master, 65536)
                except OSError:
                    return
                if not data:
                    return
                chunks.append(data)

        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        try:
            result = subprocess.run(
                ["bash", script], stdout=subprocess.PIPE, stderr=slave,
                text=True, cwd=cwd, input=stdin, env=env, timeout=600)
        finally:
            os.close(slave)
        reader.join(timeout=10)
        os.close(master)
        result.stderr = b"".join(chunks).decode("utf-8", "replace")
        return result

    def _run(self, script_relative, mode="green", cwd=None, stdin="",
             terminal=False, **extra):
        script = os.path.join(self.repo, script_relative)
        self.assertNotIn(REPO, os.path.realpath(script),
                         "refusing to run the REAL gate script")
        env = self._env(mode, **extra)
        if terminal:
            return self._run_on_a_terminal(script, cwd or self.tmp, stdin, env)
        return subprocess.run(["bash", script], capture_output=True,
                              text=True, cwd=cwd or self.tmp, input=stdin,
                              env=env)

    def sync(self, mode="green", **extra):
        # From an unrelated cwd on purpose - it claims to run from anywhere.
        return self._run(os.path.join("tools", "sync-install.sh"),
                         mode, cwd=self.tmp, **extra)

    def ref_line(self, local_sha, local_ref=None, remote_ref=None,
                 remote_sha=None):
        """One line of git's pre-push stdin - the hook gates on THIS, not HEAD, so a test that fakes it proves nothing."""
        branch_ref = "refs/heads/%s" % self.branch
        return "%s %s %s %s\n" % (local_ref or branch_ref, local_sha,
                                  remote_ref or branch_ref,
                                  self.base_sha if remote_sha is None
                                  else remote_sha)

    def push(self, mode="green", stdin=None, **extra):
        """Runs the hook the way git does - cwd at the repo root, ref lines on stdin."""
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



class FixtureFidelityTest(GateFixture):

    def test_every_gate_script_exists_where_the_tests_expect_it(self):
        for real in list(GATE_SCRIPTS.values()) + [REAL_RUNNER,
                                                   REAL_LEAK_CHECK]:
            self.assertTrue(os.path.isfile(real), real)
            self.assertGreater(os.path.getsize(real), 0, real)

    def test_the_fixture_holds_the_real_scripts_byte_for_byte(self):
        """Copied at setUp, hashed here - if this fails, every other test in the file is measuring a fossil."""
        for relative, real in GATE_SCRIPTS.items():
            self.assertEqual(_sha(os.path.join(self.repo, relative)),
                             _sha(real),
                             "fixture copy of %s has drifted" % relative)

    @staticmethod
    def _command_lines(script_text):
        """The script with full-line comments removed - grep the line that RUNS, never prose about it."""
        return "\n".join(line for line in script_text.splitlines()
                         if not line.lstrip().startswith("#"))

    def test_the_stub_still_matches_the_real_runner(self):
        """The stub fakes the real runner's OUTPUT, so if that output changes the stub is a lie."""
        with open(REAL_RUNNER, encoding="utf-8") as handle:
            code = self._command_lines(handle.read())
        self.assertIn("run_suite.py", code,
                      "the real runner no longer drives run_suite.py, "
                      "whose unittest-shaped output is what the stub "
                      "fakes - restub")
        self.assertIn("check_log_leak.py", code,
                      "the real runner no longer runs the leak check")
        with open(REAL_LEAK_CHECK, encoding="utf-8") as handle:
            self.assertIn("LOG LEAK", handle.read(),
                          "the leak check no longer prints 'LOG LEAK' - "
                          "both gates grep for that literal")

    def test_no_command_line_runs_bare_unittest(self):
        """Bare `unittest` skips the sync, the isolated log dir, the lint and the leak check - every guard, to save two minutes."""
        with open(REAL_RUNNER, encoding="utf-8") as handle:
            self.assertNotIn("hython -m unittest",
                             self._command_lines(handle.read()),
                             "a command line runs bare hython -m "
                             "unittest - every gate that run skips")

    def test_the_fixture_never_points_at_the_real_install(self):
        env = self._env("green")
        self.assertEqual(env["AMAZE"], self.install)
        self.assertTrue(env["AMAZE"].startswith(tempfile.gettempdir())
                        or "/var/folders/" in env["AMAZE"]
                        or env["AMAZE"].startswith("/private/"),
                        "the fixture install is not in a tmpdir: %s"
                        % env["AMAZE"])
        self.assertNotIn("Cloud", env["AMAZE"])



class SyncInstallGateTest(GateFixture):

    def test_green_suite_ships_and_says_so(self):
        result = self.sync("green")
        self.assertEqual(result.returncode, 0, self.both(result))
        self.assertIn(SYNC_GREEN_MSG, result.stdout)
        self.assertEqual(len(self.suite_calls()), 1,
                         "the suite ran %r times" % self.suite_calls())

    def test_an_uncommitted_file_is_refused_before_anything_ships(self):
        """The install only ever receives COMMITTED code, untracked included - the mirror copies `scripts/` wholesale."""
        _write(os.path.join(self.repo, "scripts", "python", "amaze",
                            "stray.py"), "# this was never committed\n")

        result = self.sync("green")

        self.assertEqual(result.returncode, 1, self.both(result))
        self.assertIn("uncommitted changes", self.both(result))
        self.assertIn("stray.py", self.both(result),
                      "the refusal did not name what was uncommitted")
        self.assertFalse(
            os.path.exists(os.path.join(self.install, "OPmenu.xml")),
            "it refused and shipped anyway - the check must run BEFORE "
            "the mirror, not after it")
        self.assertEqual([], self.suite_calls(),
                         "the suite ran despite the refusal")

    def _scratch(self):
        path = tempfile.mkdtemp(prefix="amaze_scratch_install")
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        return path

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

    def test_the_real_destination_still_refuses_a_dirty_tree(self):
        """The exemption is the scratch path ALONE - leaking it to the ordinary path retires the rule rather than satisfying it."""
        _write(os.path.join(self.repo, "scripts", "python", "amaze",
                            "stray.py"), "# this was never committed\n")

        result = self.sync("green")

        self.assertEqual(result.returncode, 1, self.both(result))
        self.assertIn("uncommitted changes", self.both(result))

    def test_a_scratch_pointing_at_the_real_install_is_refused(self):
        """A typo must not aim a sabotage at the tree this protects."""
        _write(os.path.join(self.repo, "scripts", "python", "amaze",
                            "stray.py"), "# sabotaged\n")

        result = self.sync("green", AMAZE_SCRATCH_INSTALL=self.install)

        self.assertEqual(result.returncode, 1, self.both(result))
        self.assertIn("REAL install", self.both(result))

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

    def test_green_run_reaches_its_end(self):
        """The DONE marker must be the LAST line - exit status alone cannot tell a clean finish from a `set -e` death after shipping."""
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
        # The shelf is how a hotkey reaches Amaze; unsynced, no tool appears in Houdini.
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
        """The rollback command is the last thing printed, so it doubles as the marker that the red path ran to its end."""
        result = self.sync("red")
        self.assertReachedEnd(result, SYNC_RED_END)

    def test_a_suite_that_cannot_run_is_refused(self):
        """No FAIL line and no `Ran` line is not the same as nothing wrong - the state that shipped broken."""
        result = self.sync("crash")
        self.assertNotEqual(result.returncode, 0,
                            "a dead suite was reported as a good ship:\n%s"
                            % self.both(result))
        self.assertNotIn(SYNC_END, result.stdout)

    def test_a_suite_that_cannot_run_says_why(self):
        """The script has the words for it, and must actually reach them."""
        result = self.sync("crash")
        self.assertIn("The suite did not run at all", result.stderr,
                      "STDOUT:\n%s\nSTDERR:\n%s"
                      % (result.stdout, result.stderr))
        self.assertReachedEnd(result, SYNC_RED_END)

    def test_a_suite_that_ran_zero_tests_is_refused(self):
        """`Ran 0 tests ... OK` exits 0 with no failures and verifies nothing."""
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
        """Green tests and a zero exit, but the run wrote to the real debug log - that arm must not be dead code."""
        result = self.sync("leak")
        self.assertNotEqual(result.returncode, 0, self.both(result))
        self.assertNotIn(SYNC_END, result.stdout)

    def test_no_verify_skips_the_suite_entirely(self):
        """`run-tests.sh` sets this to break the recursion, or the suite runs twice per command."""
        result = self.sync("crash", AMAZE_SYNC_NO_VERIFY="1")
        self.assertEqual(result.returncode, 0, self.both(result))
        self.assertEqual(self.suite_calls(), [],
                         "the suite ran despite AMAZE_SYNC_NO_VERIFY")

    def test_a_missing_install_is_refused_before_anything_is_copied(self):
        """`$AMAZE` pointing nowhere stops at the guard. `$AMAZE` EMPTY is never exercised - it falls back to the package file, which names the REAL install."""
        missing = os.path.join(self.tmp, "not_an_install")
        result = self.sync("green", AMAZE=missing)
        self.assertEqual(result.returncode, 1, self.both(result))
        self.assertIn("cannot find the install", result.stderr)
        self.assertFalse(os.path.exists(missing))
        self.assertEqual(self.suite_calls(), [])

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

    def test_the_process_gate_runs_first_and_its_refusal_stops_the_push(self):
        refusing = os.path.join(self.tmp, "refusing-hooks")
        os.makedirs(refusing)
        _write(os.path.join(refusing, "pre-push-gate"),
               '#!/bin/sh\necho "process gate says no" >&2\nexit 1\n',
               executable=True)
        self._commit(os.path.join("scripts", "python", "amaze", "widget.py"))
        result = self.push("green", AMAZE_PRIVATE_HOOKS=refusing)
        self.assertNotEqual(result.returncode, 0, self.both(result))
        self.assertIn("process gate says no", self.both(result))
        self.assertEqual([], self.suite_calls(),
                         "the suite ran before the process gate answered")

    def test_a_missing_process_gate_fails_closed(self):
        empty = os.path.join(self.tmp, "no-hooks")
        os.makedirs(empty)
        self._commit(os.path.join("scripts", "python", "amaze", "widget.py"))
        result = self.push("green", AMAZE_PRIVATE_HOOKS=empty)
        self.assertNotEqual(result.returncode, 0, self.both(result))
        self.assertIn("process gate is not installed", self.both(result))
        self.assertEqual([], self.suite_calls(),
                         "a missing gate must refuse, not pass silently")

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
        self._commit(os.path.join("scripts", "python", "amaze", "widget.py"))
        result = self.push("crash")
        self.assertNotEqual(result.returncode, 0,
                            "a dead suite was reported as a green push:\n%s"
                            % self.both(result))
        self.assertNotIn(PUSH_END, result.stdout)
        self.assertReachedEnd(result, PUSH_RED_END)

    def test_a_suite_that_ran_zero_tests_is_refused(self):
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



    def test_a_docs_only_push_still_runs_the_suite(self):
        """Only `.svg` earns the short run - every other file type runs the whole suite, however harmless it looks."""
        self._commit(os.path.join("docs", "a.md"))
        result = self.push("green")
        self.assertIn("running the suite", self.both(result))
        self.assertEqual(len(self.suite_calls()), 1)
        self.assertEqual(result.returncode, 0, self.both(result))
        self.assertIn("pre-push: DONE", result.stdout)

    def _svg(self, name="scripts/python/amaze/ui/badge_x.svg"):
        return self._commit(os.path.join(*name.split("/")))

    def test_an_svg_only_push_runs_the_art_modules_not_the_suite(self):
        """Art is data and cannot carry a logic bug, so it earns the short run - but it still runs the tests that READ the art."""
        self._svg()
        result = self.push("green", terminal=True)
        self.assertEqual(result.returncode, 0, self.both(result))
        self.assertIn("art only", self.both(result))
        self.assertEqual(
            1, len(self.suite_calls()),
            "the art run did not happen: %r" % self.suite_calls())
        self.assertIn(
            "test_hip_section", self.suite_calls()[0],
            "the short run did not name the art modules: %r"
            % self.suite_calls())
        self.assertIn("pre-push: DONE", result.stdout)

    def test_one_code_file_among_the_svgs_runs_everything(self):
        """The whole hazard in one case - a push classified as art while code rides along."""
        self._commit(os.path.join("scripts", "python", "amaze", "ui",
                                  "badge_x.svg"),
                     os.path.join("scripts", "python", "amaze", "widget.py"))
        result = self.push("green", terminal=True)
        self.assertNotIn("art only", self.both(result))
        self.assertIn("running the suite", self.both(result))
        self.assertEqual(result.returncode, 0, self.both(result))

    def test_an_svg_push_with_no_terminal_runs_everything(self):
        """The short run is for a person who just redrew a badge and can see it - anything automated gets the whole gate."""
        self._svg()
        result = self.push("green")
        self.assertNotIn("art only", self.both(result))
        self.assertIn("running the suite", self.both(result))

    def test_an_unreadable_range_never_earns_the_art_run(self):
        """A diff that FAILED must not read as a diff naming only art."""
        self._svg()
        result = self.push("red", stdin=self.ref_line(
            "b" * 40, remote_sha="c" * 40), terminal=True)
        self.assertNotIn("art only", self.both(result))
        self.assertEqual(result.returncode, 1, self.both(result))

    def test_no_refs_on_stdin_never_earns_the_art_run(self):
        """Missing information is not evidence that a push is art."""
        self._svg()
        result = self.push("red", stdin="", terminal=True)
        self.assertNotIn("art only", self.both(result))
        self.assertEqual(result.returncode, 1, self.both(result))

    def test_the_art_modules_cover_every_module_that_reads_the_art(self):
        """A list nothing derives goes stale silently - the short run must name every module that asserts on the artwork. Keyed on the CALL form, or the search matches its own pattern and the helper that defines it."""
        with open(GATE_SCRIPTS[os.path.join("tools", "git-hooks",
                                            "pre-push")],
                  encoding="utf-8") as handle:
            named = re.search(r'^ART_MODULES="([^"]*)"', handle.read(),
                              re.M)
        self.assertIsNotNone(named, "pre-push no longer names ART_MODULES")
        listed = set(named.group(1).split())
        tests_dir = os.path.dirname(os.path.abspath(__file__))
        reads_art = set()
        for name in sorted(os.listdir(tests_dir)):
            if not (name.startswith("test_") and name.endswith(".py")):
                continue
            with open(os.path.join(tests_dir, name), encoding="utf-8") as fh:
                if re.search(r"\.art_colours\(|\._effective_paint\(",
                             fh.read()):
                    reads_art.add(name[:-3])
        self.assertEqual(
            set(), reads_art - listed,
            "a module asserts on the art but is not in the short run, so "
            "an svg-only push would never exercise it")

    def test_a_second_ref_carrying_code_runs_everything(self):
        """`git push --all` feeds several lines, and an art-only ref must not excuse one carrying code."""
        art = self._commit(os.path.join("scripts", "python", "amaze", "ui",
                                        "badge_x.svg"))
        self._git("checkout", "-q", "-b", "feature", self.base_sha)
        code = self._commit(os.path.join("scripts", "python", "amaze",
                                         "widget.py"))
        stdin = (self.ref_line(art)
                 + self.ref_line(code, local_ref="refs/heads/feature",
                                 remote_ref="refs/heads/feature"))
        result = self.push("green", stdin=stdin, terminal=True)
        self.assertNotIn("art only", self.both(result))
        self.assertIn("running the suite", self.both(result))


    def test_a_push_touching_a_shell_script_does_not_skip(self):
        """An allowlist that misses `.sh` lets a push changing the TEST RUNNER ITSELF skip the gate."""
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
        """`git push origin feature:main` is a total bypass if the hook reads HEAD instead of the ref being pushed."""
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
        """`git push --all` feeds several lines, and one docs-only ref must not excuse a second carrying code."""
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
        """An all-zero REMOTE sha is a branch that does not exist there yet, and if no diff can be found the hook runs the suite rather than skipping."""
        code = self._commit(os.path.join("scripts", "python", "amaze",
                                         "widget.py"))
        result = self.push("red", stdin=self.ref_line(
            code, local_ref="refs/heads/brand-new",
            remote_ref="refs/heads/brand-new", remote_sha="0" * 40))
        self.assertNotIn("suite skipped", result.stdout)
        self.assertEqual(result.returncode, 1, self.both(result))


    def test_no_refs_on_stdin_runs_the_suite(self):
        """Missing information must never read as nothing to do - this is also the hook invoked by hand."""
        result = self.push("red", stdin="")
        self.assertNotIn("suite skipped", result.stdout)
        self.assertEqual(result.returncode, 1, self.both(result))
        self.assertEqual(len(self.suite_calls()), 1)

    def test_an_unreadable_range_runs_the_suite(self):
        """A FAILED diff must never be read as an EMPTY one, or a code push skips the gate whenever the remote sha is missing locally."""
        result = self.push("red", stdin=self.ref_line(
            "b" * 40, remote_sha="c" * 40))
        self.assertNotIn("nothing to test", result.stdout,
                         "an undiffable range was reported as 'nothing to "
                         "test' - the suite was skipped for a code push")
        self.assertEqual(result.returncode, 1, self.both(result))

    def test_a_branch_deletion_is_not_reported_as_docs_only(self):
        """An all-zero local sha is a deletion, and whatever it does it must not claim the code was vetted."""
        result = self.push("red", stdin=self.ref_line(
            "0" * 40, local_ref="refs/heads/dead"))
        self.assertNotIn("docs only", result.stdout)

    def test_the_escape_hatch_needs_the_sha_being_pushed(self):
        """Not a boolean - a boolean gets exported once in a shell profile and disables the gate forever."""
        self._commit(os.path.join("scripts", "python", "amaze", "widget.py"))
        head = self._git("rev-parse", "HEAD")
        result = self.push("crash", AMAZE_SKIP_TESTS=head)
        self.assertEqual(result.returncode, 0, self.both(result))
        self.assertIn("AMAZE_SKIP_TESTS", result.stderr)
        self.assertEqual(self.suite_calls(), [])

    def test_a_stale_escape_hatch_does_not_disable_the_gate(self):
        """Exported and forgotten - set, but to a sha that is no longer HEAD, so the suite still runs."""
        self._commit(os.path.join("scripts", "python", "amaze", "widget.py"))
        result = self.push("red", AMAZE_SKIP_TESTS=self.base_sha)
        self.assertEqual(result.returncode, 1, self.both(result))
        self.assertEqual(len(self.suite_calls()), 1,
                         "a stale AMAZE_SKIP_TESTS disabled the gate")



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


class TargetedRunTest(unittest.TestCase):
    """`start_test.sh <module>` runs THAT module, driven against the argument prologue, which exits before Houdini is looked for so these cost no interpreter start."""

    def _script(self):
        return os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "start_test.sh")

    def _run(self, *args):
        """The timeout is LOAD-BEARING: without it a regressed argument check starts the whole suite recursively from inside itself."""
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
        """A guard inspecting only `$1` lets `--isolated <junk>` through with the junk silently dropped."""
        result = self._run("--isolated", "test_no_such_module_here")
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertIn("no such test module", result.stderr)

    def test_the_refusal_costs_no_interpreter_start(self):
        """The argument check sits ABOVE the Houdini lookup, or a typo costs a Houdini start to be told it was a typo."""
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
        """Read from the source, never executed - running it costs a full Houdini start. Pins that the RESOLVED module list is what the runner is handed."""
        with open(self._script(), encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("run_suite.py\" $run_modules", source,
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
    """`MODULES` is hand-maintained, so a test file it never names is green by hand and gates nothing."""

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
        """A deleted file left in `MODULES` fails the import and takes the whole gate down, reading as a broken suite rather than a stale list."""
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


class EveryToolSpeaksTheResolver(unittest.TestCase):
    """Every `tools/*.sh` reaching for hython sources the one resolver, and the two recorded trap spellings are banned from the directory."""

    def test_no_tool_carries_the_recorded_traps(self):
        tools = os.path.join(REPO, "tools")
        checked = 0
        for name in sorted(os.listdir(tools)):
            if not name.endswith(".sh"):
                continue
            checked += 1
            with open(os.path.join(tools, name), encoding="utf-8") as f:
                text = f.read()
            self.assertNotIn(
                "mktemp -d -t", text,
                "%s: GNU/MSYS mktemp refuses -t with no X's - the "
                "script dies on line one on Windows" % name)
            self.assertNotIn(
                "ls -d /Applications", text,
                "%s carries its own mac-only Houdini lookup beside the "
                "shared resolver" % name)
            if "hython" in text and name != "houdini-env.sh":
                self.assertIn(
                    "houdini-env.sh", text,
                    "%s reaches for hython without sourcing the "
                    "resolver" % name)
        self.assertGreaterEqual(checked, 4,
                                "the tools directory scan went vacuous")


if __name__ == "__main__":
    unittest.main()
