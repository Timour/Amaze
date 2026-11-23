"""Gate tests check printed text and an end marker, not exit status alone. ▸p/gate-fixture-safety"""

import ast
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

from amaze.tests import test_support  # importing it redirects the log

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
    os.path.join("tools", "select-tests.py"):
        os.path.join(REPO, "tools", "select-tests.py"),
    os.path.join("tools", "check-requirements.py"):
        os.path.join(REPO, "tools", "check-requirements.py"),
    os.path.join("scripts", "python", "amaze", "tests", "impact_map.py"):
        os.path.join(REPO, "scripts", "python", "amaze", "tests", "impact_map.py"),
    os.path.join("scripts", "python", "amaze", "tests", "check_dead_cover.py"):
        os.path.join(REPO, "scripts", "python", "amaze", "tests", "check_dead_cover.py"),
}

REAL_RUNNER = os.path.join(
    REPO, "scripts", "python", "amaze", "tests", "start_test.sh")
REAL_LEAK_CHECK = os.path.join(
    REPO, "scripts", "python", "amaze", "tests", "check_log_leak.py")

RUNNER_REL = os.path.join("scripts", "python", "amaze", "tests",
                          "start_test.sh")
BRANDING_REL = os.path.join("scripts", "python", "amaze", "branding.py")

SYNC_SHIPPED_MSG = "is identical to the repo"
SYNC_END = "sync-install: DONE"
PUSH_GREEN_MSG = "tests OK, real debug log clean."
PUSH_END = "pre-push: DONE"
PUSH_RED_END = "Fix, or push --no-verify."


