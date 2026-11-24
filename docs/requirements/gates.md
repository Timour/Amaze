# Push and install gates: requirements

What the scripts that guard a push and the install must do: `tools/sync-install.sh`, the `pre-push`
hook in `tools/git-hooks`, `tools/run-tests.sh`, `scripts/python/amaze/tests/start_test.sh`, the
push's test selection (`tools/select-tests.py` with `tests/impact_map.py`), the dead-cover check
(`tests/check_dead_cover.py`) and the Houdini lookup in `tools/houdini-env.sh`. They guard the
maintainer's install and pushes, not a user's library, and what they let through is undone by a
new sync or a revert, so every line is Wrong output; their tests run when `tools/` changes.
The levels and the rules for tests are in the [README](README.md).

## Wrong output

- GT-20 Wrong output: A sync to the install is refused while the checkout has an uncommitted or untracked file; it names the file and copies nothing.
- GT-21 Wrong output: A scratch sync is refused when its destination is the real install.
- GT-22 Wrong output: A sync to an install folder that does not exist is refused before anything is copied.
- GT-23 Wrong output: A sync leaves an install holding a newer Amaze as it is, names both versions and exits with 3.
- GT-24 Wrong output: Versions compare as numbers, so 1.10.0 is newer than 1.9.12; an install of the same or an older version is copied over.
- GT-25 Wrong output: An older checkout goes over a newer install only when `AMAZE_REPLACE_INSTALLED` names the installed version.
- GT-26 Wrong output: A sync copies the code, the menus and the shelf to the install, runs no tests, and prints its last line.
- GT-27 Wrong output: A scratch sync copies the working tree as it is, uncommitted files included, and leaves the real install untouched.
- GT-28 Wrong output: A scratch destination that holds files and no scratch marker is refused and left as it is.
- GT-29 Wrong output: A committed change syncs without being pushed.
- GT-30 Wrong output: A sync in a fresh clone sets `core.hooksPath` to the repository's hooks, and says so only the first time.
- GT-31 Wrong output: The maintainer's checks run before the tests; when they refuse, the push is refused and no test runs.
- GT-32 Wrong output: When the maintainer's checks cannot be found, the push is refused.
- GT-33 Wrong output: A push whose tests fail is refused, and the refusal names the failing tests.
- GT-34 Wrong output: `AMAZE_SKIP_TESTS` set to the commit being pushed skips the tests.
- GT-35 Wrong output: `AMAZE_SKIP_TESTS` set to any other commit skips nothing.
- GT-36 Wrong output: A push whose tests pass goes through, says how many ran, and prints its last line.
- GT-37 Wrong output: A push is refused when its test run crashes, runs no test, prints nothing, or writes to the real debug log.
- GT-38 Wrong output: A push runs only the tests its change reaches, and that run leaves the install as it is.
- GT-39 Wrong output: A push whose selected tests fail is refused.
- GT-40 Wrong output: A push that reaches no test runs none and goes through.
- GT-41 Wrong output: A new patch version runs only the tests its change reaches.
- GT-42 Wrong output: A new minor version runs the whole suite.
- GT-43 Wrong output: A new major version runs the whole suite.
- GT-44 Wrong output: A change the map cannot answer, such as a new code file, runs the whole suite.
- GT-45 Wrong output: With no map, a push runs the whole suite.
- GT-46 Wrong output: Uncommitted files run the whole suite.
- GT-47 Wrong output: A pushed ref that is not the checked-out commit runs the whole suite.
- GT-48 Wrong output: A new branch runs the whole suite.
- GT-49 Wrong output: A push with no refs runs the whole suite.
- GT-50 Wrong output: A selection that fails runs the whole suite.
- GT-51 Wrong output: A whole-suite push tests one Houdini, even when several are installed.
- GT-52 Wrong output: `run-tests.sh` syncs to a scratch install, then runs the suite once.
- GT-53 Wrong output: A green whole run leaves an install holding a newer Amaze as it is, and stays green.
- GT-54 Wrong output: `run-tests.sh` passes its arguments to the runner.
- GT-55 Wrong output: A failing suite makes `run-tests.sh` fail.
- GT-56 Wrong output: `run-tests.sh --all-versions` runs every Houdini installed and fails on a test skipped on all of them.
- GT-57 Wrong output: A test module name that does not exist is refused with exit 2, never run as an empty subset.
- GT-58 Wrong output: The suite runs on the lowest build of the newest Houdini installed, never on a daily build above it.
- GT-59 Wrong output: An older major Houdini installed beside it is never chosen.
- GT-60 Wrong output: With one Houdini installed, that one is chosen.
- GT-61 Wrong output: The choice reads the version from macOS, Windows and Linux install paths alike.
- GT-62 Wrong output: With no Houdini installed, none is chosen.
- GT-63 Wrong output: A test skipped on only some Houdini builds is not reported as dead cover.
- GT-64 Wrong output: A test skipped on every Houdini build is reported, with each build's name and reason.
- GT-65 Wrong output: A missing, unreadable or empty report, or a single one, ends the dead-cover check with exit 2.
- GT-66 Wrong output: A report names its Houdini by the version folder, or as the production build.
- GT-67 Wrong output: A run's report holds its skipped tests, sorted, with their reasons and the number of tests run.
- GT-68 Wrong output: The dead-cover check reads the reports a run writes.
- GT-69 Wrong output: An edit to a comment or a docstring changes no code hash.
- GT-70 Wrong output: An edit changes only its own hash: a def, a module-level name, an inner def, an import, or a call made on import.
- GT-71 Wrong output: A lambda counts as part of the def it is in.
- GT-72 Wrong output: A changed def picks the tests that ran it and those that read its file.
- GT-73 Wrong output: A changed comment picks only the tests that read the file.
- GT-74 Wrong output: A changed module-level name picks every def that uses it, in any file.
- GT-75 Wrong output: A changed import picks only the defs of its own file that use it.
- GT-76 Wrong output: A changed test module picks the tests whose code changed, and the whole module when a test is added.
- GT-77 Wrong output: A def run while the suite loads picks the tests that use what it built; run by a call made on import, it runs the whole suite.
- GT-78 Wrong output: A changed file picks the tests that read it, a new file those that listed its folder, and a change in `tools/` the gate tests.
- GT-79 Wrong output: A change the map cannot place runs the whole suite: code run on import, a file no test reads, code that does not parse, new code, the runner, or no map.
- GT-80 Wrong output: The selection reads the suite's modules from `start_test.sh`, each once.
- GT-81 Wrong output: The map covers the files git tracks, and no bytecode cache.
- GT-82 Wrong output: A def run by two test modules is charged to both.
- GT-83 Wrong output: A file a test reads is charged to it; a read by an import or a traceback, or after the recorder stops, is not.
- GT-84 Wrong output: A def run while the suite loads is charged to the statement that ran it.
- GT-85 Wrong output: The map is written whole, with what ran while the suite loaded, and without defs a file no longer has.
