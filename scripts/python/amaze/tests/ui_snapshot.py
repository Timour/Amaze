"""A structural fingerprint of the CONSTRUCTED panel - widgets, layouts, models, menus, connected signals and the panel's own attributes, canonically. Two snapshots comparing equal mean a refactor was code motion.  `hython tests/ui_snapshot.py --out after.json --compare before.json`  ▸archive/ui_snapshot.py"""

import argparse
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

_VIEW_PROPS = (
    "viewMode", "verticalScrollMode", "horizontalScrollMode", "movement",
    "resizeMode", "layoutMode", "uniformItemSizes", "dragEnabled",
    "dragDropMode", "dragDropOverwriteMode", "selectionMode",
    "selectionBehavior", "sizeAdjustPolicy", "spacing", "wordWrap",
    "alternatingRowColors", "iconSize", "gridSize", "autoScroll",
    "contextMenuPolicy", "frameShape",
)

_WIDGET_PROPS = (
    "objectName", "isEnabled", "isHidden", "minimumSize", "maximumSize",
    "sizePolicy", "contextMenuPolicy", "toolTip", "styleSheet",
)


def _plain(value):
    """Anything Qt hands back as something JSON can hold and compare - never an address, never an unordered set. PySide enums raise on `int()`, and falling back to the type name makes every mode compare equal."""
    if isinstance(value, (bool, int, float, str)) or value is None:
        return value
    if isinstance(value, QtCore.QSize):
        return list(value.toTuple())
    if isinstance(value, QtCore.QRect):
        return list(value.getRect())
    if isinstance(value, QtCore.QMargins):
        return [value.left(), value.top(), value.right(), value.bottom()]
    if isinstance(value, QtGui.QColor):
        return value.name()
    if isinstance(value, QtWidgets.QSizePolicy):
        return [int(value.horizontalPolicy()), int(value.verticalPolicy())]
    if isinstance(value, QtGui.QFont):
        return [value.family(), value.pointSize(), value.weight()]
    if isinstance(value, QtGui.QKeySequence):
        return value.toString()
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if hasattr(value, "value") and not callable(value.value):
        try:
            return "%s.%s" % (type(value).__name__, value.name)
        except AttributeError:
            return "%s(%r)" % (type(value).__name__, value.value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return type(value).__name__


def _path(widget) -> str:
    """A stable identity - the chain of object names, or class name plus SIBLING INDEX where unnamed. The index is load-bearing: most of the tree is unnamed, and identical paths collapse onto one entry, so deleting a widget changes nothing in the snapshot."""
    parts = []
    node = widget
    while node is not None:
        name = node.objectName()
        if not name:
            parent = node.parent()
            if parent is not None:
                siblings = [c for c in parent.children()
                            if type(c) is type(node) and not c.objectName()]
                index = siblings.index(node) if node in siblings else 0
                name = "%s[%d]" % (type(node).__name__, index)
            else:
                name = type(node).__name__
        parts.append(name)
        node = node.parent()
    return "/".join(reversed(parts))


def _connected_signals(obj) -> list:
    """Every signal with at least one receiver - the check that matters, because a dropped `connect()` leaves the widget tree identical and the panel dead."""
    out = []
    meta = obj.metaObject()
    for i in range(meta.methodCount()):
        method = meta.method(i)
        if method.methodType() != QtCore.QMetaMethod.MethodType.Signal:
            continue
        try:
            if obj.isSignalConnected(method):
                out.append(bytes(method.methodSignature()).decode())
        except (RuntimeError, TypeError):
            continue
    return sorted(out)


def _layout_snapshot(layout):
    if layout is None:
        return None
    items = []
    for i in range(layout.count()):
        item = layout.itemAt(i)
        widget = item.widget()
        if widget is not None:
            items.append("W:" + (widget.objectName() or
                                 type(widget).__name__))
        elif item.layout() is not None:
            items.append("L:" + type(item.layout()).__name__)
        elif item.spacerItem() is not None:
            items.append("S:" + str(_plain(item.spacerItem().sizeHint())))
        else:
            items.append("?")
    return {
        "class": type(layout).__name__,
        "margins": _plain(layout.contentsMargins()),
        "spacing": layout.spacing(),
        "items": items,          # ORDER matters - it is the layout
    }


def _menu_snapshot(menu, depth=0):
    if menu is None or depth > 4:
        return None
    actions = []
    for action in menu.actions():
        entry = {
            "text": action.text(),
            "separator": action.isSeparator(),
            "checkable": action.isCheckable(),
            "enabled": action.isEnabled(),
            "shortcut": _plain(action.shortcut()),
        }
        if action.menu() is not None:
            entry["submenu"] = _menu_snapshot(action.menu(), depth + 1)
        actions.append(entry)
    return actions


def snapshot(panel_widget) -> dict:
    widgets = {}
    # QObject, NEVER QWidget - skipping non-widget children skips their connects.
    for widget in [panel_widget] + panel_widget.findChildren(QtCore.QObject):
        entry = {"class": type(widget).__name__}
        for prop in _WIDGET_PROPS:
            getter = getattr(widget, prop, None)
            if callable(getter):
                try:
                    entry[prop] = _plain(getter())
                except (RuntimeError, TypeError):
                    pass
        if isinstance(widget, QtWidgets.QAbstractItemView):
            for prop in _VIEW_PROPS:
                getter = getattr(widget, prop, None)
                if callable(getter):
                    try:
                        entry[prop] = _plain(getter())
                    except (RuntimeError, TypeError):
                        pass
            model = widget.model()
            entry["model"] = type(model).__name__ if model else None
            entry["delegate"] = type(widget.itemDelegate()).__name__
            entry["rows"] = model.rowCount() if model else 0
        if isinstance(widget, QtWidgets.QAbstractButton):
            entry["text"] = widget.text()
            entry["checkable"] = widget.isCheckable()
            entry["hasIcon"] = not widget.icon().isNull()
            menu = getattr(widget, "menu", lambda: None)()
            if menu is not None:
                entry["menu"] = _menu_snapshot(menu)
        if isinstance(widget, QtWidgets.QLabel):
            entry["text"] = widget.text()
            entry["hasPixmap"] = widget.pixmap() is not None \
                and not widget.pixmap().isNull()
        for attribute in ("_segments", "_checked_key", "_labels",
                          "_value", "_maximum", "_thumb_w", "_name_w",
                          "_type_w", "_cat_w", "_tag_w", "_licence_w"):
            if hasattr(widget, attribute):
                try:
                    entry[attribute] = _plain(getattr(widget, attribute))
                except (RuntimeError, TypeError):
                    pass
        if isinstance(widget, QtGui.QAction):
            entry["text"] = widget.text()
            entry["checkable"] = widget.isCheckable()
            entry["checked"] = widget.isChecked()
            entry["shortcut"] = _plain(widget.shortcut())
            entry["separator"] = widget.isSeparator()
        if isinstance(widget, QtWidgets.QLineEdit):
            entry["placeholder"] = widget.placeholderText()
        if isinstance(widget, QtWidgets.QAbstractSlider):
            entry["range"] = [widget.minimum(), widget.maximum()]
            entry["value"] = widget.value()
        if isinstance(widget, QtWidgets.QWidget):
            entry["layout"] = _layout_snapshot(widget.layout())
        entry["signals"] = _connected_signals(widget)
        widgets[_path(widget)] = entry

    attrs = {}
    for name in sorted(dir(panel_widget)):
        if name.startswith("__"):
            continue
        try:
            value = getattr(panel_widget, name)
        except Exception:                                # noqa: BLE001
            continue
        if callable(value):
            continue
        attrs[name] = type(value).__name__

    signal_count = sum(len(w["signals"]) for w in widgets.values())
    if len(widgets) < 40 or signal_count < 40:
        print("WARNING: only %d objects and %d connected signals - the "
              "panel was probably built WITHOUT a library, so this "
              "snapshot proves very little." % (len(widgets), signal_count))
    return {"widgets": widgets, "attributes": attrs,
            "widget_count": len(widgets), "signal_count": signal_count}


def _diff(before: dict, after: dict) -> list:
    """Every difference, as a readable line."""
    out = []
    for section in ("widgets", "attributes"):
        b, a = before.get(section, {}), after.get(section, {})
        for key in sorted(set(b) - set(a)):
            out.append("REMOVED %s: %s" % (section, key))
        for key in sorted(set(a) - set(b)):
            out.append("ADDED   %s: %s" % (section, key))
        for key in sorted(set(a) & set(b)):
            if a[key] == b[key]:
                continue
            if isinstance(a[key], dict) and isinstance(b[key], dict):
                for prop in sorted(set(a[key]) | set(b[key])):
                    if a[key].get(prop) != b[key].get(prop):
                        out.append("CHANGED %s %s.%s: %r -> %r"
                                   % (section, key, prop,
                                      b[key].get(prop), a[key].get(prop)))
            else:
                out.append("CHANGED %s %s: %r -> %r"
                           % (section, key, b[key], a[key]))
    return out


def _protect_live_settings():
    """Constructing the real panel WRITES the real settings.json, so saving is disabled outright rather than restored afterwards - a restore races the panel's own deferred save timers. The log is redirected too: a snapshot is not a session anyone had."""
    from amaze.tests import test_support
    test_support.isolate_debug_log()

    from amaze.prefs import prefs as prefs_mod

    original = prefs_mod.Prefs.save
    prefs_mod.Prefs.save = lambda self, *a, **k: None

    def restore():
        prefs_mod.Prefs.save = original
    return restore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="")
    parser.add_argument("--compare", default="",
                        help="an earlier snapshot to diff against")
    args = parser.parse_args()

    from amaze.panel import panel as panel_mod

    restore = _protect_live_settings()
    try:
        widget = panel_mod.MatLibPanel()
        data = snapshot(widget)
    finally:
        restore()
    print("widgets: %d   attributes: %d"
          % (data["widget_count"], len(data["attributes"])))
    print("connected signals: %d"
          % sum(len(w["signals"]) for w in data["widgets"].values()))

    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=1, sort_keys=True)
        print("written:", args.out)

    if args.compare:
        with open(args.compare, encoding="utf-8") as handle:
            before = json.load(handle)
        differences = _diff(before, data)
        if not differences:
            print("\nIDENTICAL to %s - the refactor changed nothing "
                  "structural." % args.compare)
            return 0
        print("\n%d DIFFERENCE(S) against %s:"
              % (len(differences), args.compare))
        for line in differences[:60]:
            print("   " + line)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