_STUB = r"""#!/bin/bash
MODULES="test_widget test_other"
GATE_MODULES=""
mode="${FAKE_SUITE_MODE:-green}"
echo "$mode $*${AMAZE_HOUDINI:+ on $AMAZE_HOUDINI}" >> "$FAKE_SUITE_CALLS"
if [ -n "${AMAZE_SKIP_REPORT:-}" ]; then
    houdini="$(printf '%s' "${AMAZE_HOUDINI:-}" | sed 's/\\/\\\\/g')"    # a Windows path's backslashes are JSON escapes
    printf '{"testsRun": 203, "houdini": "%s", "skipped": %s}\n' \
        "$houdini" "${FAKE_SKIPPED:-[]}" > "$AMAZE_SKIP_REPORT"
fi

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


def _write(path, text, executable=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    if executable:
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP)


class GateFixture(unittest.TestCase):
    """A throwaway repo and install, real gate scripts, a stub runner. ▸p/gate-fixture-safety"""

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
        plain = os.path.join(sys.base_prefix, "bin", "python3")
        _write(os.path.join(self.hfs, "bin", "hython"),    # a fake hython for the gate scripts: a real Houdini costs 1.3s a sync
               '#!/bin/bash\nexec "%s" "$@"\n'
               % (plain if os.path.isfile(plain) else "python3"), executable=True)
        _write(os.path.join(self.repo, ".gitignore"), "__pycache__/\n")    # a bytecode cache must not count as uncommitted ▸p/bytecode-cache-dirty-tree
        _write(os.path.join(self.repo, "OPmenu.xml"), "<menuDocument/>\n")
        _write(os.path.join(self.repo, "python_panels", "amaze.pypanel"),
               "<pythonPanelDocument/>\n")
        # The shelf is NOT optional: accepting a missing toolbar/ is the incomplete sync this catches.
        _write(os.path.join(self.repo, "toolbar", "Amaze.shelf"),
               "<shelfDocument/>\n")
        _write(os.path.join(self.repo, "scripts", "python", "amaze",
                            "widget.py"), "VALUE = 1\n")

        self.private_hooks = os.path.join(self.tmp, "private-hooks")   # a process gate that always passes; its refusals have their own tests
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

    def _scratch(self):
        path = tempfile.mkdtemp(prefix="amaze_scratch_install")
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        return path

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
        """Unpushed commits touching exactly these paths; git returns forward slashes on every OS."""
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

    def _versions(self, checkout, installed):
        """Commit `checkout` as the repo's `APP_VERSION` and put `installed` in the install."""
        _write(os.path.join(self.repo, BRANDING_REL), 'APP_VERSION = "%s"\n' % checkout)
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "version " + checkout)
        self._install_holds(installed)

    def _install_holds(self, version):
        path = os.path.join(self.install, BRANDING_REL)
        _write(path, 'APP_VERSION = "%s"\n' % version)
        os.utime(path, (1, 1))    # written at another time: rsync skips a same-size file of the same second

    def _installed_version(self):
        """The version in the install's `branding.py`, as the file spells it."""
        with open(os.path.join(self.install, BRANDING_REL), encoding="utf-8") as handle:
            return handle.read().split('"')[1]

    def _env(self, mode, **extra):
        """Never inherits a real bypass variable, or the pushing repository, from the calling suite."""
        env = dict(os.environ)
        env.update(self.git_env)    # a copy of the environment too, so the removals below come after it
        for name in ("AMAZE_SYNC_NO_VERIFY", "AMAZE_SKIP_TESTS", "AMAZE_REPLACE_INSTALLED",
                     "AMAZE_SCRATCH_INSTALL", "AMAZE_HOUDINI", "AMAZE_SKIP_REPORT",
                     "GIT_DIR", "GIT_WORK_TREE"):    # a worktree's pre-push sets GIT_DIR ▸r/git-hook-surface
            env.pop(name, None)
        env.update({
            "AMAZE": self.install,
            "HFS": self.hfs,
            "FAKE_SUITE_MODE": mode,
            "FAKE_SUITE_CALLS": self.calls,
            "AMAZE_PRIVATE_HOOKS": self.private_hooks,
        })
        env.update(extra)
        return env

    def _run(self, script_relative, mode="green", cwd=None, stdin="", **extra):
        script = os.path.join(self.repo, script_relative)
        self.assertNotIn(REPO, os.path.realpath(script),
                         "refusing to run the REAL gate script")
        env = self._env(mode, **extra)
        return subprocess.run([test_support.bash(), script], capture_output=True,
                              text=True, cwd=cwd or self.tmp, input=stdin,
                              env=env)

    def sync(self, mode="green", **extra):
        # From an unrelated cwd on purpose - the script states it runs from anywhere.
        return self._run(os.path.join("tools", "sync-install.sh"),
                         mode, cwd=self.tmp, **extra)

    def ref_line(self, local_sha, local_ref=None, remote_ref=None,
                 remote_sha=None):
        """One line of git's pre-push stdin; the hook checks these refs, not HEAD."""
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

    @staticmethod
    def _command_lines(script_text):
        """The script with full-line comments removed - search the lines that RUN, never comments."""
        return "\n".join(line for line in script_text.splitlines()
                         if not line.lstrip().startswith("#"))

    def test_the_stub_still_matches_the_real_runner(self):
        """The stub fakes the real runner's OUTPUT, so if that output changes the stub is wrong."""
        with open(REAL_RUNNER, encoding="utf-8") as handle:
            code = self._command_lines(handle.read())
        self.assertIn("run_suite.py", code,
                      "the real runner no longer runs run_suite.py, "
                      "whose unittest-format output is what the stub "
                      "imitates - update the stub")
        self.assertIn("check_log_leak.py", code,
                      "the real runner no longer runs the leak check")
        with open(REAL_LEAK_CHECK, encoding="utf-8") as handle:
            self.assertIn("LOG LEAK", handle.read(),
                          "the leak check no longer prints 'LOG LEAK' - "
                          "both gates search for that exact text")
        self.assertNotIn("hython -m unittest", code,
                         "a command line runs bare hython -m unittest, "
                         "which skips the sync, the log sandbox, the lint "
                         "and the leak check")

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

    def test_an_uncommitted_file_stops_the_sync_before_anything_is_copied(self):
        """Only committed code is installed, untracked included: the mirror copies `scripts/`."""
        _write(os.path.join(self.repo, "scripts", "python", "amaze",
                            "stray.py"), "# this was never committed\n")

        result = self.sync("green")

        self.assertEqual(result.returncode, 1, self.both(result))
        self.assertIn("uncommitted changes", self.both(result))
        self.assertIn("stray.py", self.both(result),
                      "the refusal did not name what was uncommitted")
        self.assertFalse(
            os.path.exists(os.path.join(self.install, "OPmenu.xml")),
            "it refused and copied to the install anyway - the check must run BEFORE "
            "the mirror, not after it")
        self.assertEqual([], self.suite_calls(),
                         "the suite ran despite the refusal")

    def test_a_scratch_pointing_at_the_real_install_stops_the_sync(self):
        """A typo must not point the sabotage test at the real install this script protects."""
        _write(os.path.join(self.repo, "scripts", "python", "amaze",
                            "stray.py"), "# sabotaged\n")

        result = self.sync("green", AMAZE_SCRATCH_INSTALL=self.install)

        self.assertEqual(result.returncode, 1, self.both(result))
        self.assertIn("REAL install", self.both(result))

    def test_a_missing_install_stops_the_sync_before_anything_is_copied(self):
        """A missing `$AMAZE` folder stops at the check; empty is never run: it means the real install."""
        missing = os.path.join(self.tmp, "not_an_install")
        result = self.sync("green", AMAZE=missing)
        self.assertEqual(result.returncode, 1, self.both(result))
        self.assertIn("cannot find the install", result.stderr)
        self.assertFalse(os.path.exists(missing))
        self.assertEqual(self.suite_calls(), [])

    def test_an_install_that_holds_a_newer_version_is_left_as_it_is(self):
        """Every machine shares the install, so one that is behind must not copy over it."""
        self._versions(checkout="1.35.1", installed="1.36.0")

        result = self.sync("green")

        self.assertEqual(result.returncode, 3, self.both(result))
        self.assertIn("the install holds Amaze 1.36.0", result.stderr)
        self.assertIn("this checkout is 1.35.1", result.stderr)
        self.assertEqual("1.36.0", self._installed_version())
        self.assertFalse(os.path.exists(os.path.join(self.install, "OPmenu.xml")),
                         "it refused and copied to the install anyway")

    def test_newer_is_read_as_numbers_and_the_same_or_an_older_install_is_copied(self):
        self._versions(checkout="1.9.12", installed="1.10.0")    # as text, "1.9.12" sorts last
        self.assertEqual(3, self.sync("green").returncode, "1.10.0 was read as older than 1.9.12")
        for installed in ("1.9.12", "1.9.2", "1.8.40"):
            with self.subTest(installed=installed):
                self._install_holds(installed)
                result = self.sync("green")
                self.assertEqual(result.returncode, 0, self.both(result))
                self.assertReachedEnd(result, SYNC_END)
                self.assertEqual("1.9.12", self._installed_version())

    def test_an_older_build_goes_over_a_newer_one_only_when_that_version_is_named(self):
        """Not a boolean: the variable names the version it replaces, so it ends with that version."""
        self._versions(checkout="1.35.1", installed="1.36.0")

        stale = self.sync("green", AMAZE_REPLACE_INSTALLED="1.35.9")
        self.assertEqual(stale.returncode, 3, self.both(stale))
        self.assertEqual("1.36.0", self._installed_version())

        result = self.sync("green", AMAZE_REPLACE_INSTALLED="1.36.0")
        self.assertEqual(result.returncode, 0, self.both(result))
        self.assertReachedEnd(result, SYNC_END)
        self.assertEqual("1.35.1", self._installed_version())


