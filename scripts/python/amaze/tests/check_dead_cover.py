#!/usr/bin/env python3
"""Which tests skipped on EVERY Houdini the suite ran against?

    check_dead_cover.py <report.json> <report.json> [...]

A test that skips everywhere protects nothing and reads as coverage.
`test_building_a_redshift_scene_restores_the_selection` was one for its
whole life - it guarded on Redshift AND needed a GUI, so it skipped
under H22 (no Redshift) and errored under H21 (no `hou.ui`). The
regression it was written to catch was live again by the time it first
ran. Nothing reported that, because the suite says `skipped=3` and
never says WHICH three, and each run's count looks reasonable alone.

WHY THIS IS A STEP OVER TWO RUNS AND NOT A TEST INSIDE ONE. A single
run cannot know it. Skipping under H22 is correct behaviour for a
Redshift test; it only becomes dead cover once H21 skipped it too. The
question needs both results in hand, so it lives where both exist -
`run-tests.sh --all-versions`, after the loop.

REFUSING IS A RESULT. A report that is missing, unreadable, or says
`testsRun: 0` means that run did not finish - Houdini's crash handler
exits 0 (practice.md), so a crashed suite leaves no trace in the status.
Comparing the surviving runs anyway would name tests as dead-everywhere
on the strength of one version, which is the same false-green this
check exists to remove. So it stops and says so.

Exit 0 = no dead cover, 1 = dead cover (named), 2 = cannot tell.
"""

import json
import os
import sys

#: Two runs is the minimum that can answer the question at all.
MINIMUM_REPORTS = 2


def load(path: str):
    """One run's report, or a sentence saying why there is not one."""
    if not os.path.exists(path):
        return None, ("no report at %s - that run never reached the end "
                      "of run_suite.py, so it crashed or was killed" % path)
    try:
        with open(path, encoding="utf-8") as handle:
            report = json.load(handle)
    except (ValueError, OSError) as exc:
        return None, "unreadable report at %s (%s)" % (path, exc)
    if not isinstance(report, dict) or "skipped" not in report:
        return None, "report at %s is not a skip report" % path
    # A run that executed nothing cannot vouch for anything. This is the
    # `Ran 0 tests` check that catches a crashed suite, in the one place
    # that would otherwise read the crash as "skipped nothing".
    if not report.get("testsRun"):
        return None, ("report at %s ran 0 tests - the suite died before "
                      "it could skip anything" % path)
    return report, ""


def host_of(report) -> str:
    """A name for the install a report came from, for the message."""
    houdini = (report.get("houdini") or "").rstrip("/")
    if not houdini:
        return "(newest install)"
    # .../Houdini21.0.729/Frameworks/... - the version directory is the
    # only readable part, and it is what a person would say out loud.
    for part in houdini.split("/"):
        if part.startswith("Houdini") and any(c.isdigit() for c in part):
            return part
    return houdini


def dead_everywhere(reports):
    """Test ids that skipped in EVERY report, with each run's reason.

    An INTERSECTION, which is the whole point: skipping on one host is
    ordinary and correct, and only skipping on all of them is dead."""
    per_run = []
    for report in reports:
        per_run.append({test_id: reason for test_id, reason in report["skipped"]})
    shared = set(per_run[0])
    for skips in per_run[1:]:
        shared &= set(skips)
    return sorted(
        (test_id, [(host_of(report), skips[test_id])
                   for report, skips in zip(reports, per_run)])
        for test_id in shared
    )


def main(argv) -> int:
    if len(argv) < MINIMUM_REPORTS:
        print("check_dead_cover.py: need at least %d reports, got %d - one "
              "run cannot tell dead cover from a correct skip"
              % (MINIMUM_REPORTS, len(argv)), file=sys.stderr)
        return 2

    reports, problems = [], []
    for path in argv:
        report, problem = load(path)
        if problem:
            problems.append(problem)
        else:
            reports.append(report)

    if problems:
        print("DEAD-COVER CHECK CANNOT RUN:", file=sys.stderr)
        for problem in problems:
            print("  %s" % problem, file=sys.stderr)
        print("  Fix the run before believing the suite - a check that "
              "silently skips itself is the thing it is here to stop.",
              file=sys.stderr)
        return 2

    hosts = ", ".join(host_of(report) for report in reports)
    dead = dead_everywhere(reports)
    if not dead:
        print("dead-cover check: no test skipped on all of %s" % hosts)
        return 0

    print("DEAD COVER - %d test(s) skipped on EVERY host (%s):"
          % (len(dead), hosts), file=sys.stderr)
    for test_id, reasons in dead:
        print("  %s" % test_id, file=sys.stderr)
        for host, reason in reasons:
            print("      %-22s %s" % (host, reason or "(no reason given)"),
                  file=sys.stderr)
    print("  A test that skips everywhere protects nothing and reads as "
          "coverage. Fix its condition, or delete it.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
