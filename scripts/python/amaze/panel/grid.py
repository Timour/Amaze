"""The Grid area - the code that drives the ONE thumbnail view.

Batch 6 of the four-areas restructure. The Grid is already one widget
(`panel.thumblist`); what was written six times is the code that
CONFIGURES it. This module is where that code goes as it leaves
`panel.py`, and the first thing to arrive is the right-click menu.

**Seven menus became one builder over a per-section entry table.**
`_material_rc_menu`, `_file_rc_menu`, `_cop_rc_menu`, `_code_rc_menu`,
`_gradient_rc_menu` and `_matx_rc_menu` were 406 lines that each
rebuilt the same five decisions - what the selection is, which entries
exist, which are greyed, what a submenu holds, and which action was
picked - and disagreed on every one of them. A menu is DATA now
(`Section.GRID_MENU`, one row per entry) and this module is the only
code that turns that data into a QMenu.

What the table has to carry, and therefore what a row can say:

* **existence** (`shown`) - Convert to Karma exists only when the
  selection holds a Redshift material; File's Import, Load and Capture
  Preview exist only when the selection holds a row of the right KIND.
* **enabled-ness** (`needs`) - the selection law, extended: an entry
  that acts on ONE item greys out while several are selected, and an
  entry that needs ANY selection greys out while none is. It never

  it, Material opened a menu of live entries over an empty selection,
  Color/Node/File opened nothing at all, and Code opened New File -
  three answers to one question).
* **children** (`children`) - a submenu built per selection: Color's
  ramp bases and its per-palette swatches, Material's Copy To targets.
  The section says the label, the payload and a swatch COLOUR; the
  pixmap is drawn here, so `sections.py` stays free of QtGui.
* **the verb** - the name of a method on the Section. Not a callable:
  a table of names reads as a table, and the five menus can be
  compared side by side without following six lambdas.

**Dispatch is by IDENTITY through a dict**, which is what retires the
family of bug the old menus each guarded against by hand: a dismissed
menu returns None, and a conditional entry that was not built is also
None, so `action == action_convert_karma` fired the Redshift converter
(with its "Converted 0 of 0" dialog) on every dismissed right-click
until someone remembered the `is not None` guard. A dict lookup on
None finds nothing, so there is nothing to remember.
"""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from amaze.core import debug, grid_columns
from amaze.helpers import theme, ui_helpers
from amaze.panel import delegates

#: The tile painter, reached the way panel.py reaches it - the module
#: is reloaded per Houdini session, so the name is resolved through it
#: rather than bound at import.
AssetItemDelegate = delegates.AssetItemDelegate



def _resolve(context, name, indexes, current, default):
    """A named fact on the context: a plain attribute is used as it is,
    a method is asked about THIS selection.

    Both forms are wanted. `offers_preview_update` and `deletes_rows`
    are facts about the SECTION and answer with nothing selected -
    which is the form the toolbar needs too (batch 8) - while "does
    this selection hold a scene file" can only be a method. Keeping
    one name resolve both is what lets the table name the existing
    fact instead of a menu-only copy of it.
    """
    if not name:
        return default
    fact = getattr(context, name, None)
    if callable(fact):
        return bool(fact(indexes, current))
    return bool(fact)


def _enabled(context, entry, indexes, current):
    """The selection law, in one place.

    ONE law for zero, one and many: an entry says what it needs and is
    greyed when it does not have it. It is never hidden for that
    reason - hiding on a selection change is what makes a menu move
    under the cursor between two right-clicks.
    """
    if entry.needs == "always":
        return True
    if entry.needs == "one":
        return len(indexes) == 1
    if entry.needs == "any":
        return bool(indexes)
    return _resolve(context, entry.needs, indexes, current, False)


def _swatch_icon(colour: str):
    """A solid colour chip for a submenu row, so Color's Copy Color
    menu doubles as a preview of the palette."""
    side = theme.ui_px(14)
    pixmap = QtGui.QPixmap(side, side)
    pixmap.fill(QtGui.QColor(colour))
    return QtGui.QIcon(pixmap)


