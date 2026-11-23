"""The Amaze pane's keys as Houdini hotkeys, in Edit > Hotkeys under Houdini > Panes > Amaze."""
import hou

from amaze.core import debug

CONTEXT = "h.pane.amaze"    # under Houdini's pane contexts, so its keys override the top-level ones
MOVES = (    # (name, label, key): each also with Shift, which extends the selection, as Qt's views do
    ("left", "Left", "LeftArrow"),
    ("right", "Right", "RightArrow"),
    ("up", "Up", "UpArrow"),
    ("down", "Down", "DownArrow"),
    ("home", "First", "Home"),
    ("end", "Last", "End"),
    ("page_up", "Page Up", "PageUp"),
    ("page_down", "Page Down", "PageDown"),
)
SELECT_ALL = "select_all"
EXTEND = "extend_"
_installed = False    # Houdini keeps installed definitions for the session


def _definitions():
    """Amaze's category, context, commands and default keys, in a `hou.PluginHotkeyDefinitions`."""
    definitions = hou.PluginHotkeyDefinitions()
    about = "The keys of the Amaze pane's grid and list."
    definitions.addCommandCategory(CONTEXT, "Amaze", about)
    definitions.addContext(CONTEXT, "Amaze", about)
    for name, label, key in MOVES:
        for extend in (False, True):
            symbol = "%s.%s%s" % (CONTEXT, EXTEND if extend else "", name)
            definitions.addCommand(symbol, ("Extend %s" if extend else "Move %s") % label,
                                   ("Extend the selection: %s." if extend else "Choose the item: %s.") % label)
            definitions.addDefaultBinding(CONTEXT, symbol, (("Shift+" if extend else "") + key,))
    symbol = "%s.%s" % (CONTEXT, SELECT_ALL)
    definitions.addCommand(symbol, "Select All", "Select every item the grid or list shows.")
    definitions.addDefaultBinding(CONTEXT, symbol, ("Ctrl+A",))    # Houdini maps Ctrl to Cmd on a Mac
    return definitions


def _resolve_info(**_kwargs) -> dict:
    return {"contexts": [CONTEXT]}


def watch(widget) -> None:
    """Install Amaze's hotkeys once a session and make their context active for `widget`."""
    global _installed
    if not hou.isUIAvailable():
        return    # Houdini's hotkeys exist only with its UI
    if not _installed:
        hou.hotkeys.installDefinitions(_definitions())
        _installed = True
    hou.qt.registerKeyResolveInfoCallback(widget, _resolve_info)
    debug.event("keys", "hotkey context registered", context=CONTEXT)


def unwatch(widget) -> None:
    """The pane is closing: Houdini stops asking `widget` for its contexts."""
    if hou.isUIAvailable():
        hou.qt.unregisterKeyResolveInfoCallback(widget)


def action(event):
    """(name, extend) of the Amaze action a key press resolves to in Houdini's hotkeys, or None."""
    if not hou.isUIAvailable():
        return None
    symbol = hou.qt.resolveKeyEvent(event)
    debug.event("keys", "resolved to %s" % (symbol or "nothing"), key=event.key())
    if not symbol.startswith(CONTEXT + "."):
        return None
    name = symbol[len(CONTEXT) + 1:]
    return (name[len(EXTEND):], True) if name.startswith(EXTEND) else (name, False)
