"""Each layer of Amaze uses only the layers below it, read from the source. ▸m/layer-plan"""
import ast
import os
import sys
import unittest

from amaze.tests import test_support  # noqa: F401

PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(PACKAGE)
EXCEPTIONS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "layer_exceptions.txt")
SKIP_DIRS = {"__pycache__", "tests", "res", "ui"}

ORDER = ("base", "library", "formats", "models", "houdini", "actions", "interface")
ALLOWED = {    # who may use whom: everything below, except that models and houdini are siblings
    "base": {"base"},
    "library": {"base", "library"},
    "formats": {"base", "library", "formats"},
    "models": {"base", "library", "formats", "models"},
    "houdini": {"base", "library", "formats", "houdini"},
    "actions": {"base", "library", "formats", "models", "houdini", "actions"},
    "interface": set(ORDER),
}

PACKAGE_LAYER = {    # every module under these packages
    "panel": "interface", "dialogs": "interface", "utils": "interface",
    "render": "houdini", "preview": "houdini", "prefs": "library", "actions": "actions",
}

MODULE_LAYER = {    # one row per module in core/, helpers/ and the top level
    "amaze": "base", "branding": "base", "messages": "base", "tooltips": "base",
    "amazetheme": "base", "core": "base", "helpers": "base", "core.debug": "base",
    "helpers.hostos": "base", "helpers.bytecode": "base", "core.renderers": "base",
    "helpers.wording": "base",
    "core.database": "library", "core.keyed_store": "library", "helpers.restore": "library",
    "core.quarantine": "library", "core.material": "library", "core.locations": "library",
    "core.notes": "library", "core.users": "library", "core.versions": "library",
    "core.captures": "library", "core.library_policy": "library",
    "core.library_prefs": "library", "core.tile_icons": "library", "core.texstore": "library",
    "core.repair": "library", "core.asset_files": "library",
    "core.packages": "formats", "core.addons": "formats", "core.matx_sources": "formats",
    "core.matx_usd": "formats", "core.bsdf_reader": "formats", "core.conversion": "formats",
    "core.geo_library": "formats",
    "core.library": "models", "core.category": "models", "core.cop_library": "models",
    "core.code_library": "models", "core.gradient_library": "models",
    "core.file_library": "models", "core.folders": "models", "core.texture_library": "models",
    "core.matx_library": "models", "core.grid_engine": "models", "core.grid_proxy": "models",
    "core.multifilterproxy_model": "models", "core.model_registry": "models",
    "core.thumbnails": "models", "core.grid_columns": "models", "core.matx_icon": "models",
    "helpers.vex_syntax": "models",
    "core.dragengine": "houdini", "core.lop_assign": "houdini", "core.scene_captures": "houdini",
    "core.gallery_import": "houdini", "core.matx_translate": "houdini",
    "core.matx_import": "houdini", "helpers.helpers": "houdini", "helpers.hostver": "houdini",
    "core.updater": "actions",
    "helpers.ui_helpers": "interface", "helpers.theme": "interface",
}

HOUDINI = {"hou", "husd", "toolutils", "loputils", "voptoolutils", "nodegraphutils",
           "hdefereval", "stateutils", "viewerstate", "soptoolutils", "objecttoolutils"}
HOUDINI_LIBS = {"pxr", "MaterialX"}    # Houdini's Python libraries, no session needed
TALK = {"displayMessage", "displayConfirmation", "displayCustomConfirmation", "readInput",
        "readMultiInput", "selectFile", "selectFromList", "selectFromTree", "selectColor",
        "selectNode", "selectMultipleNodes", "setStatusMessage"}


def module_files():
    """{dotted name without `amaze.`: path} for every module the layers cover."""
    found = {}
    for dirpath, dirs, files in os.walk(PACKAGE):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(files):
            if name.endswith(".py"):
                path = os.path.join(dirpath, name)
                rel = os.path.relpath(path, PACKAGE)[:-3].replace(os.sep, ".")
                found["amaze" if rel == "__init__" else rel.replace(".__init__", "")] = path
    return found


def layer_of(name):
    """The layer a module belongs to, or None when the map has no row for it."""
    head = name.split(".")[0]
    if head in PACKAGE_LAYER:
        return PACKAGE_LAYER[head]
    return MODULE_LAYER.get(name)