def _tidy_separators(rows):
    """No leading, doubled or trailing divider.

    A table with conditional rows produces all three - drop every
    kind-conditional entry from the File menu and its divider is the
    first thing in it; a Code menu over an empty selection used to end
    on one. Each of the seven hand-written menus placed its dividers
    where its own conditionals happened to leave them, which is why
    none of them had to think about this and a table does.
    """
    out = []
    for row in rows:
        if row is None:
            if out and out[-1] is not None:
                out.append(None)
        else:
            out.append(row)
    while out and out[-1] is None:
        out.pop()
    return out


def build_menu(panel, context, entries, indexes, current):
    """The QMenu for one entry table, plus {action: (verb, payload)}.

    Split from the exec so a test can read the menu without a popup,
    and so the dispatch table is a value rather than a closure.

    It takes the TABLE rather than reading `GRID_MENU` itself, because
    the Sidebar's three menus are the same five decisions over a
    different table and a different selection - so they get this
    builder rather than a second one (2026-08-04).
    """
    menu = QtWidgets.QMenu(panel)
    verbs = {}
    rows = []
    for entry in entries:
        if not entry.label:
            rows.append(None)
            continue
        if not _resolve(context, entry.shown, indexes, current, True):
            continue
        rows.append(entry)

    for entry in _tidy_separators(rows):
        if entry is None:
            menu.addSeparator()
            continue
        label = entry.label
        if entry.count_suffix and len(indexes) > 1:
            label += " (%d)" % len(indexes)
        enabled = _enabled(context, entry, indexes, current)
        if entry.children:
            submenu = menu.addMenu(label)
            # The PARENT carries the enabled state: greying the rows
            # inside a live submenu still lets the user open it and
            # find nothing to pick, which reads as broken rather than
            # as unavailable.
            submenu.menuAction().setEnabled(enabled)
            children = getattr(context, entry.children)(indexes, current)
            # (label, payload, swatch colour, live). A child GREYS when
            # it has nothing to act on; it does not vanish - the same
            # law the top level follows, and the File sidebar's Label
            # submenu is where it shows: Remove is offered on a
            # location with no label, greyed, so the submenu keeps its
            # shape between two right-clicks.
            for child_label, payload, colour, live in children:
                if colour:
                    action = submenu.addAction(
                        _swatch_icon(colour), child_label)
                else:
                    action = submenu.addAction(child_label)
                action.setEnabled(bool(live))
                verbs[action] = (entry.verb, payload)
            continue
        action = menu.addAction(label)
        action.setEnabled(enabled)
        if entry.checkable:
            # A TOGGLE, not a command: the entry says what its current
            # state is, and the verb is handed the state the user just
            # asked for. File's Show Subfolders and Show All Files are
            # the only two, and they are per-location.
            action.setCheckable(True)
            state = _resolve(context, entry.checkable, indexes, current,
                             False)
            action.setChecked(state)
            verbs[action] = (entry.verb, not state)
        else:
            verbs[action] = (entry.verb, None)
    return menu, verbs


def build_grid_menu(panel, context, indexes, current):
    """The Grid's table. Kept as its own name because the tests and
    the docs speak of the grid menu specifically."""
    return build_menu(panel, context, context.GRID_MENU, indexes, current)


def open_grid_menu(panel, context) -> None:
    """Right-click on the Grid."""
    if context is None:
        return
    _open(panel, context, getattr(context, "GRID_MENU", ()),
          context.grid_selection(), panel.thumblist)


def open_catlist_menu(panel, context) -> None:
    """Right-click on the Sidebar - the same builder over the same
    five decisions, a different table and a different selection.

    It was three hand-written menus (2026-08-04): Add / Rename /
    Remove / divider / Set Color / Clear Color in all three, with File
    swapping Rename for a Label submenu and adding two per-location
    toggles. The spine was identical and each copy placed its own
    dividers, wrote its own selection law and guarded its own
    conditional entries against the None-collision by hand.
    """
    if context is None:
        return
    _open(panel, context, getattr(context, "SIDEBAR_MENU", ()),
          context.sidebar_selection(), panel.cat_list)


