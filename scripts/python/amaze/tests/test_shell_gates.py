"""Gate tests check printed text and an end marker, not exit status alone. ▸p/gate-fixture-safety"""

import os
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
        env.update(self.git_env)
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
        temp = os.path.realpath(tempfile.gettempdir())
        self.assertTrue(os.path.realpath(env["AMAZE"]).startswith(temp),
                        "the fixture's install is outside the temp folder, so a sync would "
                        "write over the real install: %s" % env["AMAZE"])
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


class SyncInstallGateTest(GateFixture):

    def test_gt20_an_uncommitted_file_stops_the_sync_before_anything_is_copied(self):
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

    def test_gt21_a_scratch_pointing_at_the_real_install_stops_the_sync(self):
        """A typo must not point the sabotage test at the real install this script protects."""
        _write(os.path.join(self.repo, "scripts", "python", "amaze",
                            "stray.py"), "# sabotaged\n")

        result = self.sync("green", AMAZE_SCRATCH_INSTALL=self.install)

        self.assertEqual(result.returncode, 1, self.both(result))
        self.assertIn("REAL install", self.both(result))

    def test_gt22_a_missing_install_stops_the_sync_before_anything_is_copied(self):
        """A missing `$AMAZE` folder stops at the check; empty is never run: it means the real install."""
        missing = os.path.join(self.tmp, "not_an_install")
        result = self.sync("green", AMAZE=missing)
        self.assertEqual(result.returncode, 1, self.both(result))
        self.assertIn("cannot find the install", result.stderr)
        self.assertFalse(os.path.exists(missing))
        self.assertEqual(self.suite_calls(), [])

    def test_gt23_an_install_that_holds_a_newer_version_is_left_as_it_is(self):
        """Every machine shares the install, so one that is behind must not copy over it."""
        self._versions(checkout="1.35.1", installed="1.36.0")

        result = self.sync("green")

        self.assertEqual(result.returncode, 3, self.both(result))
        self.assertIn("the install holds Amaze 1.36.0", result.stderr)
        self.assertIn("this checkout is 1.35.1", result.stderr)
        self.assertEqual("1.36.0", self._installed_version())
        self.assertFalse(os.path.exists(os.path.join(self.install, "OPmenu.xml")),
                         "it refused and copied to the install anyway")

    def test_gt24_newer_is_read_as_numbers_and_the_same_or_an_older_install_is_copied(self):
        self._versions(checkout="1.9.12", installed="1.10.0")    # as text, "1.9.12" sorts last
        self.assertEqual(3, self.sync("green").returncode, "1.10.0 was read as older than 1.9.12")
        for installed in ("1.9.12", "1.9.2", "1.8.40"):
            with self.subTest(installed=installed):
                self._install_holds(installed)
                result = self.sync("green")
                self.assertEqual(result.returncode, 0, self.both(result))
                self.assertReachedEnd(result, SYNC_END)
                self.assertEqual("1.9.12", self._installed_version())

    def test_gt25_an_older_build_goes_over_a_newer_one_only_when_that_version_is_named(self):
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

    def test_gt31_the_process_gate_runs_first_and_its_failure_stops_the_push(self):
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

    def test_gt32_a_missing_process_gate_fails_closed(self):
        empty = os.path.join(self.tmp, "no-hooks")
        os.makedirs(empty)
        self._commit(os.path.join("scripts", "python", "amaze", "widget.py"))
        result = self.push("green", AMAZE_PRIVATE_HOOKS=empty)
        self.assertNotEqual(result.returncode, 0, self.both(result))
        self.assertIn("maintainer checks are not installed", self.both(result))
        self.assertEqual([], self.suite_calls(),
                         "a missing gate must refuse, not pass silently")

    def test_gt33_red_suite_stops_the_push_and_names_the_failures(self):
        self._commit(os.path.join("scripts", "python", "amaze", "widget.py"))
        result = self.push("red")
        self.assertEqual(result.returncode, 1, self.both(result))
        self.assertIn("PUSH REFUSED", result.stderr)
        self.assertIn("FAIL: test_tile_is_composed", result.stderr)
        self.assertNotIn(PUSH_END, result.stdout)
        self.assertReachedEnd(result, PUSH_RED_END)

    def test_gt34_amaze_skip_tests_needs_the_sha_being_pushed(self):
        """Not a boolean - a boolean gets exported once in a shell profile and disables the gate forever."""
        self._commit(os.path.join("scripts", "python", "amaze", "widget.py"))
        head = self._git("rev-parse", "HEAD")
        result = self.push("crash", AMAZE_SKIP_TESTS=head)
        self.assertEqual(result.returncode, 0, self.both(result))
        self.assertIn("AMAZE_SKIP_TESTS", result.stderr)
        self.assertEqual(self.suite_calls(), [])


class TargetedRunTest(unittest.TestCase):
    """`start_test.sh` refuses a name that is not a test module before it looks for Houdini."""

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

    def test_gt57_a_name_that_is_not_a_module_exits_with_2(self):
        for args in (("test_no_such_module_here",),
                     ("--isolated", "test_no_such_module_here")):    # a check reading only $1 misses it
            with self.subTest(args=args):
                result = self._run(*args)
                self.assertEqual(2, result.returncode, result.stderr)
                self.assertIn("no such test module", result.stderr)


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

    def test_gt58_production_runs_and_the_daily_above_it_does_not(self):
        self.assertEqual("/A/Houdini22.0.100",
                         self._pick("/A/Houdini22.0.100", "/A/Houdini22.0.200"))

    def test_gt59_an_older_major_beside_them_is_not_run(self):
        self.assertEqual("/A/Houdini22.0.100", self._pick(
            "/A/Houdini21.0.300", "/A/Houdini22.0.100", "/A/Houdini22.0.200"))

    def test_gt60_one_install_is_the_one_run(self):
        self.assertEqual("/A/Houdini22.0.200", self._pick("/A/Houdini22.0.200"))

    def test_gt61_every_platform_spelling_names_its_major(self):
        windows = "C:/Program Files/Side Effects Software/Houdini %s"
        self.assertEqual(windows % "22.0.100", self._pick(
            windows % "21.0.300", windows % "22.0.100", windows % "22.0.200"))
        mac = "/Applications/Houdini/Houdini%s/Frameworks/Houdini.framework/Versions/Current/Resources"
        self.assertEqual(mac % "22.0.100",
                         self._pick(mac % "21.0.300", mac % "22.0.100", mac % "22.0.200"))
        self.assertEqual("/opt/hfs22.0.100",
                         self._pick("/opt/hfs21.0.300", "/opt/hfs22.0.100", "/opt/hfs22.0"))

    def test_gt62_no_install_returns_nothing(self):
        self.assertEqual("", self._pick())


if __name__ == "__main__":
    unittest.main()
