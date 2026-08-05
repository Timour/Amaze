"""Where can a long method be split without moving any state?

Splitting a method is safe exactly where no LOCAL VARIABLE crosses the
boundary: everything before the cut can move into its own method,
because nothing after it reads what that code produced. This walks a
method's top-level statements and reports those boundaries.

    hython tests/split_points.py panel/panel.py init_ui
    hython tests/split_points.py panel/panel.py init_ui --allow central_layout

`--allow NAME` answers the follow-up question: "what would promoting
this local to an attribute buy me?" - it reports the cuts that would
open up if NAME no longer counted as crossing.

**Module-level names are not locals.** Imports, module constants and
classes are visible inside any method, so they never block a split -
counting them (as the first version of this analysis did) makes a
method look hopelessly entangled and hides the one local that is
actually pinning it together. For init_ui that was `central_layout`:
excluding the imports took the largest unsplittable block from 278
lines to 62.

**What this CANNOT see, and it is a big exclusion:** `self` is treated
as always-available, so ordering constraints expressed through
attributes are invisible. In a method that is almost entirely
`self.*` mutation - which init_ui is - that covers most of the real
constraints: an index saved on self and consumed later, a widget that
must be added to a layout before another is inserted at position 0, a
connect that must follow the widget it binds. It reports where no
LOCAL crosses; it does not report where the ORDER matters.

Worse, taking its "promote this local to an attribute" advice converts
a constraint it CAN see into one it cannot. That is a real trade, not
a free win: it is only worth making when the resulting attribute is
genuinely panel-wide state (central_layout was; a filter row or a
short-lived palette is not).

The cuts this finds are therefore necessary, not sufficient. Pair it
with tests/ui_snapshot.py, which compares the constructed panel before
and after - and keep the cuts small enough to read.
"""

import argparse
import ast
import builtins
import os
import sys


def module_level_names(tree) -> set:
    """Every name a method can use without it being a local: imports,
    module constants, module-level defs and classes, and builtins."""
    names = set(dir(builtins))
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.ClassDef)):
            names.add(node.name)
    return names


def analyse(path: str, method: str, allow=()):
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    skip = module_level_names(tree)
    target = next((n for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and n.name == method), None)
    if target is None:
        raise SystemExit("no method named %s in %s" % (method, path))

    def used(node, ctx):
        return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)
                and isinstance(n.ctx, ctx) and n.id not in skip}

    stmts = [{
        "line": s.lineno,
        "end": getattr(s, "end_lineno", s.lineno),
        "defs": used(s, ast.Store),
        "uses": used(s, ast.Load),
        "src": ast.unparse(s).splitlines()[0][:60],
    } for s in target.body]

    allowed = {"self"} | set(allow)
    cuts, crossing = [], {}
    for i in range(len(stmts) - 1):
        defined = set().union(*[s["defs"] for s in stmts[:i + 1]])
        later = set().union(*[s["uses"] for s in stmts[i + 1:]])
        blockers = (defined & later) - allowed
        if blockers:
            for name in blockers:
                crossing[name] = crossing.get(name, 0) + 1
        else:
            cuts.append(i)

    blocks, prev = [], target.lineno
    for i in cuts:
        blocks.append((prev, stmts[i]["end"]))
        prev = stmts[i]["end"]
    blocks.append((prev, target.end_lineno))
    return target, stmts, cuts, blocks, crossing


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("method")
    parser.add_argument("--allow", nargs="*", default=[],
                        help="locals to treat as if they were attributes")
    args = parser.parse_args()

    path = args.path
    if not os.path.exists(path):
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), args.path)
    target, stmts, cuts, blocks, crossing = analyse(
        path, args.method, args.allow)

    print("%s.%s: %d lines, %d top-level statements"
          % (os.path.basename(path), args.method,
             target.end_lineno - target.lineno, len(stmts)))
    if args.allow:
        print("treating as attributes: %s" % ", ".join(args.allow))
    print("clean cut points: %d of %d" % (len(cuts), max(len(stmts) - 1, 0)))

    print("\nblocks between clean cuts (the pieces you could extract):")
    for start, end in sorted(blocks, key=lambda b: -(b[1] - b[0]))[:8]:
        first = next((s["src"] for s in stmts if s["line"] >= start), "")
        print("   lines %5d-%5d  %4d  %s" % (start, end, end - start, first))

    if crossing:
        print("\nlocals that block cuts (promote these to attributes to "
              "open the method up):")
        for name, count in sorted(crossing.items(), key=lambda kv: -kv[1]):
            print("   %-24s blocks %d boundaries" % (name, count))
    else:
        print("\nno local blocks any boundary - every statement is a "
              "candidate cut.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