def _open(panel, context, entries, indexes, view) -> None:
    """Build a menu, show it, and run whatever was picked.

    The selection and the current row are read ONCE here. Both were
    read again inside every menu that needed them, and the fallback
    from a dead current index to the first selected row was written
    twice and forgotten in four places.
    """
    if not entries or view is None:
        return
    current = ui_helpers.live_current_index(view)
    # THE ROW THE MENU IS ABOUT IS ALWAYS A SELECTED ROW. Qt's current
    # index and its selection are independent - arrow keys and a
    # programmatic select both move one without the other - so a
    # current index outside the selection is reachable, and File's
    # Load, Show Location and Capture Preview each read it raw. Two of
    # the three copies fell back to the first selected row only when it
    # was INVALID, which cannot see the case where it is valid and
    # points somewhere else.
    if current is None or not current.isValid() or current not in indexes:
        current = indexes[0] if indexes else None

    menu, verbs = build_menu(panel, context, entries, indexes, current)
    chosen = menu.exec_(QtGui.QCursor.pos())
    # A dismissed menu answers None, and so does an entry that was
    # never built - which is why this is a dict lookup and not a chain
    # of `==` comparisons against names that may be None.
    verb, payload = verbs.get(chosen, ("", None))
    # THE MENU IS PARENTED TO THE PANEL, so nothing deletes it: measured
    # 2026-08-03, twenty right-clicks in Materials left FORTY QMenus
    # alive as panel children (the menu plus its Copy To submenu, every
    # time), and they lived as long as the Houdini session. All six
    # handlers did this; one builder means one line. After the lookup
    # above, because the dict is keyed by the menu's own QActions.
    menu.deleteLater()
    if not verb:
        return
    getattr(context, verb)(indexes, current, payload)


# --------------------------------------------------------------------
# THE VIEW ITSELF: which of the two grid views is up, how its
# columns are sized and styled, and how tall a row is. Moved out
# of MatLibPanel 2026-08-04 (batch 6's tail) - code motion, with
# the panel keeping a one-line delegate for each so no caller
# changed. Same shape as panel/sidebar.py.
# --------------------------------------------------------------------

def restore_drag_mode(panel) -> None:
    """Re-arm Qt's own drag after any setViewMode().

    QListView.setViewMode() re-applies the movement mode, and
    setMovement(Static) sets dragEnabled(False) - so every switch
    between grid and list silently disarmed the ONE drag that is
    still native: textures hand Houdini a real file-path mime that
    parameter fields accept. The panel-managed sections (materials,
    cop, colors, code, geometry) were unaffected, which is exactly
    why it would have gone unnoticed.
    """
    panel.thumblist.setDragEnabled(True)
    panel.thumblist.setDragDropMode(
        QtWidgets.QAbstractItemView.DragDropMode.DragOnly
    )


def sidebar_row_height(panel, table) -> int:
    """How tall a list row is, answered by the CATEGORY list.

    One source for both views. The sidebar is a plain `QListView`,
    so its row is whatever its delegate hints - and its delegate
    reserves a decoration for the colour bar, which the table's
    does not. Asking each view for its own answer is what put them
    2px apart.

    Falls back to the table's own delegate when the sidebar has no
    rows yet (a section with no categories, or construction order),
    so this never returns a height nothing was measured for.
    """
    cat = getattr(panel, "cat_list", None)
    model = cat.model() if cat is not None else None
    if model is not None and model.rowCount():
        height = cat.sizeHintForRow(0)
        if height > 0:
            return height
    option = QtWidgets.QStyleOptionViewItem()
    option.initFrom(table)
    option.font = table.font()
    return table.itemDelegate().sizeHint(
        option,
        table.model().index(0, grid_columns.KEYS.index("name"))
    ).height()