def _target(dotted, modules):
    """The amaze module a dotted import lands on: its longest existing prefix."""
    parts = dotted.split(".")[1:]
    while parts:
        name = ".".join(parts)
        if name in modules:
            return name
        parts = parts[:-1]
    return "amaze" if dotted == "amaze" else None


def _base_of(node, name, modules):
    """The absolute module an ImportFrom names, relative spellings resolved."""
    if not node.level:
        return node.module or ""
    parts = ("amaze." + name).split(".") if name != "amaze" else ["amaze"]
    if not modules[name].endswith("__init__.py"):
        parts = parts[:-1]
    parts = parts[:len(parts) - (node.level - 1)]
    return ".".join(parts + ([node.module] if node.module else []))


def breaks(modules=None):
    """Every place a module uses a layer it may not: (path, kind, what)."""
    modules = modules or module_files()
    found = set()
    for name, path in modules.items():
        layer = layer_of(name)
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
        talks = {}
        for node in ast.walk(tree):
            imported = []
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = _base_of(node, name, modules)
                imported = [base + "." + alias.name for alias in node.names] if \
                    base.split(".")[0] == "amaze" else [base] + [
                        base + "." + alias.name for alias in node.names
                        if base == "PySide6"]
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr in TALK and layer != "interface":
                talks[node.func.attr] = talks.get(node.func.attr, 0) + 1
            for dotted in imported:
                top = dotted.split(".")[0]
                if top == "amaze":
                    target = _target(dotted, modules)
                    if target and target != name and layer_of(target) not in ALLOWED[layer]:
                        found.add((_path(name, modules), "imports", _path(target, modules)))
                elif not _external_ok(layer, top, dotted):
                    what = "PySide6." + dotted.split(".")[1] if top == "PySide6" and "." in dotted \
                        else top
                    found.add((_path(name, modules), "uses", what))
        if talks:
            found.add((_path(name, modules), "talks", ", ".join(
                "%s x%d" % (call, count) for call, count in sorted(talks.items()))))
    return found


def _external_ok(layer, top, dotted):
    if top in ("PySide6", "shiboken6"):
        if dotted.endswith(("QtWidgets", "QtUiTools")):
            return layer == "interface"
        return layer != "base" or dotted == "PySide6"
    if top in HOUDINI:
        return layer in ("houdini", "actions", "interface")
    if top in HOUDINI_LIBS:
        return layer in ("formats", "houdini", "actions", "interface")
    return True    # the standard library and anything else


def _path(name, modules):
    return os.path.relpath(modules[name], PACKAGE).replace(os.sep, "/")


def listed():
    """The places the exception list allows, read as (path, kind, what)."""
    places = set()
    with open(EXCEPTIONS, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith("#"):
                path, kind, what = line.split(" ", 2)
                places.add((path, kind, what))
    return places


def lines(places):
    return ["%s %s %s" % place for place in sorted(places)]


class EachLayerUsesOnlyTheLayersBelowIt(unittest.TestCase):
    """The map is on the project's FigJam board; this is the push's compiler feedback. ▸m/layer-plan"""

    def test_every_module_has_a_layer(self):
        """A new file fails until the map gives it a row, so no file is outside the rules."""
        modules = module_files()
        self.assertEqual([], sorted(n for n in modules if layer_of(n) is None),
                         "these files have no row in MODULE_LAYER or PACKAGE_LAYER")
        self.assertEqual([], sorted(n for n in MODULE_LAYER if n not in modules),
                         "these rows name files that no longer exist")

    def test_no_break_beyond_the_listed_places(self):
        new = breaks() - listed()
        self.assertEqual([], lines(new),
                         "these break the layer map; move the code, or list the place on purpose")

    def test_a_fixed_place_leaves_the_list(self):
        """The list only shrinks: a place no longer broken must lose its line."""
        stale = listed() - breaks()
        self.assertEqual([], lines(stale),
                         "these are fixed; delete their lines from layer_exceptions.txt")


if __name__ == "__main__":
    if "--list" in sys.argv:    # what the exception list would hold today
        print("\n".join(lines(breaks())))
    else:
        unittest.main()
