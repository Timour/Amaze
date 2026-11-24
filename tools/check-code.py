#!/usr/bin/env python3
"""Refuses code that breaks a rule no test run would show; check-requirements.py runs it."""
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE = os.path.join(ROOT, "scripts", "python", "amaze")
TESTS = os.path.join(PACKAGE, "tests")
NOT_SHIPPED = {"tests", "res", "ui", "__pycache__"}
OFFSCREEN = 'os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")'

ALLOWED = {    # the layers each layer may use: all below it, but models and houdini not each other
    "base": {"base"},
    "library": {"base", "library"},
    "formats": {"base", "library", "formats"},
    "models": {"base", "library", "formats", "models"},
    "houdini": {"base", "library", "formats", "houdini"},
    "actions": {"base", "library", "formats", "models", "houdini", "actions"},
    "interface": {"base", "library", "formats", "models", "houdini", "actions", "interface"},
}
PACKAGE_LAYER = {    # every module under these packages ▸m/layer-plan
    "panel": "interface", "dialogs": "interface", "utils": "interface", "pane": "interface",
    "sections": "interface", "qml": "interface",
    "render": "houdini", "preview": "houdini", "prefs": "library", "actions": "actions",
}
MODULE_LAYER = {    # one row per module in core/, helpers/ and the top level
    "amaze": "base", "branding": "base", "messages": "base", "tooltips": "base",
    "amazetheme": "base", "core": "base", "helpers": "base", "core.debug": "base",
    "helpers.hostos": "base", "core.renderers": "base", "core.library_files": "base",
    "core.section_list": "base", "helpers.wording": "base", "core.workers": "base",
    "core.guard": "library", "core.documents": "library", "core.library_db": "library",
    "core.library_settings": "library", "core.material": "library", "core.locations": "library",
    "core.notes": "library", "core.users": "library", "core.versions": "library",
    "core.captures": "library", "core.library_policy": "library", "core.file_moves": "library",
    "core.tile_icons": "library", "core.texstore": "library", "core.check_library": "library",
    "core.asset_files": "library", "core.asset_record": "library",
    "core.library_conversion": "library", "core.layout_conversion": "library",
    "core.packages": "formats", "core.addons": "formats", "core.matx_sources": "formats",
    "core.matx_usd": "formats", "core.bsdf_reader": "formats", "core.conversion": "formats",
    "core.geo_library": "formats", "core.scene_files": "formats", "core.material_files": "formats",
    "core.file_info": "formats", "core.image_preview": "formats",
    "core.library": "models", "core.category": "models", "core.cop_library": "models",
    "core.code_library": "models", "core.gradient_library": "models",
    "core.file_library": "models", "core.folders": "models", "core.texture_library": "models",
    "core.matx_library": "models", "core.grid_engine": "models", "core.grid_proxy": "models",
    "core.sidebar_model": "models", "core.multifilterproxy_model": "models",
    "core.model_registry": "models", "core.thumbnails": "models", "core.grid_columns": "models",
    "core.matx_icon": "models", "helpers.vex_syntax": "models",
    "core.dragengine": "houdini", "core.lop_assign": "houdini", "core.scene_captures": "houdini",
    "core.gallery_import": "houdini", "core.matx_translate": "houdini",
    "core.matx_import": "houdini", "helpers.helpers": "houdini", "helpers.hostver": "houdini",
    "core.updater": "actions",
    "helpers.ui_helpers": "interface", "helpers.theme": "interface",
}
LAYER_BREAKS = {    # accepted on purpose; the list only shrinks
    "core/matx_icon.py imports helpers/ui_helpers.py",
    "core/texstore.py uses hou",
    "core/tile_icons.py imports helpers/ui_helpers.py",
    "render/nodes.py talks displayMessage x5",
    "render/thumbs.py talks displayMessage x3",
}
HOUDINI = {"hou", "husd", "hutil", "toolutils", "loputils", "voptoolutils", "nodegraphutils",
           "hdefereval", "stateutils", "viewerstate", "soptoolutils", "objecttoolutils"}
HOUDINI_LIBS = {"pxr", "MaterialX", "OpenImageIO"}
UI_CALLS = {"displayMessage", "displayConfirmation", "displayCustomConfirmation", "readInput",
            "readMultiInput", "selectFile", "selectFromList", "selectFromTree", "selectColor",
            "selectNode", "selectMultipleNodes", "setStatusMessage"}