#: What a column's `roles` entry says when it is not a delegate
#: attribute. Distinct objects, because absence and "always" and
#: "never" are three different answers and two of them used to share
#: `None`.
ALWAYS_SHOWN = "always-shown"
NEVER_SHOWN = "never-shown"


def visible_view(panel):
    """The grid view the user is actually looking at.

    ONE answer to a question three readers each answered by naming
    `thumblist` outright - which is the HIDDEN one in list mode (see
    show_table). So the per-section scroll memory captured and restored
    a scrollbar nobody was moving, the Comments badge repainted a
    viewport nobody was seeing, and an online category change scrolled
    the wrong widget to the top.

    `isHidden`, never `isVisible`: a panel that was never shown reports
    every widget invisible, so `isVisible` has no answer headless
    (practice.md ▸ *Testing - proving a test can fail*) while the
    hidden FLAG is exactly what show_table sets.
    """
    table = getattr(panel, "thumbtable", None)
    if table is not None and not table.isHidden():
        return table
    return panel.thumblist


def show_table(panel, showing: bool) -> None:
    """Swap which grid view is visible.

    ONE of the two is up at any moment, and both are pointed at the
    same model and the same selection - so this is a visibility
    change and nothing more. The painted strip goes with the list
    view: the table brings its own header.
    """
    table = getattr(panel, "thumbtable", None)
    if table is None:
        return
    if showing:
        # THE CATEGORY LIST DECIDES THE ROW HEIGHT, and this asks
        # it. Both views measuring independently is exactly how
        # they ended up 2px apart: the sidebar reserves a
        # decoration for the colour bar and the table does not, so
        # the same question asked of two delegates gives two
        # answers. One source, read by the other.
        #
        # A hand-computed `max(font + 6, 18)` forced 21 here before
        # any of this. Measured 2026-08-04, offscreen: the sidebar's
        # rows are 17.
        header = table.verticalHeader()
        header.setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.Fixed)
        model = table.model()
        if model is not None and model.rowCount():
            hint = panel._sidebar_row_height(table)
            # THE MINIMUM FIRST, or the default is silently
            # clamped: `minimumSectionSize` is 19 on this style and
            # `setDefaultSectionSize(15)` answered 19 back
            # (measured). That clamp was the whole difference
            # between this table and the category list.
            header.setMinimumSectionSize(hint)
            header.setDefaultSectionSize(hint)
        # THE PANEL'S OWN COLOURS AND FONT, by palette and font.
        # A QTableView brings the platform's palette - white rows
        # and black text against a dark panel.
        #
        # THE SIDEBAR'S OWN TEXT COLOUR, from the same constant it
        # reads, so the two lists cannot disagree about what an
        # unselected row looks like. Everything else - the
        # selection band, its text colour, the alternating rows -
        # is the host's and is not set anywhere.
        table_palette = QtGui.QPalette(panel.thumblist.palette())
        table_palette.setColor(
            QtGui.QPalette.ColorRole.Text, AssetItemDelegate.TEXT_COLOR)
        table.setPalette(table_palette)
        table.setFont(panel.thumblist.font())
        # NO STYLE OBJECT AND NO STYLESHEET FOR THE PADDING: a
        # `QProxyStyle` via `setStyle` is owned by nobody and
        # bus-errored the process, and neither Qt's own examples nor
        # Houdini's base.qss pads an item cell at all.
        table.viewport().setAutoFillBackground(True)
        panel._sync_table_columns()
    # THE MODE IS RECORDED, THE VISIBILITY IS WRITTEN IN ONE PLACE.
    # A blank showing must survive a view-mode change, so this asks
    # what is up rather than assuming a view is.
    page = getattr(panel, "empty_page", None)
    blank_up = page is not None and not page.isHidden()
    panel._table_mode = bool(showing)
    apply_grid_face(panel, blank_up)