class PrePushGateTest(GateFixture):

    def test_the_process_gate_runs_first_and_its_failure_stops_the_push(self):
        failing_hooks = os.path.join(self.tmp, "refusing-hooks")
        os.makedirs(failing_hooks)
        _write(os.path.join(failing_hooks, "pre-push-gate"),
               '#!/bin/sh\necho "process gate says no" >&2\nexit 1\n',
               executable=True)
        self._commit(os.path.join("scripts", "python", "amaze", "widget.py"))
        result = self.push("green", AMAZE_PRIVATE_HOOKS=failing_hooks)
        self.assertNotEqual(result.returncode, 0, self.both(result))
        self.assertIn("process gate says no", self.both(result))
        self.assertEqual([], self.suite_calls(),
                         "the suite ran before the process gate finished")

    def test_a_missing_process_gate_fails_closed(self):
        empty = os.path.join(self.tmp, "no-hooks")
        os.makedirs(empty)
        self._commit(os.path.join("scripts", "python", "amaze", "widget.py"))
        result = self.push("green", AMAZE_PRIVATE_HOOKS=empty)
        self.assertNotEqual(result.returncode, 0, self.both(result))
        self.assertIn("maintainer checks are not installed", self.both(result))
        self.assertEqual([], self.suite_calls(),
                         "a missing gate must refuse, not pass silently")

    def test_red_suite_stops_the_push_and_names_the_failures(self):
        self._commit(os.path.join("scripts", "python", "amaze", "widget.py"))
        result = self.push("red")
        self.assertEqual(result.returncode, 1, self.both(result))
        self.assertIn("PUSH REFUSED", result.stderr)
        self.assertIn("FAIL: test_tile_is_composed", result.stderr)
        self.assertNotIn(PUSH_END, result.stdout)
        self.assertReachedEnd(result, PUSH_RED_END)

    def test_amaze_skip_tests_needs_the_sha_being_pushed(self):
        """Not a boolean - a boolean gets exported once in a shell profile and disables the gate forever."""
        self._commit(os.path.join("scripts", "python", "amaze", "widget.py"))
        head = self._git("rev-parse", "HEAD")
        result = self.push("crash", AMAZE_SKIP_TESTS=head)
        self.assertEqual(result.returncode, 0, self.both(result))
        self.assertIn("AMAZE_SKIP_TESTS", result.stderr)
        self.assertEqual(self.suite_calls(), [])