DIALOGS = {"displayMessage", "displayConfirmation", "displayCustomConfirmation",
           "selectFromList", "readInput", "readMultiInput"}
TEXT_KEYWORDS = {"text", "help", "buttons", "title", "message", "details", "details_label",
                 "column_header"}
INTERFACE = ("panel/", "pane/", "sections/", "dialogs/", "utils/")
PLACEHOLDER = re.compile(r"%[sdif]")
WORDED = re.compile(r"[A-Za-z]{3,}")
LONG = re.compile(r"(?m)^[ \t]*(?:#|//).{100,}|[ \t](?:#|(?<![:\w])//).{100,}"
                  r'|^[ \t]*["]{3}[^\n]{100,}')
SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def shipped() -> dict:
    """{module name, `amaze` for the package: (path under the package, tree, its nodes)}."""
    found = {}
    for folder, dirs, files in os.walk(PACKAGE):
        dirs[:] = sorted(d for d in dirs if d not in NOT_SHIPPED)
        for name in sorted(f for f in files if f.endswith(".py")):
            path = os.path.relpath(os.path.join(folder, name), PACKAGE).replace(os.sep, "/")
            dotted = path[:-3].replace("/", ".").replace(".__init__", "")
            with open(os.path.join(folder, name), encoding="utf-8") as handle:
                tree = ast.parse(handle.read())
            found["amaze" if dotted == "__init__" else dotted] = (path, tree, list(ast.walk(tree)))
    return found


def imports(name, code) -> set:
    """The absolute dotted names a module imports, relative imports resolved."""
    path, _tree, nodes = code[name]
    found = set()
    for node in nodes:
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = ("amaze." + name if name != "amaze" else "amaze").split(".")
                parts = parts if path.endswith("__init__.py") else parts[:-1]
                base = ".".join(parts[:len(parts) - node.level + 1] + ([base] if base else []))
            found.add(base)
            found.update("%s.%s" % (base, alias.name) for alias in node.names)
    return found


def amaze_target(dotted, code):
    """The Amaze module a dotted import names: its longest prefix that is a module."""
    parts = dotted.split(".")[1:]
    while parts and ".".join(parts) not in code:
        parts.pop()
    return ".".join(parts) if parts else ("amaze" if dotted == "amaze" else None)


def layer_of(name):
    return PACKAGE_LAYER.get(name.split(".")[0]) or MODULE_LAYER.get(name)


def outside_ok(layer, dotted) -> bool:
    """Whether a layer may use a library outside Amaze: Qt, Houdini's session or its libraries."""
    top = dotted.split(".")[0]
    if top in ("PySide6", "shiboken6"):
        if dotted.endswith(("QtWidgets", "QtUiTools")):
            return layer == "interface"
        return layer != "base" or dotted == "PySide6"
    if top in HOUDINI:
        return layer in ("houdini", "actions", "interface")
    return top not in HOUDINI_LIBS or layer in ("formats", "houdini", "actions", "interface")


def layers(code) -> list:
    """Each module uses only the layers below it, except the places LAYER_BREAKS accepts."""
    found = ["%s has no layer in MODULE_LAYER" % code[n][0] for n in code if not layer_of(n)]
    found += ["MODULE_LAYER names %s, which is gone" % n for n in MODULE_LAYER if n not in code]
    breaks = set()
    for name, (path, _tree, nodes) in code.items():
        layer = layer_of(name)
        if layer is None:
            continue
        for dotted in imports(name, code):
            target = amaze_target(dotted, code) if dotted.split(".")[0] == "amaze" else None
            if target and target != name and layer_of(target) not in ALLOWED[layer]:
                breaks.add("%s imports %s" % (path, code[target][0]))
            elif dotted.split(".")[0] != "amaze" and not outside_ok(layer, dotted):
                what = ".".join(dotted.split(".")[:2 if dotted.startswith("PySide6.") else 1])
                breaks.add("%s uses %s" % (path, what))
        talks = sorted(node.func.attr for node in nodes if isinstance(node, ast.Call)
                       and isinstance(node.func, ast.Attribute) and node.func.attr in UI_CALLS)
        if talks and layer != "interface":
            breaks.add("%s talks %s" % (path, ", ".join(
                "%s x%d" % (call, talks.count(call)) for call in sorted(set(talks)))))
    found += ["%s breaks the layer map" % line for line in sorted(breaks - LAYER_BREAKS)]
    return found + ["%s is fixed: take it out of LAYER_BREAKS" % line
                    for line in sorted(LAYER_BREAKS - breaks)]