def grid_pane_layout(panel):
    """The layout holding the grid views - the empty page joins it."""
    root = getattr(panel, "ui", None)
    if root is None:
        return None
    return root.findChild(QtWidgets.QVBoxLayout, "verticalLayout_7")


def apply_grid_face(panel, blank_up: bool) -> None:
    """THE ONE WRITER of the grid pane's three visibilities.

    Exactly one of table / list / empty page is up. Kept here rather
    than in `empty_state` so that module can import this one and this
    one needs nothing back; the verdict arrives as an argument.
    """
    table = getattr(panel, "thumbtable", None)
    page = getattr(panel, "empty_page", None)
    showing_table = bool(getattr(panel, "_table_mode", False))
    if page is not None:
        page.setVisible(bool(blank_up))
    if blank_up and page is not None:
        if table is not None:
            table.setVisible(False)
        panel.thumblist.setVisible(False)
        return
    if table is not None:
        table.setVisible(showing_table)
    panel.thumblist.setVisible(not showing_table)


def bind_table_cell_delegates(panel, tile_delegate) -> None:
    """Per-COLUMN delegates for the cells Qt cannot paint as text,
    and a row height that is one text line.

    Which columns those are comes from the active delegate's own
    roles - the same roles the tile painter reads - so a section
    without a Favorite role simply has no tick to draw.
    """
    table = getattr(panel, "thumbtable", None)
    if table is None:
        return

    # THE PREVIOUS SET GOES FIRST. `setItemDelegate*` takes no
    # ownership and these are parented to the table, which outlives
    # every one of them - so rebinding left the old five alive as
    # children nothing points at. Measured on a live panel: ELEVEN
    # after an ordinary afternoon of tab switching, where one
    # `activate()` builds five (research.md > Qt widgets, views &
    # painting). Only the ones WE installed are dropped; the view's
    # own default delegate is not ours to destroy.
    #
    # setParent(None) AND deleteLater: the first leaves the child list
    # at once, the second frees it under the real event loop. A test
    # must flush `DeferredDelete` itself - `processEvents()` does not.
    for previous in getattr(table, "_amaze_cell_delegates", ()):
        try:
            previous.setParent(None)
            previous.deleteLater()
        except RuntimeError:
            pass          # already gone with a rebuilt table
    installed = []

    keys = grid_columns.KEYS
    # THE SELECTED ROW'S LOOK, in one place. Houdini's app-wide
    # stylesheet draws list-item selection itself, and the table is
    # LET to. `hou.qt.styleSheet()` goes on this panel's root and
    # every child inherits it, so the rows wear the host's own
    # selection - see `GridCellDelegate`, which now owns the cell
    # padding and nothing else.
    grid_cell = delegates.GridCellDelegate(table)
    installed.append(grid_cell)
    table.setItemDelegate(grid_cell)
    # WHICH columns are ticks is the model's list (the cells and
    # their headings have to centre together, so it is filed with
    # the alignment). What each one reads and what colour it draws
    # belongs here, with the delegate that draws it.
    sources = {
        "favorite": ("_favorite_role", tile_delegate.FAV_MARK_COLOR),
        "open": ("_open_role", tile_delegate.OPEN_MARK_COLOR),
        "comments": ("_notes_role", tile_delegate.NOTE_MARK_COLOR),
    }
    ticks = ((key,) + sources[key]
             for key in grid_columns.GridColumnsMixin.TICK_COLUMNS)
    category_cell = delegates.CategoryCellDelegate(tile_delegate, table)
    installed.append(category_cell)
    table.setItemDelegateForColumn(keys.index("category"), category_cell)
    for key, attribute, colour in ticks:
        tick = delegates.TickCellDelegate(
            tile_delegate, getattr(tile_delegate, attribute, None),
            colour, table)
        installed.append(tick)
        table.setItemDelegateForColumn(keys.index(key), tick)
    # WHAT THIS BIND OWNS, for the next one to drop.
    table._amaze_cell_delegates = installed