class TargetedRunTest(unittest.TestCase):
    """`start_test.sh <module>` runs that module; its argument check exits before Houdini starts."""

    def _script(self):
        return os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "start_test.sh")

    def _run(self, *args):
        """The timeout matters: a broken argument check starts the whole suite recursively."""
        try:
            return subprocess.run([test_support.bash(), self._script(), *args],
                                  capture_output=True, text=True,
                                  timeout=60)
        except subprocess.TimeoutExpired:
            self.fail(
                "start_test.sh did not refuse %r within 60s - the "
                "argument check has regressed and this call was "
                "starting the whole suite recursively" % (args,))

    def test_a_name_that_is_not_a_module_exits_with_2(self):
        for args in (("test_no_such_module_here",),
                     ("--isolated", "test_no_such_module_here")):    # a check reading only $1 misses it
            with self.subTest(args=args):
                result = self._run(*args)
                self.assertEqual(2, result.returncode, result.stderr)
                self.assertIn("no such test module", result.stderr)

    def test_the_argument_check_runs_before_the_houdini_lookup(self):
        """The argument check sits above the Houdini lookup, so a typo costs no Houdini start."""
        with open(self._script(), encoding="utf-8") as handle:
            source = handle.read()
        check = source.find("no such test module")
        houdini = source.find("AMAZE_HOUDINI")
        self.assertGreater(check, -1, "the argument check is gone")
        self.assertGreater(houdini, -1, "the Houdini lookup is gone")
        self.assertLess(
            check, houdini,
            "the argument check moved below the Houdini lookup, so a "
            "typo now costs an interpreter start before it is rejected")

    def test_a_real_module_name_reaches_the_runner(self):
        """Read from source, never executed: the runner gets the resolved module list."""
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
        self.assertIn("SUBSET RUN", source,
                      "a subset run no longer announces itself, so a "
                      "passing one looks exactly like the full gate")