def engine_widgets(code) -> list:
    """The pane engine and its sections, shared with the QML pane, reach no widget code."""
    uses = {name: {amaze_target(d, code) if d.split(".")[0] == "amaze" else d
                   for d in imports(name, code)} for name in code}
    widgets = {name for name, used in uses.items() if "PySide6.QtWidgets" in used}
    return ["%s imports %s" % (code[name][0], code[used][0] if used in code else used)
            for name in sorted(code) if name.split(".")[0] in ("pane", "sections")
            for used in sorted(filter(None, uses[name]))
            if used == "PySide6.QtWidgets" or used in widgets - {name}]


def preview_api(code) -> list:
    """Code outside the preview engine imports `amaze.preview`, never a module inside it."""
    return ["%s imports %s" % (path, dotted) for name, (path, _t, _n) in sorted(code.items())
            if not path.startswith("preview/")
            for dotted in sorted(imports(name, code)) if dotted.startswith("amaze.preview.")]


def host_checks(code) -> list:
    """Only hostver.py reads Houdini's version and only hostos.py tests the system."""
    found = []
    for path, _tree, nodes in code.values():
        for node in nodes:
            if not isinstance(node, ast.Attribute):
                continue
            owner = node.value.id if isinstance(node.value, ast.Name) else ""
            if node.attr == "applicationVersion" and path != "helpers/hostver.py":
                found.append("%s:%d reads the Houdini version" % (path, node.lineno))
            elif (owner, node.attr) in (("sys", "platform"), ("platform", "system")) \
                    and path != "helpers/hostos.py":
                found.append("%s:%d tests the system" % (path, node.lineno))
    return found


def binds(node) -> set:
    """The names one node binds in its scope."""
    if isinstance(node, ast.Import):
        return {(alias.asname or alias.name).split(".")[0] for alias in node.names}
    if isinstance(node, ast.ImportFrom):
        return {alias.asname or alias.name for alias in node.names}
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
        return {node.id}
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    if isinstance(node, ast.arg):
        return {node.arg}
    if isinstance(node, ast.Global):
        return set(node.names)
    return {node.name} if isinstance(node, ast.ExceptHandler) and node.name else set()


def own(scope, stop=SCOPES):
    """The nodes evaluated in `scope` itself, not inside a nested scope of a `stop` type."""
    args = getattr(scope, "args", None)
    pending = (scope.body if isinstance(scope.body, list) else [scope.body]) + ([
        a for a in args.posonlyargs + args.args + args.kwonlyargs + [args.vararg, args.kwarg]
        if a] if args else [])
    while pending:
        node = pending.pop()
        yield node
        if not isinstance(node, stop):
            pending += ast.iter_child_nodes(node)
        elif isinstance(node, ast.ClassDef):
            pending += node.decorator_list + node.bases + node.keywords
        else:
            pending += getattr(node, "decorator_list", []) + [
                d for d in node.args.defaults + node.args.kw_defaults if d is not None]


def unbound_names(code) -> list:
    """A module read in a scope that never imported it raises NameError only when it runs."""
    watched = set(sys.stdlib_module_names) | {path.rsplit("/", 1)[-1][:-3]
                                              for path, _tree, _nodes in code.values()}
    found = set()
    for path, tree, nodes in code.values():
        anywhere = set().union(*map(binds, nodes))
        module = set().union(*map(binds, own(tree, SCOPES + (ast.ClassDef,))))

        def visit(node, enclosing):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, SCOPES):
                    mine = list(own(child))
                    bound = enclosing | set().union(*map(binds, mine))
                    found.update("%s:%d reads %s and never imports it" % (path, n.lineno, n.id)
                                 for n in mine if isinstance(n, ast.Name)
                                 and isinstance(n.ctx, ast.Load) and n.id in watched
                                 and n.id not in module | bound)
                    visit(child, bound)
                    continue
                if not enclosing and isinstance(child, ast.Name) and isinstance(
                        child.ctx, ast.Load) and child.id in watched - anywhere:
                    found.add("%s:%d reads %s and never imports it" % (
                        path, child.lineno, child.id))
                visit(child, enclosing)

        visit(tree, frozenset())
    return sorted(found)