def sync_list_columns(panel) -> None:
    """Re-fit list mode's columns for the context now showing.

    THE SECTIONS' entry point, called from every `activate()`.
    Named for what it does rather than for how: it used to be
    `_update_list_columns`, a 259-line measure-and-fit over a
    painted strip, and it is a column-visibility sync plus Qt's own
    `ResizeToContents` now.
    """
    panel._sync_table_columns()


def sync_table_columns(panel) -> None:
    """Which columns the table SHOWS, and how wide.

    WHICH is the section's answer and stays ours: a column the
    active delegate has no role for does not exist here, which is
    exactly what the painted strip said by drawing nothing.

    HOW WIDE is Qt's now. `ResizeToContents` measures the header
    label and the visible cells, per column - which is what 214
    lines of measure-and-fit did by hand, sampled row scan and memo
    included. The one column keeping a rule of ours is the
    thumbnail: it is the picture's own size, because that is what
    is drawn in it.
    """
    table = getattr(panel, "thumbtable", None)
    if table is None:
        return
    delegate = (panel.thumblist.itemDelegate()
                if panel.thumblist is not None else None)
    roles = {
        "category": "_category_role", "tags": "_tag_role",
        "license": "_licence_role", "favorite": "_favorite_role",
        "open": "_open_role", "comments": "_notes_role",
        "version": "_active_version_role",
        # NO PICTURE COLUMN. Decided 2026-08-04, and it is the
        # cleaner answer to the slowness by a distance: at list
        # size a thumbnail is 16px, where the art is a smudge.
        #
        # At list size a thumbnail is 16px, which is the same
        # argument that took the BADGES out of list rows a few days
        # earlier - at that size the art is a smudge. Removing it
        # also removes the whole reason the column measuring was
        # expensive: DecorationRole is never asked for in list mode
        # now, so nothing queues a thumbnail the user cannot see.
        # Measured before and after: 1668 reads, then 18, now 0.
        "thumb": NEVER_SHOWN,
        # EVERY COLUMN IS NAMED, including the two that are always up.
        # Absence used to MEAN always-shown while a `None` value meant
        # hidden - one marker with two readings decided by membership -
        # so a column nobody configured was indistinguishable from one
        # deliberately left ungated. `name` and `type` were the two
        # riding on that, and a new column would have joined them
        # silently.
        "name": ALWAYS_SHOWN,
        "type": ALWAYS_SHOWN,
    }
    # AND THE MODEL HAS TO BE ABLE TO FILL IT. The delegate's roles
    # decided this alone, and the File section is handed a category
    # role while `FileFiles.COLUMN_ROLES` has no `category` entry - so
    # the column was shown, sortable, coloured, and empty in every row.
    # One question, two sources of truth: the delegate says what it can
    # PAINT, the model says what it can ANSWER, and a column needs both.
    source = table.model()
    inner = getattr(source, "sourceModel", None)
    source = (inner() if inner is not None else None) or source
    column_role = getattr(source, "_column_role", None)

    header = table.horizontalHeader()
    for column, key in enumerate(grid_columns.KEYS):
        attribute = roles.get(key)
        if attribute is None:
            # Not in the table at all: shown, and SAID, because the
            # alternative is a half-configured column that looks
            # deliberate.
            debug.event("grid", "column is in no roles entry - shown "
                                "unconditionally", column=key)
            table.setColumnHidden(column, False)
            continue
        if attribute is NEVER_SHOWN:
            table.setColumnHidden(column, True)
            continue
        fills = True
        if attribute is not ALWAYS_SHOWN and column_role is not None:
            fills = column_role(key) is not None
        shown = (attribute is ALWAYS_SHOWN
                 or (getattr(delegate, attribute, None) is not None
                     and fills))
        table.setColumnHidden(column, not shown)
    # NOTHING IS MEASURED. This is the end of a road that started
    # with a 214-line hand-written fit and went through Qt's own:
    # `ResizeToContents` as a MODE asks the delegate for a sizeHint
    # per cell and re-runs for the life of the view (~4400 style
    # options per pass on a 550-asset section, again on every
    # change of the row set), and it also forbids the user to drag
    # a column - *"the size cannot be changed by the user or
    # programmatically"*. Fitting once was better and still cost
    # 0.4ms sampled, 13.5ms exact, per row-set change.
    #
    # A STARTING WIDTH plus a drag handle is what was actually
    # wanted, and it costs nothing at all.
    #
    # SEEDED ONCE per view, not per call: this runs from every
    # activate(), view-mode switch and show, and re-applying the
    # defaults here snapped a user's dragged width back on the next
    # tab click - the widths are DEFAULTS the user can drag
    # (overview.md §2). Visibility above stays per-call, because it
    # is the SECTION's answer; a width is the USER's.
    if not getattr(table, "_widths_seeded", False):
        table._widths_seeded = True
        header.setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.Interactive)
        header.setMinimumSectionSize(theme.ui_px(panel.COLUMN_MIN_WIDTH))
        for column, key in enumerate(grid_columns.KEYS):
            width = panel.COLUMN_DEFAULT_WIDTH.get(key)
            if width:
                header.resizeSection(column, theme.ui_px(width))
        # THE LAST COLUMN TAKES THE SLACK. Qt's own property for it,
        # so a wide panel has no dead strip on the right and a narrow
        # one simply scrolls. It overrides the resize mode on that
        # section alone, which is why every other column stays
        # draggable.
        header.setStretchLastSection(True)


