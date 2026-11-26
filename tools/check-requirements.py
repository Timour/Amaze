#!/usr/bin/env python3
"""Refuses a test that proves no listed requirement, a second test for one, or a broken code rule."""
import ast
import importlib.util
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LISTS = os.path.join(ROOT, "docs", "requirements")
TESTS = os.path.join(ROOT, "scripts", "python", "amaze", "tests")
LEVELS = ("Catastrophe", "Severe", "Wrong output")
LINE = re.compile(r"^- ([A-Z]{2,3})-(\d{2}) (%s): \S" % "|".join(LEVELS))
NAMED = re.compile(r"^test_([a-z]{2,3})(\d{2})_")


def requirements() -> tuple:
    """({id: (level, list file)}, [problems]) from every list."""
    found, problems = {}, []
    for name in sorted(os.listdir(LISTS)) if os.path.isdir(LISTS) else ():
        if not name.endswith(".md"):
            continue
        with open(os.path.join(LISTS, name), encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                if not re.match(r"^- [A-Z]{2,3}-\d", line):
                    continue
                match = LINE.match(line)
                if match is None:
                    problems.append("%s:%d is no `- XX-NN Level: text` line" % (name, number))
                    continue
                rid = "%s-%s" % match.group(1, 2)
                if rid in found:
                    problems.append("%s:%d lists %s again (first in %s)" % (
                        name, number, rid, found[rid][1]))
                found[rid] = (match.group(3), name)
    return found, problems


def tests() -> list:
    """(file, `Class.test`, requirement id or "") of every test method in the suite."""
    found = []
    for name in sorted(os.listdir(TESTS)):
        if not (name.startswith("test_") and name.endswith(".py")):
            continue
        with open(os.path.join(TESTS, name), encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), name)
        for owner in (node for node in tree.body if isinstance(node, ast.ClassDef)):
            for node in owner.body:
                if isinstance(node, ast.FunctionDef) and node.name.startswith("test"):
                    match = NAMED.match(node.name)
                    rid = "%s-%s" % (match.group(1).upper(), match.group(2)) if match else ""
                    found.append((name, "%s.%s" % (owner.name, node.name), rid))
    return found


def modules() -> list:
    """The test modules that hold the requirements' tests."""
    return sorted({name[:-3] for name, _test, rid in tests() if rid})


def at_every_push() -> list:
    """The ids of the tests proving a Catastrophe or Severe requirement, which every push runs."""
    listed, _problems = requirements()
    return ["%s.%s" % (name[:-3], test) for name, test, rid in tests()
            if listed.get(rid, ("",))[0] in ("Catastrophe", "Severe")]


def code_rules() -> list:
    """What breaks a rule of `check-code.py`, loaded only here so its importers need no copy."""
    spec = importlib.util.spec_from_file_location(
        "check_code", os.path.join(ROOT, "tools", "check-code.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.refusals()


def main() -> int:
    listed, refused = requirements()
    refused += code_rules()
    proved, files, every = {}, {}, tests()
    for name, test, rid in every:
        files.setdefault(name, set()).add(bool(rid))
        if not rid:
            continue
        if rid not in listed:
            refused.append("%s ▸ %s proves %s, which no list holds" % (name, test, rid))
        elif rid in proved:
            refused.append("%s ▸ %s is a second test for %s (first: %s)" % (
                name, test, rid, proved[rid]))
        else:
            proved[rid] = "%s ▸ %s" % (name, test)
    refused += ["%s mixes tests with and without a requirement id" % name
                for name, kinds in sorted(files.items()) if kinds == {True, False}]
    untested = sorted(rid for rid, (level, _list) in listed.items()
                      if level != "Wrong output" and rid not in proved)
    waiting = ["%s %s" % (name[:-3], test) for name, test, rid in every if not rid]
    for line in refused:
        print("requirements: REFUSED - " + line, file=sys.stderr)
    for one in waiting if "--cut" in sys.argv[1:] else ():    # names each test proving none
        print("requirements: no requirement - " + one)
    if untested:
        print("requirements: Catastrophe or Severe with no test: " + ", ".join(untested))
    print("requirements: %d listed, %d proved by a test, %d tests still without one (the cut)"
          % (len(listed), len(proved), len(waiting)))
    return 1 if refused else 0


if __name__ == "__main__":
    sys.exit(main())