def defined_twice(code) -> list:
    """A second `def` of one name in a class or module replaces the first in silence."""
    found = []
    for path, _tree, nodes in code.values():
        for scope in (n for n in nodes if isinstance(n, (ast.Module, ast.ClassDef))):
            seen = set()
            for item in scope.body:
                if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) or any(
                        ast.unparse(d).endswith((".setter", ".deleter"))
                        for d in item.decorator_list):
                    continue
                if item.name in seen:
                    found.append("%s:%d defines %s again" % (path, item.lineno, item.name))
                seen.add(item.name)
    return found


def event_pumps(code) -> list:
    """A bare `processEvents()` lets a click re-enter the loop that pumps it."""
    return ["%s:%d pumps events with user input on" % (path, node.lineno)
            for path, _tree, nodes in code.values() for node in nodes
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "processEvents" and not node.args and not node.keywords]


def unowned_styles(code) -> list:
    """A style given to a widget is owned by nobody and crashed Houdini at quit. ▸r/no-proxystyle"""
    return ["%s:%d gives a widget a style" % (path, node.lineno)
            for path, _tree, nodes in code.values() for node in nodes
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "setStyle"
            and not ast.unparse(node.func.value).endswith("QApplication")]


def colour_pickers(code) -> list:
    """Only `pick_color` opens a colour picker: Houdini's under a Qt modal crashed Houdini."""
    return ["%s:%d opens a colour picker of its own" % (path, node.lineno)
            for path, _tree, nodes in code.values() if path != "helpers/ui_helpers.py"
            for node in nodes
            if (isinstance(node, ast.Attribute) and node.attr in ("QColorDialog", "selectColor"))
            or (isinstance(node, ast.alias) and node.name == "QColorDialog")]


def text_of(module) -> dict:
    """{name: value} of what messages.py or tooltips.py binds at its top."""
    found = {}
    for node in module.body:
        for name in binds(node) if not isinstance(node, ast.Assign) else ():
            found[name] = None
        if isinstance(node, ast.Assign):
            value = node.value.value if isinstance(node.value, ast.Constant) else None
            found.update((name, value) for target in node.targets for name in binds(target))
    return found


def text_names(code) -> list:
    """Every `messages.X` and `tooltips.X` the code reads exists, or it raises in front of the user."""
    known = {owner: text_of(code[owner][1]) for owner in ("messages", "tooltips")}
    return ["%s:%d reads %s.%s, which is not there" % (path, node.lineno, node.value.id, node.attr)
            for path, _tree, nodes in code.values() for node in nodes
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
            and node.value.id in known and node.attr.isupper()
            and node.attr not in known[node.value.id]]


def placeholders(code) -> list:
    """A message's `%` fields match what each caller passes; one nobody formats has none."""
    texts = text_of(code["messages"][1])
    found, formatted, read = [], set(), set()
    for path, _tree, nodes in code.values():
        for node in nodes:
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                    and node.value.id == "messages":
                read.add(node.attr)
            if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod)
                    and isinstance(node.left, ast.Attribute)
                    and isinstance(node.left.value, ast.Name)
                    and node.left.value.id == "messages"):
                continue
            name = node.left.attr
            formatted.add(name)
            given = len(node.right.elts) if isinstance(node.right, ast.Tuple) else 1
            wanted = len(PLACEHOLDER.findall(texts.get(name) or ""))
            if isinstance(texts.get(name), str) and given != wanted:
                found.append("%s:%d passes %d to messages.%s, which has %d" % (
                    path, node.lineno, given, name, wanted))
    return found + ["messages.%s has a %% field and is never formatted" % name
                    for name in sorted(read - formatted)
                    if PLACEHOLDER.search(texts.get(name) or "")]


def literal_words(node) -> str:
    """The first worded literal an argument is written with, or ""."""
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) and WORDED.search(
            re.sub(r"%[-+ #0-9.]*[sdifr%]", "", node.value)) else ""
    parts = {ast.JoinedStr: lambda n: n.values, ast.IfExp: lambda n: (n.body, n.orelse),
             ast.BoolOp: lambda n: n.values, ast.Tuple: lambda n: n.elts,
             ast.List: lambda n: n.elts,
             ast.BinOp: lambda n: (n.left,) if isinstance(n.op, ast.Mod) else (n.left, n.right)}
    found = parts.get(type(node), lambda n: ())(node)
    return next((words for words in map(literal_words, found) if words), "")


