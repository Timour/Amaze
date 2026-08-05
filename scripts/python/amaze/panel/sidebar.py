"""The Sidebar area - the code that drives the ONE category/folder list.

Batch 7 of the four-areas restructure, the counterpart to
`panel/grid.py`. The Sidebar is already one widget (`panel.cat_list`);
what was spread across `panel.py` is the code that decides what a row
MEANS and what may be dropped on it.

**The drag-hover cluster lives here.** Ten methods answering one
question in layers - is the thing under the cursor a row a tile can be
dropped onto, and if so, which - plus the highlight that says so. They
are functions over the panel rather than methods on it, the same shape
`grid.open_grid_menu` uses.

**What actually changed on the way, and it is not the move.** The
cluster branched on the section KEY twice: a `CATEGORY_SECTIONS` tuple
of four key strings, and `if self.current_section == "gradient"`
reaching into `gradient_model` by name. That is the shape batches 4 to
9 took out of activation, the toolbar, comments and both menus, still
standing in the sidebar. The context answers now -
`Section.takes_category_drops` and `Section.accepts_category_drop` -
so a sixth section brings its own answer instead of being added to a
tuple somebody has to remember.

The HIGHLIGHT repaints rather than updates, deliberately: a native
`QDrag.exec()` (the texture file drag) runs macOS's own drag loop,
which does not process Qt's deferred paint events until the drag ends,
so `update()` never showed the drop target at all.
"""

from __future__ import annotations

from PySide6 import QtGui


def droppable_index(panel, pos):
    """The sidebar index under a sidebar-local point IF a tile may be
    dropped on it. Else None.

    THE ONE PLACE the drop-target rules live. Three of them are shared
    - the context takes drops at all, the row is real, the row is not
    "All" - and whatever is left is the context's own.
    """
    context = panel._section()
    if context is None or not context.takes_category_drops:
        return None
    if panel.cat_list is None:
        return None
    index = panel.cat_list.indexAt(pos)
    if not index.isValid():
        return None
    # The STORED name: the sidebar shows "_WIP" as "WIP", and every
    # rule below - and the write that follows - is about the stored one.
    name = panel._raw_category_name(index)
    if not name or name in ("All", "_All"):
        return None
    if not context.accepts_category_drop(index, name):
        return None
    return index


def category_at_point(panel, pos):
    """The droppable category NAME at a sidebar-local point, or None.

    The stored name, which is what `assign_category_active` writes onto
    the asset. By its LABEL, a drop onto "_WIP" called
    `check_add_category("WIP")` and created a SECOND category beside
    it - so the tile vanished from the row it was dropped on.
    """
    index = droppable_index(panel, pos)
    return None if index is None else panel._raw_category_name(index)


def _cursor_in_sidebar(panel):
    """The cursor's sidebar-local position, or None when it is not over
    the sidebar at all. The guard both global-cursor paths need."""
    if panel.cat_list is None or not panel.cat_list.isVisible():
        return None
    viewport = panel.cat_list.viewport()
    pos = viewport.mapFromGlobal(QtGui.QCursor.pos())
    return pos if viewport.rect().contains(pos) else None


def category_under_cursor(panel):
    """The assignable category name under the GLOBAL cursor, or None.

    Every self-managed release checks this first: a drop on a sidebar
    category recategorises instead of importing.
    """
    pos = _cursor_in_sidebar(panel)
    return None if pos is None else category_at_point(panel, pos)


def set_hover_row(panel, row: int) -> None:
    """Highlight (row) or clear (row=-1) the category being dragged
    over, in the accent purple - the drop-target feedback.

    `repaint()`, not `update()`: a native `QDrag.exec()` (the texture
    file drag) runs macOS's own drag loop, which does not process Qt's
    DEFERRED paint events until the drag ends, so the highlight never
    showed at all through `update()`. This paints synchronously, inside
    the drag loop.
    """
    delegate = getattr(panel, "sidebar_delegate", None)
    if delegate is None or delegate.drag_row == row:
        return
    delegate.drag_row = row
    if panel.cat_list is not None:
        panel.cat_list.viewport().repaint()


def update_hover(panel, pos) -> None:
    """Set the highlight from a sidebar-local point."""
    index = droppable_index(panel, pos)
    set_hover_row(panel, index.row() if index is not None else -1)


def update_hover_global(panel) -> None:
    """The highlight for the SELF-MANAGED drags (Node/Color/Code, which
    have no Qt drag events) - maps the global cursor into the sidebar
    and highlights whatever droppable row it is over."""
    pos = _cursor_in_sidebar(panel)
    if pos is None:
        set_hover_row(panel, -1)
        return
    update_hover(panel, pos)


def can_drop(panel, event) -> bool:
    """The sidebar accepts a drop only from OUR OWN grid, and only into
    a context that takes them - so a node dragged in from a Houdini
    network editor still falls through to the save-node handler."""
    context = panel._section()
    return bool(context is not None
                and context.takes_category_drops
                and event.source() is panel.thumblist)


def handle_drop(panel, event) -> bool:
    """A grid drag was dropped on the sidebar.

    Recategorise the selection if it landed on a real category; consume
    the drop either way - even over "All" or empty space - so it never
    reaches the central widget's save-node flow.
    """
    if not can_drop(panel, event):
        return False
    category = category_at_point(panel, event.position().toPoint())
    if category is not None:
        panel.assign_category_active(category)
    return True