def style_table_header(panel) -> None:
    """Make the real header look like the strip it replaces.

    Decided 2026-08-04: match the painted strip exactly. What the
    table ADDS is what a header gives for free - click a heading to
    sort, drag an edge to resize - and none of that should announce
    itself by looking foreign.
    """
    header = panel.thumbtable.horizontalHeader()
    header.setFixedHeight(panel.HEADER_HEIGHT)
    header.setStretchLastSection(False)
    header.setHighlightSections(False)
    header.setSectionsMovable(False)
    header.setSortIndicatorShown(True)
    # POINT IT AT NAME. A header's indicator starts on section 0,
    # which is the picture column - hidden, so the arrow was
    # nowhere and the list looked unsorted until you clicked a
    # heading. Column 0 answers the display name, so this sorts by
    # exactly what it sorted by before; what changes is that you
    # can SEE which column it is.
    header.setSortIndicator(
        grid_columns.KEYS.index("name"),
        QtCore.Qt.SortOrder.AscendingOrder)
    # SORTING, which the painted strip could never offer. Every
    # column answers DisplayRole with its own text (the mixin), and
    # QSortFilterProxyModel compares exactly that for whichever
    # column it is asked about - so this is the whole feature.
    #
    # `setDynamicSortFilter(False)` is set on these proxies for
    # performance, and GridProxyModel already re-sorts on a filter
    # change and on an insert using `sortColumn()` - so a user's
    # chosen column survives both, rather than snapping back to
    # name.
    panel.thumbtable.setSortingEnabled(True)
    header.setDefaultAlignment(
        QtCore.Qt.AlignmentFlag.AlignLeft
        | QtCore.Qt.AlignmentFlag.AlignVCenter)
    header.setStyleSheet(
        "QHeaderView { background-color: %s; border: 0; }"
        "QHeaderView::section {"
        "  background-color: %s; color: %s; border: 0;"
        "  border-right: 1px solid %s; padding-left: %dpx;"
        "}" % (
            panel.HEADER_BG.name(), panel.HEADER_BG.name(),
            delegates.AssetItemDelegate.LIST_INK.name(),
            panel.HEADER_DIVIDER.name(), panel.CELL_PAD,
        ))


