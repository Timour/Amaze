"""Where a long method can be split without moving state - the boundaries no LOCAL variable crosses. ITS CUTS ARE NECESSARY, NEVER SUFFICIENT: `self` counts as always-available, so an ordering constraint carried through an attribute is invisible to it, and promoting a local to an attribute converts a constraint it CAN see into one it cannot. Pair it with ui_snapshot.  `hython tests/split_points.py panel/panel.py init_ui [--allow NAME]`  ▸archive/split_points.py"""

import argparse
import ast
import builtins
import os
import sys


def module_level_names(tree) -> set:
    """Every name a method can use without it being a local - imports, module constants, module-level defs and classes, and builtins."""
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