def text_literals(code) -> list:
    """What a dialog, the status line or a tooltip says comes from messages.py or tooltips.py."""
    found = []
    for path, _tree, nodes in code.values():
        interface = path.startswith(INTERFACE)
        for node in nodes:
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            name, owner = node.func.attr, ast.unparse(node.func.value)
            said = []
            if name in DIALOGS:
                said = node.args[:1] + [k.value for k in node.keywords if k.arg in TEXT_KEYWORDS]
            elif owner == "debug" and name in ("alert", "refuse", "status", "note"):
                said = node.args[:1] if name != "note" or interface else []
            elif owner.endswith("QMessageBox"):
                said = node.args[1:3]
            elif name in ("setToolTip", "tooltip_text"):
                said = node.args[:1]
            for words in filter(None, map(literal_words, said)):
                found.append("%s:%d writes its own text %r" % (path, node.lineno, words[:40]))
    return found


def comment_length() -> list:
    """No comment or docstring line is over 100 characters, in any file of the repository."""
    found = []
    for folder, dirs, files in os.walk(ROOT):
        dirs[:] = sorted(d for d in dirs if d not in (".git", "__pycache__"))
        for name in sorted(f for f in files if f.endswith((".py", ".sh", ".shelf", ".xml"))):
            path = os.path.join(folder, name)
            with open(path, encoding="utf-8") as handle:
                source = handle.read()
            found += ["%s:%d has a comment over 100 characters" % (
                os.path.relpath(path, ROOT).replace(os.sep, "/"),
                source.count("\n", 0, match.start()) + 1) for match in LONG.finditer(source)]
    return found