class TestEveryTestFileIsInTheGate(unittest.TestCase):
    """`MODULES` is hand-maintained, so a test file it omits passes only by hand and blocks no push."""

    NOT_SUITES = {
        "test_support",
    }

    def _tests_dir(self):
        return os.path.dirname(os.path.abspath(__file__))

    def _list(self, name):
        start = os.path.join(self._tests_dir(), "start_test.sh")
        with open(start, encoding="utf-8") as fh:
            src = fh.read()
        match = re.search(r'^%s="(.*?)"' % name, src, re.S | re.M)
        self.assertIsNotNone(
            match, "%s= is gone from start_test.sh - this test can no "
                   "longer read what the gate runs" % name)
        return set(match.group(1).replace("\\\n", " ").split())

    def _listed(self):
        return self._list("MODULES") | self._list("GATE_MODULES")

    def _tuple_in(self, relative, name):
        """A module-level tuple or set of strings in a tool, read from its source."""
        path = os.path.join(REPO, relative)
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == name for t in node.targets):
                return set(ast.literal_eval(node.value))
        self.fail("%s is gone from %s" % (name, relative))

    def test_a_module_kept_out_of_the_default_run_still_runs(self):
        """GATE_MODULES skip a plain full run, so a tools/ change is the one place they run."""
        gate = self._list("GATE_MODULES")
        self.assertTrue(gate, "GATE_MODULES is empty - this test checks nothing")
        self.assertEqual(set(), gate & self._list("MODULES"), "a module is in both lists")
        self.assertEqual(set(), gate - self._tuple_in("tools/select-tests.py", "GATE_TESTS"),
                         "a push that changes tools/ would not run these")

    def _on_disk(self):
        found = set()
        for name in os.listdir(self._tests_dir()):
            if name.startswith("test_") and name.endswith(".py"):
                found.add(name[:-3])
        return found - self.NOT_SUITES

    def test_no_test_file_is_missing_from_the_runner(self):
        self.assertGreater(len(self._on_disk()), 10,    # two empty sets are equal
                           "the directory scan found almost nothing")
        self.assertGreater(len(self._listed()), 10,
                           "MODULES parsed to almost nothing - the regex "
                           "no longer matches the shell syntax")
        missing = sorted(self._on_disk() - self._listed())
        self.assertEqual(
            [], missing,
            "these test files exist but the push gate never runs them - "
            "add them to MODULES in start_test.sh: %s" % missing)

    def test_the_runner_names_no_file_that_is_gone(self):
        """A deleted file left in `MODULES` fails the import and with it the whole gate."""
        stale = sorted(self._listed() - self._on_disk() - self.NOT_SUITES)
        self.assertEqual(
            [], stale,
            "MODULES names test files that no longer exist: %s" % stale)


class EveryAppBuilderPicksOffscreen(unittest.TestCase):
    """The first module to build the app picks the platform for the run ▸p/first-app-picks-the-platform"""

    GUARD = 'os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")'

    def _builders(self):
        tests_dir = os.path.dirname(os.path.abspath(__file__))
        found = {}
        for name in sorted(os.listdir(tests_dir)):
            if not (name.startswith("test_") and name.endswith(".py")):
                continue
            with open(os.path.join(tests_dir, name), encoding="utf-8") as fh:
                source = fh.read()
            built = re.search(r"\bQ(?:Gui)?Application\(", source)
            if built:
                found[name[:-3]] = (source, built.start())
        return found

    def test_every_app_builder_sets_the_platform_first(self):
        builders = self._builders()
        self.assertGreater(len(builders), 40,    # a scan that matches nothing passes
                           "the app-construction pattern no longer matches")
        unguarded = sorted(
            name for name, (source, at) in builders.items()
            if not 0 <= source.find(self.GUARD) < at)
        self.assertEqual(
            [], unguarded,
            "these modules build the app before setting the platform, so a "
            "run they start uses the native platform and fails another module's layout "
            "asserts: %s" % unguarded)