def apply_view_mode(panel) -> None:
    """Apply the persisted grid/list view mode to the thumbnail list and
    sync the toggle button and menu. The slider drives GRID only
    (2026-08-01); list has one size and a greyed slider.
    Wrapped so a bad state falls back to grid instead of hanging."""
    if not panel.material_model:
        return
    panel._sync_slider_for_mode()
    ts = panel._active_thumbsize()
    try:
        if panel.prefs.view_mode == "list":
            # THE TABLE IS LIST MODE. Nothing dresses the QListView
            # as a list any more - it is hidden in this mode, and
            # eleven lines were setting the flow, the wrapping, the
            # icon size, the alternating colours and the scrollbar
            # policy of a widget nobody could see. `setViewMode`
            # was the load-bearing one: it is what `_is_list` read,
            # which is what put the delegate down the painted
            # spreadsheet branch this replaces.
            #
            # It stays in IconMode throughout, so the grid it
            # paints is the only thing it ever paints.
            panel._restore_drag_mode()
            panel._show_table(True)
            panel._sync_table_columns()
        else:
            panel.thumblist.setViewMode(QtWidgets.QListView.ViewMode.IconMode)
            panel._restore_drag_mode()
            panel.thumblist.setHorizontalScrollBarPolicy(
                QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded
            )
            panel.thumblist.setAlternatingRowColors(False)
            panel.thumblist.setFlow(QtWidgets.QListView.Flow.LeftToRight)
            panel.thumblist.setWrapping(True)
            panel.thumblist.setIconSize(QtCore.QSize(ts, ts))
            # Extra height over the icon for the two text lines.
            panel.thumblist.setGridSize(
                AssetItemDelegate.grid_cell_size(ts, panel.thumblist.font())
            )
            panel._show_table(False)
        panel.thumblist.setResizeMode(QtWidgets.QListView.ResizeMode.Adjust)
    except Exception as e:
        debug.event("grid", "view mode switch failed - falling back "
                    "to grid", error=str(e))
        try:
            panel.thumblist.setViewMode(QtWidgets.QListView.ViewMode.IconMode)
            panel._restore_drag_mode()
            panel.thumblist.setGridSize(
                AssetItemDelegate.grid_cell_size(ts, panel.thumblist.font())
            )
            panel._show_table(False)
        except Exception:
            pass
    panel._sync_view_mode_controls()


# `list_grid_size` sized a list-mode row here: a width that kept the
# columns from collapsing when the notes pane grew, and a height that
# fit the thumbnail and one text line. Both belonged to the PAINTED
# list. THE TABLE IS LIST MODE now (apply_view_mode above), and the
# QListView it sized is hidden the whole time - so its one caller, a
# resize branch in MatLibPanel.eventFilter, was measuring a viewport
# nobody could see and applying the answer to a widget nobody could
# see. The table decides both: `show_table` sets the row height from
# the sidebar's, `_sync_table_columns` the widths.
#
# The width also read `panel._list_row_width`, which nothing anywhere
# ever set - so the remembered width was always the default and the
# `max()` always chose the floor.


def sync_view_mode_controls(panel) -> None:
    """Reflect prefs.view_mode on the toggle button and menu. Sets both
    menu actions explicitly (one on, one off) so they can never both read
    as selected, and suppresses handler re-entry while doing so."""
    panel._suppress_view_signals = True
    try:
        is_list = panel.prefs.view_mode == "list"
        if hasattr(panel, "cb_viewmode"):
            panel.cb_viewmode.setChecked(is_list)
        if getattr(panel, "view_actions", None):
            grid_act = panel.view_actions.get("grid")
            list_act = panel.view_actions.get("list")
            if grid_act is not None:
                grid_act.setChecked(not is_list)
            if list_act is not None:
                list_act.setChecked(is_list)
    finally:
        panel._suppress_view_signals = False


def active_thumbsize(panel) -> int:
    """The icon size for the CURRENT view mode: the remembered
    one in grid, the fixed one in list."""
    if panel.prefs.view_mode == "list":
        return panel.LIST_THUMB_SIZE
    return panel.prefs.thumbsize