def doc_pictures() -> list:
    """Every picture MANUAL.md and README.md show is a file in the repository."""
    found = []
    for doc in ("MANUAL.md", "README.md"):
        with open(os.path.join(ROOT, doc), encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                for one in re.findall(r'<img[^>]*\bsrc="([^"]+)"|!\[[^\]]*\]\(([^)\s]+)\)', line):
                    src = one[0] or one[1]
                    if "://" not in src and not os.path.exists(os.path.join(ROOT, src)):
                        found.append("%s:%d shows %s, which is not there" % (doc, number, src))
    return found


def _text(*parts) -> str:
    """A repository file's text, its path given from the repository's root."""
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as handle:
        return handle.read()


def _constant(relative, name):
    """The literal a script binds to `name` at its top, or None."""
    for node in ast.parse(_text(relative)).body:
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    return None


def suite_lists() -> list:
    """Every test module is in a list of start_test.sh, each listed one exists, gate ones run."""
    runner, lists = _text(TESTS, "start_test.sh"), {}
    for name in ("MODULES", "GATE_MODULES"):
        match = re.search(r'^%s="(.*?)"' % name, runner, re.S | re.M)
        lists[name] = set(match.group(1).replace("\\\n", " ").split()) if match else None
    found = ["start_test.sh has no %s list" % name for name, held in lists.items() if held is None]
    modules, gate = lists["MODULES"] or set(), lists["GATE_MODULES"] or set()
    on_disk = {name[:-3] for name in os.listdir(TESTS)
               if name.startswith("test_") and name.endswith(".py")} - {"test_support"}
    found += ["tests/%s.py is in no list of start_test.sh, so no push runs it" % name
              for name in sorted(on_disk - modules - gate)]
    found += ["start_test.sh lists %s, which is gone" % name
              for name in sorted((modules | gate) - on_disk)]
    found += ["start_test.sh has %s in both lists" % name for name in sorted(modules & gate)]
    pushed = set(_constant("tools/select-tests.py", "GATE_TESTS") or ())
    return found + ["GATE_MODULES holds %s and select-tests.py's GATE_TESTS does not, so no push "
                    "runs it" % name for name in sorted(gate - pushed)]


def test_runner() -> list:
    """start_test.sh refuses a wrong name before Houdini starts and runs what it was given."""
    runner = _text(TESTS, "start_test.sh")
    lines = "\n".join(line for line in runner.splitlines() if not line.lstrip().startswith("#"))
    found = [] if 0 <= runner.find("no such test module") < runner.find("AMAZE_HOUDINI") else [
        "start_test.sh no longer refuses a wrong module name before it looks for Houdini"]
    found += ["start_test.sh no longer %s" % lost for needle, lost in (
        ('run_suite.py" $run_modules', "runs the modules it resolved"),
        ('run_modules="$wanted_modules"', "runs the modules it was given"),
        ('run_modules="$MODULES"', "runs the whole list when given none"),
        ("SUBSET RUN", "says a subset is not the full run"),
        ("check_log_leak.py", "runs the leak check")) if needle not in lines]
    if "hython -m unittest" in lines:
        found.append("start_test.sh runs bare `hython -m unittest`, which skips the sandbox")
    if "LOG LEAK" not in _text(TESTS, "check_log_leak.py"):
        found.append("check_log_leak.py no longer prints LOG LEAK, which pre-push looks for")
    report = _constant(os.path.join(TESTS, "run_suite.py"), "SKIP_REPORT_VAR")
    run_tests = _text("tools", "run-tests.sh")
    return found + ["run-tests.sh --all-versions no longer %s" % lost for needle, lost in (
        ('%s="$report"' % report, "gives each run its own skip report"),
        ("check_dead_cover.py", "runs the dead-cover check"),
        ("full_run", "keeps a subset from passing the dead-cover check")) if needle not in run_tests]


def tool_scripts() -> list:
    """The tools find Houdini through the one resolver, and run on every system."""
    shells = sorted(name for name in os.listdir(os.path.join(ROOT, "tools")) if name.endswith(".sh"))
    found = []
    for name in shells:
        text = _text("tools", name)
        if "mktemp -d -t" in text:
            found.append("tools/%s uses `mktemp -d -t`, which GNU and MSYS mktemp refuse" % name)
        if "ls -d /Applications" in text:
            found.append("tools/%s looks for Houdini its own way, which only works on a Mac" % name)
        if "hython" in text and name != "houdini-env.sh" and "houdini-env.sh" not in text:
            found.append("tools/%s uses hython without sourcing houdini-env.sh" % name)
    callers = ["tools/" + name for name in shells] + [
        "tools/git-hooks/pre-push", "scripts/python/amaze/tests/start_test.sh"]
    return found + ["%s asks for the newest Houdini; only amaze_houdini picks the build" % path
                    for path in callers if "amaze_newest_houdini" in _text(path)]


def _imports_test_support(node) -> bool:
    if isinstance(node, ast.Import):
        names = [alias.name for alias in node.names]
    elif isinstance(node, ast.ImportFrom):
        names = ["%s.%s" % (node.module, alias.name) for alias in node.names]
    else:
        return False
    return any(name.split(".")[-1] == "test_support" for name in names)


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
                if ast.unparse(call.func).endswith("addCleanup") and any(
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


def test_modules() -> list:
    """Each test module arms the sandbox, builds the app offscreen, stops its patches, ends at main."""
    found = []
    for name in sorted(n for n in os.listdir(TESTS) if n.startswith("test_") and n.endswith(".py")):
        source = _text(TESTS, name)
        tree = ast.parse(source, name)
        built = re.search(r"\bQ(?:Gui)?Application\(", source)
        if built and not 0 <= source.find(OFFSCREEN) < built.start():
            found.append("tests/%s builds the app before it sets the offscreen platform" % name)
        main = min((node.lineno for node in ast.walk(tree) if isinstance(node, ast.Call)
                    and ast.unparse(node.func) == "unittest.main"), default=None)
        found += ["tests/%s defines %s below unittest.main(), so a direct run skips it" % (
            name, node.name) for node in tree.body if main is not None
            and isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.lineno > main]
        if name == "test_support.py":
            continue
        if not any(map(_imports_test_support, tree.body)):
            found.append("tests/%s never imports test_support at its top, so alone it can write "
                         "the user's folders" % name)
        found += ["tests/%s:%d starts a patch with no cleanup to stop it" % (name, line)
                  for line in _starts_left_running(tree)]
    return found


RULES = (layers, engine_widgets, preview_api, host_checks, unbound_names, defined_twice,
         event_pumps, unowned_styles, colour_pickers, text_names, placeholders, text_literals)
CHECKS = (comment_length, doc_pictures, suite_lists, test_runner, tool_scripts, test_modules)


def refusals() -> list:
    """`rule: what breaks it` for every break of every rule."""
    code = shipped()
    return ["%s: %s" % (rule.__name__, line) for rule in RULES for line in rule(code)] + [
        "%s: %s" % (rule.__name__, line) for rule in CHECKS for line in rule()]


if __name__ == "__main__":
    lines = refusals()
    for line in lines:
        print("code: REFUSED - " + line, file=sys.stderr)
    print("code: %d rules read, %d breaks" % (len(RULES) + len(CHECKS), len(lines)))
    sys.exit(1 if lines else 0)