class EveryTestModuleArmsTheSandbox(unittest.TestCase):
    """Importing `test_support` sets up the sandbox, so every module does it at module level."""

    def _imports_the_harness(self, tree):
        for node in tree.body:
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = ["%s.%s" % (node.module, alias.name)
                         for alias in node.names]
            else:
                continue
            if any(name.split(".")[-1] == "test_support" for name in names):
                return True
        return False

    def _modules(self):
        tests_dir = os.path.dirname(os.path.abspath(__file__))
        found = {}
        for name in sorted(os.listdir(tests_dir)):
            if name.startswith("test_") and name.endswith(".py") \
                    and name != "test_support.py":
                with open(os.path.join(tests_dir, name),
                          encoding="utf-8") as handle:
                    found[name[:-3]] = ast.parse(handle.read(), name)
        return found

    def test_every_test_module_imports_the_harness(self):
        unarmed = sorted(name for name, tree in self._modules().items()
                         if not self._imports_the_harness(tree))
        self.assertEqual(
            [], unarmed,
            "these test modules never import test_support at module level, "
            "so run on their own they can write the user's real folders: %s"
            % unarmed)

    def test_the_scan_sees_an_import(self):
        """Tests the check itself: a scan that matches nothing reports every module."""
        self.assertTrue(self._imports_the_harness(ast.parse(
            "from amaze.tests import test_support")))
        self.assertTrue(self._imports_the_harness(ast.parse(
            "import test_support")))
        self.assertFalse(self._imports_the_harness(ast.parse(
            "def f():\n    from amaze.tests import test_support\n")))
        self.assertGreater(len(self._modules()), 40,
                           "the test directory scan found almost nothing")


def _is_patch_call(node) -> bool:
    """`patch(...)`, `patch.object(...)`, `mock.patch.dict(...)` and the like."""
    if not isinstance(node, ast.Call):
        return False
    spelled = ast.unparse(node.func)
    return spelled == "patch" or spelled.startswith(("patch.", "mock.patch", "unittest.mock.patch"))


def _starts_left_running(tree) -> list:
    """Lines where a patch starts with no stop registered before it or on the very next line."""
    found = []

    def walk_block(block, patchers, stopall):
        for index, stmt in enumerate(block):
            for call in (n for n in ast.walk(stmt) if isinstance(n, ast.Call)):
                spelled = ast.unparse(call.func)
                if spelled.endswith("addCleanup") and any(
                        ast.unparse(a).endswith("patch.stopall") for a in call.args):
                    stopall = True
            if isinstance(stmt, ast.Assign) and _is_patch_call(stmt.value):
                patchers |= {ast.unparse(target) for target in stmt.targets}
            for call in (n for n in ast.walk(stmt) if isinstance(n, ast.Call)):
                receiver = getattr(call.func, "value", None)
                if getattr(call.func, "attr", "") != "start" or receiver is None:
                    continue
                if not (_is_patch_call(receiver) or ast.unparse(receiver) in patchers):
                    continue
                after = ast.unparse(block[index + 1]) if index + 1 < len(block) else ""
                if not stopall and "addCleanup(%s.stop)" % ast.unparse(receiver) not in after:
                    found.append(stmt.lineno)
            for field in ("body", "orelse", "finalbody"):
                inner = getattr(stmt, field, None)
                if inner and not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef,
                                                   ast.ClassDef)):
                    stopall = walk_block(inner, patchers, stopall)
        return stopall

    for func in ast.walk(tree):
        if isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            walk_block(func.body, set(), False)
    return sorted(set(found))


class AStartedPatchIsUndoneWhenWhatFollowsRaises(unittest.TestCase):
    """tearDown never runs after a failed setUp, so a started patch needs a cleanup to stop it."""

    def test_no_test_module_leaves_a_started_patch_running(self):
        offences = []
        for name, tree in EveryTestModuleArmsTheSandbox._modules(self).items():
            offences.extend("%s.py:%d" % (name, line) for line in _starts_left_running(tree))
        self.assertEqual(
            [], offences,
            "a patch started with no cleanup to stop it: if setUp then fails, the patch "
            "stays on for every later test (one moved import once failed 821): %s" % offences)

    def test_the_scan_tells_a_leak_from_the_two_safe_shapes(self):
        """Tests the check itself: a scan that matches nothing passes everything."""
        leak = ("def setUp(self):\n    self.p = patch('a.B')\n    self.b = self.p.start()\n"
                "    self.q = patch('a.C')\n    self.q.start()\n")
        stopall = ("def setUp(self):\n    self.addCleanup(patch.stopall)\n"
                   "    self.p = patch('a.B')\n    self.p.start()\n")
        paired = ("def setUp(self):\n    p = mock.patch.object(a, 'b')\n    p.start()\n"
                  "    self.addCleanup(p.stop)\n    t = threading.Thread()\n    t.start()\n")
        self.assertEqual([3, 5], _starts_left_running(ast.parse(leak)))
        self.assertEqual([], _starts_left_running(ast.parse(stopall)))
        self.assertEqual([], _starts_left_running(ast.parse(paired)))


class TheSuiteRunsOnTheProductionBuild(unittest.TestCase):
    """`amaze_houdini`: the LOWEST build of the newest major - production, with a daily above it."""

    def _pick(self, *roots):
        resolver = os.path.join(REPO, "tools", "houdini-env.sh")
        fake = " ".join("'%s'" % root for root in roots)
        script = (". '%s'\namaze_houdini_roots() { [ -z \"%s\" ] || printf '%%s\\n' %s; }\n"
                  "amaze_houdini\n" % (resolver, fake, fake))
        result = subprocess.run([test_support.bash(), "-c", script],
                                capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        return result.stdout.strip()

    def test_production_runs_and_the_daily_above_it_does_not(self):
        self.assertEqual("/A/Houdini22.0.100",
                         self._pick("/A/Houdini22.0.100", "/A/Houdini22.0.200"))

    def test_an_older_major_beside_them_is_not_run(self):
        self.assertEqual("/A/Houdini22.0.100", self._pick(
            "/A/Houdini21.0.300", "/A/Houdini22.0.100", "/A/Houdini22.0.200"))

    def test_one_install_is_the_one_run(self):
        self.assertEqual("/A/Houdini22.0.200", self._pick("/A/Houdini22.0.200"))

    def test_every_platform_spelling_names_its_major(self):
        windows = "C:/Program Files/Side Effects Software/Houdini %s"
        self.assertEqual(windows % "22.0.100", self._pick(
            windows % "21.0.300", windows % "22.0.100", windows % "22.0.200"))
        mac = "/Applications/Houdini/Houdini%s/Frameworks/Houdini.framework/Versions/Current/Resources"
        self.assertEqual(mac % "22.0.100",
                         self._pick(mac % "21.0.300", mac % "22.0.100", mac % "22.0.200"))
        self.assertEqual("/opt/hfs22.0.100",
                         self._pick("/opt/hfs21.0.300", "/opt/hfs22.0.100", "/opt/hfs22.0"))

    def test_no_install_returns_nothing(self):
        self.assertEqual("", self._pick())

    def test_no_runner_still_requests_the_newest(self):
        """Only the resolver picks the build; a caller asking for the newest would bypass it."""
        callers = [os.path.join("tools", name) for name in os.listdir(os.path.join(REPO, "tools"))
                   if name.endswith(".sh")]
        callers += [os.path.join("tools", "git-hooks", "pre-push"), RUNNER_REL]
        for relative in callers:
            with open(os.path.join(REPO, relative), encoding="utf-8") as handle:
                self.assertNotIn("amaze_newest_houdini", handle.read(), relative)


class EveryToolSourcesHoudiniEnv(unittest.TestCase):
    """Every `tools/*.sh` using hython sources houdini-env.sh; two known-bad commands are banned."""

    def test_no_tool_contains_the_banned_commands(self):
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
                "%s: GNU/MSYS mktemp rejects -t with no X's - the "
                "script fails on its first line on Windows" % name)
            self.assertNotIn(
                "ls -d /Applications", text,
                "%s has its own mac-only Houdini lookup besides the "
                "shared resolver" % name)
            if "hython" in text and name != "houdini-env.sh":
                self.assertIn(
                    "houdini-env.sh", text,
                    "%s uses hython without sourcing the "
                    "resolver" % name)
        self.assertGreaterEqual(checked, 3,    # houdini-env, run-tests, sync-install
                                "the tools directory scan found almost nothing")


if __name__ == "__main__":
    unittest.main()
