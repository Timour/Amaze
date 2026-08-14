"""Section objects - one per library tab, like a small node type.

The panel owns the widgets (cat_list, thumblist, filter box, star) and
builds every model in setup(). A Section encapsulates how ONE section
drives them: what its activate does, how it filters, what a sidebar
click means, what a double-click does. The panel's shared handlers then
dispatch to `panel._section()` instead of branching on
`current_section`, so a new section is a new class here, not edits to a
dozen handlers.

Three archetypes, mirroring the three model families:

* **AssetSection** - the curated-library machinery (a MaterialLibrary
  over its own json + a Categories sidebar): Material, Node, Code.
* **FolderSection** - a folder-pointer list over real files on disk:
  the File section (the 2026-07-31 merge of Images, Geometry and HIP -
  one folder list, EVERY file shown, per-kind behaviour).
* **GradientSection** - the palette library: Color. (Not read-only -
  it adds, renames, recategorises and deletes user palettes.)

`activate()` used to delegate back to the panel; the bodies moved onto
the sections in batch 4 (2026-08-03), so an archetype now points the
shared widgets at its own models directly. `activate_method` survives
only as the base's fallback for a context that has not been moved.

The module docstring below each class says what that class owns; the
four AREAS each have a hook here - activate (Grid + Sidebar bindings),
select_category (Sidebar), comment_subject (Comments), and the toolbar
facts declared as data.

**A section's grid right-click MENU is data here too** (`GRID_MENU`,
2026-08-03): six handlers in panel.py became one table per context and
one builder in `panel/grid.py`. See `MenuEntry` below for what a row
carries and why every behaviour in it is a NAME rather than a callable.
"""

from __future__ import annotations

import collections
import os

import hou
from PySide6 import QtCore, QtWidgets

from amaze.core import (debug, dragengine, file_library, grid_columns,
                        scene_captures, notes)
from amaze.dialogs import code_dialog
from amaze.helpers import helpers, hostos, ui_helpers
from amaze.panel import grid


#: THE ASSET STACK - the four models an Asset section works through.
#:
#: A bare 4-tuple until 2026-08-03, unpacked in nine places and read by
#: NUMBER in three more (`st[0]`, `st[1]`, `st[3]`). Mixed unpacking and
#: indexing is where a swap hides: `st[3]` is the categories model only
#: because nothing has ever reordered the tuple. overview.md names the
#: four parts; these are those names.
AssetStack = collections.namedtuple(
    "AssetStack", "model proxy selection categories")

#: WHAT THE COMMENTS PANE POINTS AT. Six values, built by three
#: different sections and unpacked positionally into
#: `notes_panel.set_subject` - so three builders had to agree on an
#: order nothing enforced, which is the column-widths defect with more
#: authors. `colour` is the CATEGORY's colour, not the comment's.
CommentSubject = collections.namedtuple(
    "CommentSubject", "key section name type category colour",
    defaults=("", ""),
)

#: THE REGISTERED LOCATION a File row came from: which folder is
#: recorded, how that folder displays itself (a custom name, else the
#: path), and the colour set on it.
FileLocation = collections.namedtuple(
    "FileLocation", "path label colour")

#: WHAT A GESTURE DOES HERE (ROADMAP - the interaction matrix): one
#: behaviour, two aiming methods, BOTH doors reading this one rule.
#:
#: The DRAG walker (GridGestureMixin._apply_drop_rule) aims by the
#: cursor: a node under the release takes the payload `(index,
#: node)`; a release outside the panel runs `outside(index)`; a
#: self-aiming verb `resolve(index)` finds its own landing; empty
#: network space runs the creation rule `(index, network, position)`.
#:
#: The CLICK walker (MatLibPanel._apply_click_rule) aims by the
#: SELECTION: one visible selected node is tried through `on_node` as
#: a HINT - a node that cannot take the payload falls through, never
#: vetoes (the host's own Tab behaviour: a selection never blocks a
#: creation); then `click_resolve(index)` for sections that aim
#: themselves; then the creation walk over the visible networks; the
#: one dialog only when nothing held it.
#:
#: Undeclared doors fall through; no door left = the uniform miss.
#: This retired the release ladder AND the five hand-written
#: double-click handlers - two doors, one rule (ROADMAP - the
#: interaction matrix).
#: `on_node`/`on_space`/`resolve`/`outside` are the DRAG's doors;
#: `click_on_node`/`click_resolve` are the CLICK's, and they are
#: separate because the function sheet aims the two doors
#: differently in exactly two rows: a double-clicked scene file
#: opens the scene and an unknown file copies its path, whatever
#: happens to be selected, while a DRAGGED one still hands its path
#: to the node under the cursor. Where both doors agree - code,
#: colour, images - the same verb name appears in both fields, which
#: is one fact stated twice, not two mechanisms.
#: `carrier_type` names what the space door CREATES, when the answer
#: is a constant - the DRAG GHOST draws that type's shape while the
#: payload is still in the air, from the same declaration the creator
#: builds from. A per-kind rule carries its own; a section-wide one
#: sits on the class (Section.carrier_type / carrier_type_verb).
DropRule = collections.namedtuple(
    "DropRule",
    "on_node on_space resolve outside click_on_node click_resolve "
    "carrier_type",
    defaults=(None, None, None, None, None, None, ""),
)


#: ONE ROW OF A GRID RIGHT-CLICK MENU - data, never a callable.
#:
#: The seven menus this replaces were 406 lines of panel.py, and each
#: rebuilt the same five decisions in its own words. The behaviour is
#: still per-section; what stops being per-section is the CODE that
#: renders it (panel/grid.py is the only reader).
#:
#: * `label` - the text, from ui-text.md, which is the source for
#:   every user-facing string. An empty label is a divider (SEPARATOR
#:   below); the builder drops leading, doubled and trailing ones, so
#:   a table with conditional rows never has to place them by hand.
#: * `verb` - the NAME of a method on this section, called as
#:   `verb(indexes, current, payload)`. A name rather than a function
#:   so the five tables read side by side.
#: * `needs` - what the entry needs to be LIVE: "any" (a selection,
#:   the default), "one" (exactly one row), "always" (New File and
#:   Refresh act on nothing), or the name of a fact answering for this
#:   selection. It greys; it never hides.
#: * `shown` - the name of a fact deciding whether the entry EXISTS at
#:   all. A plain attribute (`deletes_rows`) or a method asked about
#:   this selection - the same two forms the toolbar table reads.
#: * `children` - the name of a method returning
#:   ((label, payload, swatch_colour), ...) for a submenu. The colour
#:   is a hex string or ""; the pixmap is drawn in panel/grid.py, so
#:   nothing here needs QtGui.
#: * `count_suffix` - append " (N)" on a multi-selection, which is how
#:   the online imports say how many they are about to fetch.
#: * `checkable` - the name of a fact giving the entry's CURRENT state.
#:   Makes it a tick-box rather than a command, and the verb is handed
#:   the state the user just asked for. Only the File sidebar's two
#:   per-location toggles use it.
MenuEntry = collections.namedtuple(
    "MenuEntry",
    "label verb needs shown children count_suffix checkable",
    defaults=("", "any", "", "", False, ""),
)

#: A divider. The label is what makes it one, so a section places it
#: in its own table exactly where ui-text.md draws it.
SEPARATOR = MenuEntry("")

#: THE TAIL EVERY TILE MENU ENDS WITH, in the menu law's order (set
#: 2026-07-31 on the contextual-menu base, recorded in ui-text.md):
#: the tile's presentation, then Favorite, then Delete last of all.
#:
#: It was written five times. Two of the five carried an entry the
#: section could not honour and one was missing an entry it could -
#: Code offered Update Preview for a day over a preview that is
#: painted from its own text, and had none for the month before that.
#: Both facts are declared per section now and the tail asks them.
GRID_MENU_TAIL = (
    MenuEntry("Update Preview", verb="menu_update_preview",
              shown="menu_offers_preview"),
    MenuEntry("Customize", verb="menu_customize"),
    MenuEntry("Favorite", verb="menu_favourite"),
    MenuEntry("Delete", verb="menu_delete", shown="deletes_rows"),
)


class Section:
    """Base protocol. A section is constructed with the panel and reads
    the panel's already-built models by attribute name."""

    key = ""
    #: The tab's human label. Lives HERE because three places used to
    #: carry their own copy of the (key, label) list - the tab strip and
    #: two in the Preferences dialog - and the two in Preferences were
    #: never updated when "hip" was added. Toggling ANY section then
    #: rebuilt enabled_sections from a six-entry list and dropped HIP,
    #: permanently and with no way to switch it back on. One list.
    label = ""

    # -- WHAT THIS CONTEXT OFFERS THE TOOLBAR ------------------------
    #
    # One fact per control, read by `MatLibPanel.TOOLBAR_CONTROLS`.
    # These were five sync methods that could disagree, because each
    # carried its own idea of which context it was in - three of them
    # by asking `_is_online()` and one by testing `key == "file"` from
    # inside the activation path.

    #: Does the Comments pane have anything to point at here? A comment
    #: is written against a library asset, and the online world has
    #: none. Deliberately NOT the same question as `comment_subject`
    #: below: this one answers with nothing selected, which is what the
    #: toolbar chip needs.
    takes_comments = True
    #: Does a record here carry a favourite state? An online one does
    #: not - the role always answers False, so the star would filter
    #: the grid to nothing.
    takes_favourites = True
    #: Does the Filter menu have entries that mean anything here? Its
    #: entries describe the LOCAL section underneath - renderers,
    #: palette sizes, file kinds - and an online result answers to
    #: none of them; the online browser has its sources in the tab
    #: strip instead.
    takes_filter_menu = True
    #: Capture acts on the open SCENE, so it belongs where scene tiles
    #: live and nowhere else.
    takes_capture = False

    #: WHAT THIS SECTION IS CALLED IN A SENTENCE, plural. The shared
    #: empty-state blanks read it, so they can say what is missing
    #: without a table of their own.
    empty_noun = "items"
    #: THE ONE BLANK THAT DIFFERS PER SECTION: `nothing-yet`, as
    #: (headline, sentence, button label, verb). How you put something
    #: in is the only thing that changes between sections, so the other
    #: three blanks live once in `empty_state.SHARED`. A blank verb
    #: means no button - which is right wherever the gesture belongs to
    #: the network editor rather than to this panel. The words are in
    #: `docs/architecture/ui-text.md`.
    EMPTY: dict = {}

    #: THE FOUR AREAS, as data. What this context binds into each one -
    #: named here so a caller never spells a model out, and so a
    #: section that arrives with a delegate of its own joins every
    #: sweep by existing rather than by being remembered.
    sidebar_attr = ""
    delegate_attr = ""

    #: THE SECTION'S LIBRARY-BACKED MODELS, by panel attribute name -
    #: the ones holding data read from `prefs.dir`, which must be
    #: re-pointed when the library changes. Declared HERE, by the
    #: section that owns them, and walked by `panel.switch_all_models`
    #: through `panel.library_models()`; there is no list of them in
    #: panel.py any more.
    #:
    #: It was three hand-written lists there, each naming seven models
    #: where there are eight - and the missing one was the Colors
    #: sidebar, so a library switch left it showing the previous
    #: library's categories with the new library's counts. A section
    #: that arrives with a model of its own now joins by declaring it,
    #: and `test_area_bindings` fails a model that carries
    #: `switch_model_data` and appears in no declaration.
    #:
    #: EMPTY IS A REAL ANSWER: the File section's data is folders on
    #: disk, registered per machine, and does not move with the
    #: library.
    library_model_attrs: tuple = ()
    #: The Grid's selection model. Named here because a menu acts on
    #: THIS section's selection, whatever the shared view happens to
    #: be pointed at.
    selection_attr = ""
    #: Name of the panel method that points the widgets at this section's
    #: models. Kept on the panel for now (see module docstring).
    activate_method = ""
    #: THIS SECTION'S GRID RIGHT-CLICK MENU, as rows of MenuEntry.
    #: Empty = no menu opens. Rendered by panel/grid.py, which is the
    #: only code that reads it.
    GRID_MENU: tuple = ()
    #: THIS SECTION'S SIDEBAR RIGHT-CLICK MENU, same shape, same
    #: builder. Three hand-written menus until 2026-08-04.
    SIDEBAR_MENU: tuple = ()
    #: WHAT A GESTURE RELEASE DOES HERE - one DropRule, or None for a
    #: section that never arms a drag (the online catalogue). The File
    #: section declares per row KIND instead, in DROP_BY_KIND; a
    #: non-empty kind table wins over DROP. Read only by the gesture
    #: engine (GridGestureMixin).
    DROP = None
    DROP_BY_KIND: dict = {}

    #: THE CARRIER THIS SECTION CREATES on empty network space, when
    #: the answer is a constant. Code answers per language and per
    #: network kind instead, so it names a panel method in
    #: `carrier_type_verb` rather than a type here.
    #:
    #: ONE ANSWER, TWO READERS: the creator builds this type, and the
    #: DRAG GHOST draws its shape while the payload is still in the
    #: air. A ghost that asked its own question would be a second
    #: engine free to disagree with the drop it is promising.
    carrier_type = ""
    carrier_type_verb = ""
    #: What the shared Filter Box says while this section is active.
    #: Per-ARCHETYPE rather than per-section, because the archetype is
    #: what decides the answer: filter_text below understands ":tag",
    #: FolderSection matches a file name, and Colors also matches the
    #: color names inside a palette. Read by the panel on every section
    #: AND mode change - one box serving five tabs cannot be labelled
    #: once at construction.
    #:
    #: A NOUN PHRASE, no verb: the "Filter" label and the magnifier icon
    #: already name the control, so these say what is MATCHED. That also
    #: keeps every one of them inside the box, which is 200 code px at
    #: its widest and shrinks as the toolbar tightens. This base value is
    #: the fallback no shipped archetype uses - all four override it.
    search_hint = ""

    #: What the shared FILTER MENU offers while this section is active,
    #: as ((label, value), ...) AFTER the everything-entry - the panel
    #: puts that one in front, so no section repeats it. The value is
    #: whatever apply_filter below needs and NOTHING else reads it: the
    #: panel carries it from the menu to the section and never looks
    #: inside. Empty = this section has no filter and the button hides.
    FILTER_CHOICES: tuple = ()

    #: The everything-entry's label. Also what the menu falls back to
    #: when a remembered choice is no longer offered (a renderer
    #: switched off in Preferences, say).
    ALL_LABEL = "All"

    #: The filter button's hover text. Per SECTION, because what the
    #: menu narrows by is the one thing the entries cannot say on their
    #: own - "SOP" does not explain that it is where the setup was
    #: saved from.
    filter_tooltip = ""

    def __init__(self, panel) -> None:
        self.panel = panel

    # -- lifecycle --------------------------------------------------------

    def activate(self) -> None:
        getattr(self.panel, self.activate_method)()

    def rc_menu(self) -> None:
        """Build and exec this section's grid right-click menu.

        ONE builder over GRID_MENU. It used to name a panel method per
        section, which is how six menus came to answer the same five
        questions six different ways.
        """
        grid.open_grid_menu(self.panel, self)

    def grid_selection(self) -> list:
        """This section's grid selection, as ITS OWN proxy's indexes -
        ONE per row (grid_columns.selected_rows: in list mode a
        SelectRows selection answers one index per CELL, and a raw read
        acted on every row ten times).

        The shared view's selection model IS this one while the section
        is active, but a menu asks the section, not the widget - which
        is what lets a test drive one section's menu without the panel
        having switched to it.
        """
        return grid_columns.selected_rows(self._p(self.selection_attr))

    def tile_models(self):
        """(model, proxy) for the tile a menu is acting on - what the
        shared Customize handler needs.

        The pair was spelled out inside five right-click menus, and a
        test had to check by REGEX that none of them named a model the
        panel does not have, because a typo there is invisible until
        someone right-clicks that section."""
        return None, None

    def catlist_menu(self) -> None:
        """Build and exec this section's sidebar right-click menu -
        the same builder the Grid uses, over SIDEBAR_MENU."""
        grid.open_catlist_menu(self.panel, self)

    def sidebar_selection(self) -> list:
        """The Sidebar's selected rows. Its selection lives on the
        shared `cat_list`, which has no per-section selection model -
        unlike the Grid, where each section brings its own."""
        cat_list = getattr(self.panel, "cat_list", None)
        if cat_list is None:
            return []
        return list(cat_list.selectedIndexes())

    def edit_dialog(self) -> None:
        """Open this section's metadata/edit dialog, if it has one. The
        Section API's extension point for the Dialog concept (see
        docs/architecture/overview.md): a section owns its dialog like it
        owns its menu. Default: no dialog.

        DISPATCHED since 2026-08-03: the Material table's Info row
        names `menu_info`, which calls this rather than reaching past
        it into the panel. So a section that wants an Info entry adds
        one table row and an `edit_dialog` override, and edits nothing
        in panel.py - which is what this hook existed for and did not
        do while the menus were written there."""
        pass

    def prefs_changed(self) -> None:
        """Preferences just closed - a section showing live filesystem or
        render state re-scans here (the panel refreshes the shared
        models/looks itself). Default: nothing."""
        pass

    def save_node(self, node) -> None:
        """A scene node was dropped onto the panel (or otherwise handed
        in to save) while this section is active. Each section routes to
        its own save flow so the right dialog - with the right
        categories - opens. Default: explain why nothing happens, since
        the folder sections browse files on disk and have no node-save
        concept."""
        hou.ui.displayMessage(  # type: ignore
            "This section browses files on disk - a scene node can't "
            "be saved into it. Switch to Material, Color, Node or "
            "Code first."
        )

    # -- the curated-library stack (asset sections only) -----------------

    def stack(self):
        """(model, proxy, selection, categories) for the material
        machinery, or None for sections that don't use it."""
        return None

    # -- shared handlers dispatch here -----------------------------------

    def filter_text(self, text: str) -> None:
        pass

    def filter_favorites(self, on: bool) -> None:
        pass

    def filter_entries(self) -> tuple:
        """((label, value), ...) for the Filter menu, in menu order,
        the everything-entry first.

        A METHOD rather than a plain tuple because Materials' list is
        not fixed: it holds only the renderers switched on in
        Preferences, and that changes while the panel is open. Every
        other section answers from FILTER_CHOICES and never overrides
        this.

        The everything-entry's value is None, which every apply_filter
        below reads as "no filter" - the same shape the Materials menu
        already had, where All REMOVES the filter rather than storing a
        sentinel that accepts every row (2026-08-02).
        """
        if not self.FILTER_CHOICES:
            return ()
        return ((self.ALL_LABEL, None),) + tuple(self.FILTER_CHOICES)

    def apply_filter(self, value) -> None:
        """Narrow this section's grid to one entry's VALUE.

        The panel owns the menu, this owns what an entry MEANS - which
        is why the five sections can share one button while filtering
        on five unrelated things (a renderer, a palette size, a node
        context, a language, a file kind)."""
        pass

    def select_category(self, index) -> None:
        pass

    # -- the sidebar reorder contract ------------------------------------
    #
    # The press-hold gesture (panel/sidebar.py SidebarReorder) asks the
    # CONTEXT, never a list of section keys - the sidebar's own retired
    # CATEGORY_SECTIONS lesson. The sidebar shows the STORED order (the
    # name sort retired 2026-08-14), so a move is real data movement:
    # live while the mouse is down, persisted ONCE on release, put back
    # whole on Esc.
    #
    # The bodies below are the CATEGORY-sidebar form - a
    # CategoriesSidebarProxy over a Categories model, which is what
    # every `reorders_sidebar` section except File shows - written once
    # here rather than once per archetype. FolderSection overrides the
    # five for its folder rows; a context that answers False (Online)
    # never has them called.

    #: Whether this context's sidebar rows may be reordered at all.
    reorders_sidebar = False

    def _sidebar_categories(self):
        """(proxy, source Categories) behind this context's sidebar,
        or (None, None) where the sidebar is not that shape."""
        proxy = self._p(self.sidebar_attr)
        source = getattr(proxy, "sourceModel", lambda: None)()
        if source is None or not hasattr(source, "move_category"):
            return None, None
        return proxy, source

    def sidebar_movable(self, index) -> bool:
        """May THIS row be picked up? Everything below All may."""
        if not self.reorders_sidebar:
            return False
        if index is None or not index.isValid() or index.row() < 1:
            return False
        proxy, source = self._sidebar_categories()
        if proxy is None:
            return False
        raw = proxy.index(index.row(), 0).data(source.CatSortRole)
        return bool(raw) and raw != "_All"

    def move_sidebar_row(self, index, to_view_row: int) -> bool:
        """Move the row at `index` to VIEW row `to_view_row` - never
        above All (clamped, so a drag past the top parks the row at
        row 1 rather than refusing to follow the hand)."""
        proxy, source = self._sidebar_categories()
        if proxy is None or index is None or not index.isValid():
            return False
        to_view_row = max(1, min(int(to_view_row), proxy.rowCount() - 1))
        from_source = proxy.mapToSource(
            proxy.index(index.row(), 0)).row()
        to_source = proxy.mapToSource(
            proxy.index(to_view_row, 0)).row()
        return source.move_category(from_source, to_source)

    def sidebar_order_snapshot(self):
        """The order before the gesture - what Esc puts back."""
        _proxy, source = self._sidebar_categories()
        return None if source is None else source.order_snapshot()

    def restore_sidebar_order(self, snapshot) -> None:
        _proxy, source = self._sidebar_categories()
        if source is not None and snapshot is not None:
            source.restore_order(snapshot)

    def commit_sidebar_order(self) -> None:
        """One write per gesture, on release."""
        _proxy, source = self._sidebar_categories()
        if source is not None:
            source.save()

    def double_click(self, index) -> None:
        pass

    #: Does this context's Delete remove a LIBRARY record? File says
    #: no: its rows are files on disk that the section only browses.
    deletes_rows = False

    @staticmethod
    def delete_prompt(count: int, name: str = "") -> str:
        """What deleting `count` rows costs, in this section's terms.

        `name` is the single row's display name, for the one section
        whose approved copy quotes it (ui-text.md is the source for
        every user-facing string; Color says `Delete "<name>"?`).

        A STATIC method: it depends on nothing but the count, which is
        what makes the four sentences readable side by side and
        testable without building a panel.

        The one genuinely per-section part of Delete - a material's
        files, a node asset's networks, a snippet's applied code, a
        palette's applied ramps - and it carries the COUNT, because
        "the selected material(s)" never told anyone how many.
        """
        return ""

    def delete_rows(self, indexes) -> None:
        """Remove these SOURCE rows.

        HIGHEST ROW FIRST, always: a removal shifts every row below it,
        so ascending order deletes neighbours - and only ever on a
        multi-selection, which is how it survives hand-testing. Written
        four times before this, and a fifth section would have had to
        remember it.

        No `layoutAboutToBeChanged`/`layoutChanged` wrap around a
        structural removal: removeRow emits the real begin/endRemoveRows
        contract, and layering a layout-change pair around it hands the
        proxy dangling persistent indexes at the closing signal - a
        native segfault (crashed H21 live; H22's Qt tolerated it).
        """

    # -- the Sidebar area: a row's colour ---------------------------------

    #: What the colour picker calls itself here. A location is not a
    #: category, and the dialog title is the only place that shows.
    colour_title = "Category Color"

    def menu_set_colour(self, indexes, current, payload=None) -> None:
        """Both colour entries go through the panel's ONE gesture -
        the same one all three sidebars already shared before their
        MENUS did (2026-08-03 gave them one verb; this gives them one
        builder over it)."""
        self.panel.sidebar_set_colour(True)

    def menu_clear_colour(self, indexes, current, payload=None) -> None:
        self.panel.sidebar_set_colour(False)

    #: Can a TILE be dropped onto this sidebar to refile it? A drop on
    #: a category row recategorises the selection instead of importing
    #: it - which only means anything where the rows ARE categories.
    #: File says no: its rows are registered folders, and a file's
    #: location is where it sits on disk.
    #:
    #: It was `panel.CATEGORY_SECTIONS`, a tuple of section KEYS - the
    #: shape every other area shed in batches 4 to 9, still standing in
    #: the sidebar's drag-hover cluster (2026-08-04).
    takes_category_drops = False

    def accepts_category_drop(self, index, name: str) -> bool:
        """Is THIS row a legal drop target, beyond being a category?

        Asked after the shared rules (a real row, not "All"). Only
        Color has more to say - and the panel used to say it FOR it,
        by name, inside the shared helper.
        """
        return True

    def sidebar_key(self, index) -> str:
        """WHAT THIS SIDEBAR ROW IS KEYED BY - a category name for the
        asset and palette sidebars, a registered folder PATH for the
        File one. The key, never the label: a category shown as "WIP"
        is stored "_WIP", and a location shows a custom name over a
        path it is keyed by.
        """
        return ""

    def sidebar_colour(self, name: str) -> str:
        """The colour on this sidebar row, "" for none.

        `name` is the STORED name, never the displayed one: the sidebar
        shows "_WIP" as "WIP", and a colour written under the display
        name is one nothing ever reads.
        """
        return ""

    def set_sidebar_colour(self, name: str, colour: str) -> None:
        """Colour one sidebar row, or clear it with "".

        The context writes its own store AND repaints its own models -
        a sidebar colour is painted twice, on the row and on every tile
        filed under it, and a gesture that repaints one of them looks
        like it half-worked. Three stores stay three: a category
        colour lives in the library, a palette category's in
        gradients.json, a location's in prefs.
        """

    # -- the Grid area: verbs over the selection --------------------------

    def toggle_favourite(self, indexes) -> None:
        """Flip the star on every row in `indexes` (GRID indexes, this
        section's own proxy).

        One verb, one owner. This was written five times - once in each
        section's right-click handler - and the copies disagreed about
        more than the model method's name: three of them wrapped the
        call in `layoutAboutToBeChanged`/`layoutChanged` to force the
        grid to re-map, and two did not, so un-favouriting a File or
        Color tile with Favourites-only on left it in the grid with its
        star off. That re-map is the proxy's own invariant now
        (core/grid_proxy.py), so no caller carries it.

        Base: nothing to flip. The online world has rows but no
        favourite state, which is why its star is disabled.
        """

    #: Can a row here be re-rendered? Three menus offered Update
    #: Preview and a fourth forgot it - Code repaints its painted
    #: preview from the snippet's current content and had no way to
    #: ask. A palette answers False: it is drawn from its ramp, so
    #: there is nothing to re-render and the entry would lie.
    offers_preview_update = False

    def update_preview(self, indexes) -> None:
        """Re-render the thumbnail for every row in `indexes`."""

    def menu_offers_preview(self, indexes, current) -> bool:
        """Does THIS SELECTION have anything to re-render?

        Deliberately a second question beside `offers_preview_update`,
        for the same reason `comment_subject` sits beside
        `takes_comments` (batch 9): one answers about the SECTION with
        nothing selected, the other about the rows in hand. They agree
        everywhere but File, where the kinds in the selection decide -
        a scene capture is hand-framed and an OS icon has nothing to
        render, so the entry would lie on those rows.
        """
        return bool(self.offers_preview_update)

    # -- the Grid area: the menu's shared verbs ---------------------------
    #
    # The four entries every tile menu ends with. Each one hands the
    # selection to the panel entry point that already owns the verb -
    # so these are the only place a menu names one, and adding a
    # section adds no copy of any of them.

    def menu_update_preview(self, indexes, current, payload=None) -> None:
        self.panel.grid_update_preview(indexes)

    def menu_customize(self, indexes, current, payload=None) -> None:
        model, proxy = self.tile_models()
        if model is None or proxy is None:
            return
        self.panel.edit_tile_icon(model, proxy, indexes)

    def menu_favourite(self, indexes, current, payload=None) -> None:
        self.panel.grid_toggle_favourite(indexes)

    def menu_delete(self, indexes, current, payload=None) -> None:
        self.panel.grid_delete(indexes)

    # -- the Comments area ------------------------------------------------

    def comment_subject(self, index):
        """What the Comments pane points at for `index` - as
        (key, section, name, type, category, colour) - or None.

        Only this context can answer: the index belongs to ITS proxy,
        and every field behind it comes from ITS roles. The panel used
        to hold all three mappings in one method that branched on
        `key`, which is the shape batch 4 collapsed for activation and
        batch 8 for the toolbar. Comments is the fourth area, not the
        exception.

        None means "nothing to write against" and the pane clears -
        which is also the base answer, so a context that takes no
        comments needs nothing here.
        """
        return None

    # -- helper -----------------------------------------------------------

    def _p(self, attr):
        return getattr(self.panel, attr, None)


class AssetSection(Section):
    """Materials / Cop / Code: a MaterialLibrary-family model + a
    Categories sidebar, filtered by the MultiFilterProxyModel. All three
    share the same filter/favourite/category logic; they differ only in
    which models they name and what a double-click does."""

    #: The base's category-sidebar reorder bodies fit as written -
    #: `sidebar_attr` names a CategoriesSidebarProxy here.
    reorders_sidebar = True

    model_attr = ""
    proxy_attr = ""
    selection_attr = ""
    category_attr = ""
    #: The SIDEBAR's model - the categories PROXY, not `category_attr`,
    #: which is the raw model underneath it.
    sidebar_attr = ""
    #: The Grid's delegate. Only the File section named its own until
    #: 2026-08-03; the rest were spelled out inside four activation
    #: bodies in the panel, which is how the fourth delegate came to be
    #: in none of the three lists that sweep them.
    delegate_attr = ""
    #: ":tag" is the only way to reach tags from this box, and nothing
    #: else in the panel says so. "for tags" spells out what the bare
    #: token means - ":tag" alone is a shape, not an instruction.
    search_hint = ""

    def activate(self) -> None:
        """Point the four shared widgets at THIS section's models.

        Materials, Node and Code had a copy of this each inside the
        panel - identical but for which models they named, so a fix to
        one had to be remembered for the other two. It was not: the
        delegate each of them named was spelled out here, which is how
        `asset_delegate` came to be in none of the three lists that
        sweep every tile delegate. The attributes above are the whole
        difference between them, exactly as `FolderSection.activate`
        already proved for the Folder archetype.
        """
        panel = self.panel
        sidebar = self._p(self.sidebar_attr)
        if panel.cat_list and sidebar is not None:
            panel.cat_list.setModel(sidebar)
        panel.bind_grid_views(self._p(self.proxy_attr),
                              self._p(self.selection_attr),
                              self._p(self.delegate_attr))
        # Not this section's bar: whichever section owned it last may
        # have left it visible, and it sits above the grid.
        panel.texture_progress.setVisible(False)
        # Different section = different names; re-fit the Name column.
        panel.sync_list_columns()

        # Start on the sidebar's first row and set the category filter
        # FROM the row that actually got selected, never from an
        # assumption about what sorts first. The programmatic select
        # does not fire clicked(), so the filter is applied explicitly -
        # and a blanket "" here while row 0 happened to be a real
        # category produced an "Abstract highlighted but everything
        # shown" mismatch on pre-migration data.
        #
        # _restore_section_state overrides it when it has a remembered
        # category that still exists, which is its job.
        selected_name = panel._select_default_sidebar_row(sidebar)
        model = self._p(self.model_attr)
        proxy = self._p(self.proxy_attr)
        if model is not None and proxy is not None:
            proxy.setFilter(
                model.CategoryRole,
                "" if selected_name in (None, "All", "_All")
                else selected_name,
            )

    takes_category_drops = True

    #: THE SIDEBAR SPINE, shared whole by Material, Node and Code.
    #: Rename acts on ONE category and greys beside the others, which
    #: act on the whole selection - the Grid's selection law,
    #: unchanged, because it is the same law.
    SIDEBAR_MENU = (
        MenuEntry("Add Category", verb="menu_add_category",
                  needs="always"),
        MenuEntry("Rename", verb="menu_rename_category", needs="one"),
        MenuEntry("Remove", verb="menu_remove_category"),
        SEPARATOR,
        MenuEntry("Set Color", verb="menu_set_colour"),
        MenuEntry("Clear Color", verb="menu_clear_colour"),
    )

    def menu_add_category(self, indexes, current, payload=None) -> None:
        st = self.stack()
        name = self.panel.ask_category_name("Add Category")
        if st is None or not name:
            return
        # NO relayout wrapper: check_add_category announces itself with
        # begin/endInsertRows, and pairing the two segfaults H21
        # (research.md, measured 2026-08-04) - the same hoist
        # panel.assign_category_active carries.
        st.categories.check_add_category(name)

    def menu_rename_category(self, indexes, current, payload=None) -> None:
        st = self.stack()
        new_name = self.panel.ask_category_name("Rename Category")
        if st is None or not new_name:
            return
        with ui_helpers.relayout(st.model, st.categories):
            for index in indexes:
                # The STORED name: the sidebar strips a leading
                # underscore for display, so renaming "_WIP" by its
                # label matched no asset and no entry and silently did
                # nothing.
                name = self.sidebar_key(index)
                if not name or name in ("All", "_All"):
                    continue
                st.model.rename_category(name, new_name)
                st.categories.rename_category(name, new_name)
            st.model.save()
        # THE GRID'S FILTER STILL NAMED THE OLD CATEGORY. The rename
        # rewrote every asset and the sidebar row, and left the proxy
        # narrowed to a name nothing carries any more - so the row read
        # correctly, stayed highlighted, and the grid went permanently
        # empty with nothing said, until another row was clicked.
        # Re-pointed through the ONE route a sidebar click uses, rather
        # than a second place that knows how a category becomes a
        # filter.
        self._refilter_from_sidebar()

    def _refilter_from_sidebar(self) -> None:
        """Point the grid at whatever the sidebar is standing on now.

        Both category verbs change what the current row MEANS, and the
        proxy holds the value it was given when the row was clicked.
        """
        cat_list = getattr(self.panel, "cat_list", None)
        if cat_list is None:
            return
        current = cat_list.currentIndex()
        if current.isValid():
            self.select_category(current)

    def menu_remove_category(self, indexes, current, payload=None) -> None:
        st = self.stack()
        if st is None:
            return
        # Stored names, same reason as the rename above:
        # remove_category returns early on its own
        # `cat not in self._categories` guard, so removing by the
        # label left the row exactly where it was.
        names = []
        for index in indexes:
            name = self.sidebar_key(index)
            if name and name not in ("All", "_All"):
                names.append(name)
        if not names:
            return
        if st.selection is not None:
            st.selection.clearSelection()
        with ui_helpers.relayout(st.model):
            for name in names:
                st.model.remove_category(name)
            st.model.save()
        # OUTSIDE the wrapper: remove_category announces itself with
        # begin/endRemoveRows, and pairing the two segfaults H21
        # (research.md, measured 2026-08-04). The asset rows changed
        # inside the wrapper; the sidebar rows change here, bracketed
        # by their own signals.
        for name in names:
            st.categories.remove_category(name)
        # THE ROW IS GONE AND THE FILTER WAS NOT. The grid stayed
        # narrowed to a category that no longer exists - zero tiles,
        # nothing highlighted, no message - and
        # `_ensure_sidebar_selection`, whose docstring says the sidebar
        # must never sit with an empty selection, was never called on
        # this path. It falls back to All and refilters; the re-point
        # below covers the case where the sidebar lands somewhere else.
        self.panel._ensure_sidebar_selection(self.key)
        self._refilter_from_sidebar()

    def tile_models(self):
        st = self.stack()
        return ((st.model, st.proxy) if st is not None
                else (None, None))

    def stack(self):
        model = self._p(self.model_attr)
        category = self._p(self.category_attr)
        if not model or not category:
            return None
        return AssetStack(
            model=model,
            proxy=self._p(self.proxy_attr),
            selection=self._p(self.selection_attr),
            categories=category,
        )

    def toggle_favourite(self, indexes) -> None:
        st = self.stack()
        if st is None:
            return
        for index in indexes:
            source = st.proxy.mapToSource(index)
            if source.isValid():
                st.model.toggle_fav(source)

    deletes_rows = True

    def delete_rows(self, indexes) -> None:
        st = self.stack()
        if st is None:
            return
        model = st.model
        for index in sorted(indexes, key=lambda i: i.row(), reverse=True):
            model.remove_asset(index)
        self.panel._refresh_sidebar_categories()

    def sidebar_key(self, index) -> str:
        # `_raw_category_name` is the ONE reader of a category row's
        # stored name - the underscore strip lives in Categories.data.
        return self.panel._raw_category_name(index)

    def sidebar_colour(self, name: str) -> str:
        st = self.stack()
        if st is None:
            return ""
        return st.categories.color_of(name)

    def set_sidebar_colour(self, name: str, colour: str) -> None:
        st = self.stack()
        if st is None:
            return
        st.categories.set_color(name, colour)
        # The grid reads the colour through a role on the ASSET model,
        # which shares the category model's data dict - so a repaint is
        # all that is needed. Role-scoped on purpose: a roles-less emit
        # over every row sends the list view into an O(rows) column
        # re-measure that a colour can never change, which the panel's
        # own tripwire logs as a "column re-measure storm".
        if st.model is not None and st.model.rowCount():
            st.model.dataChanged.emit(
                st.model.index(0, 0), st.model.index(st.model.rowCount() - 1, 0),
                [st.model.CategoryColorRole])

    offers_preview_update = True

    def update_preview(self, indexes) -> None:
        """Materials and Nodes re-render (the UI blocks for it); Code
        repaints from content. All three reach it the same way, which
        is why Code stops being the one that forgot."""
        st = self.stack()
        if st is None:
            return
        sources = [st.proxy.mapToSource(i) for i in indexes]
        sources = [s for s in sources if s.isValid()]
        if not sources:
            return
        batch = getattr(st.model, "render_thumbnails", None)
        if batch is None:
            # Code repaints from content and has no batch to share.
            for source in sources:
                st.model.render_thumbnail(source)
            return
        # ONE Karma scaffold for the whole selection - the stage
        # composition is identical per material and was being paid per
        # row (core/library.py > render_thumbnails).
        batch(sources)

    def comment_subject(self, index):
        st = self.stack()
        if st is None:
            return None
        source = st.proxy.mapToSource(index)
        if not source.isValid():
            return None
        asset_id = source.data(st.model.IdRole)
        if not asset_id:
            return None
        # An asset carries a LIST of categories; the pane's header has
        # room for one, and the first is the one the sidebar sorts it
        # under.
        categories = source.data(st.model.CategoryRole)
        if isinstance(categories, (list, tuple)):
            category = str(categories[0]) if categories else ""
        else:
            category = str(categories or "")
        return CommentSubject(
            # The model's own name for its store section, not this
            # class's key: three sections share these models, and the
            # store is keyed by what the model writes.
            key=notes.note_key(st.model.NOTES_SECTION, asset_id),
            section=self.label.lower(),
            name=source.data(QtCore.Qt.ItemDataRole.DisplayRole) or "",
            type=source.data(st.model.RendererLabelRole) or "",
            category=category,
            colour=str(source.data(st.model.CategoryColorRole) or ""),
        )

    def filter_text(self, text: str) -> None:
        st = self.stack()
        if st is None:
            return
        # setFilter/removeFilter invalidate the proxy themselves - the
        # old extra invalidate() + manual layout-change pair ran the
        # whole filter pass 2-3x per keystroke.
        # NO sort() after these: setFilter/removeFilter re-sort inside
        # GridProxyModel.refilter(), which is the whole reason that
        # method exists (core/grid_proxy.py). The
        # caller-side sort was left behind when sorting moved into the
        # proxy, so every keystroke sorted all rows TWICE - once in
        # refilter, once here - and paid a second layout-changed
        # repaint for it.
        if text.startswith(":"):
            # ":tag" searches the TagRole instead of the name.
            st.proxy.removeFilter(QtCore.Qt.ItemDataRole.DisplayRole)
            if len(text) > 1:
                st.proxy.setFilter(st.model.TagRole, text[1:])
            else:
                # A BARE COLON is a tag search with no tag yet, so it
                # narrows nothing. This branch used to be taken and
                # then fall through doing NOTHING - so backspacing a
                # tag search one character at a time left the grid on
                # the previous tag while the box showed only a colon,
                # and the two disagreed until the field was cleared.
                st.proxy.removeFilter(st.model.TagRole)
        else:
            st.proxy.removeFilter(st.model.TagRole)
            st.proxy.setFilter(QtCore.Qt.ItemDataRole.DisplayRole, text)

    def filter_favorites(self, on: bool) -> None:
        st = self.stack()
        if st is None:
            return
        st.proxy.setFilter(st.model.FavoriteRole, True if on else "")

    def apply_filter(self, value) -> None:
        """All three asset sections filter on RendererRole, because all
        three KEEP THEIR KIND IN THAT ONE FIELD: a renderer for
        Materials, the context a setup was saved from for Nodes
        ("Sop"/"Cop"/"Lop"...), the language for Code ("VEX"/"OpenCL"/
        "Python"). cop_library and code_library both say so in their
        module docstrings - the field was widened by those sections,
        not copied.

        That is why this method is here once and not three times, and
        why Nodes and Code needed no filtering machinery built at all:
        MultiFilterProxyModel matches on hard-coded role NUMBERS (259
        is RendererRole, and a filter set on any other role is silently
        ignored - research.md), so the route these three need already
        existed and was only ever driven from the Materials menu.

        None REMOVES the filter rather than storing a value that
        accepts everything: both reach the same yes, but a stored
        filter costs an index.data() per row on every pass forever, and
        removing it lets the proxy take its no-filters-at-all fast path.

        THE SIDEBAR IS PART OF THIS ROUTE, not a Materials extra. The
        push into the category model is what makes the sidebar list
        only categories holding a VISIBLE asset and count only those,
        and it used to hang off a MaterialSection override - so Node
        and Code inherited the grid half and not the sidebar half.
        Nothing ever called set_renderer_filter on their category
        models, `showing_all_renderers()` stayed True, every row was
        accepted and every asset counted: filter Node to SOP and a
        category holding three LOP setups still reads "MyCat (3)" and
        opens EMPTY - which CategoriesSidebarProxy's own docstring says
        cannot happen ("you can never click your way to an empty
        grid"). Hide Empty Categories had no effect on those two
        sidebars either.

        The override's comment said "Materials is the only section with
        renderer-aware category counts". That stopped being a decision
        the day the shared Filter menu gave Node and Code the same
        field; it was a description of the gap.
        """
        st = self.stack()
        if st is None:
            return
        if value is None:
            st.proxy.removeFilter(st.model.RendererRole)
        else:
            st.proxy.setFilter(st.model.RendererRole, value)
        # The PROXY's value, never the menu's label: Categories
        # lowercases what it is given and matches it as a SUBSTRING, so
        # the word "All" matches no renderer at all - measured
        # 2026-08-02 as every count reading 0 and, with Hide Empty
        # Categories on, every real category vanishing. "" is the
        # honest mirror of what the grid does with All.
        st.categories.set_renderer_filter(value or "")
        self.panel._refresh_sidebar_categories()
        self.panel._ensure_sidebar_selection(self.key)

    def select_category(self, index) -> None:
        """Narrow the grid to the clicked row's category.

        THE STORED NAME, never the displayed one. `Categories.data`
        returns `elem[1:]` for DisplayRole when the stored name begins
        with "_" - the mechanism that makes the stored `_All` sort
        first and read as "All" - so `index.data()` on a category
        stored `_WIP` gives "WIP", which no asset carries. The grid
        emptied, the row stayed highlighted, and nothing said why.

        `_raw_category_name` is the one home for this question, and its
        own docstring already lists three actions that were broken this
        exact way and were moved onto it: rename, remove, and dragging
        a tile onto the row. The sidebar CLICK was never moved. Reading
        the stored name here is that move, not a fourth copy - and
        `_category_filter_value` is what keeps `_All` meaning
        everything rather than a literal category nobody has.
        """
        st = self.stack()
        if st is None:
            return
        stored = self.panel._raw_category_name(index)
        st.proxy.setFilter(st.model.CategoryRole,
                        "" if stored in ("All", "_All") else stored)


class MaterialSection(AssetSection):
    key = "material"
    label = "Material"
    empty_noun = "material"
    #: No button: `save_asset` needs a selected node and says so when
    #: there is none, which is the normal state on an empty library.
    EMPTY = {
        "nothing-yet": (
            "No materials saved yet",
            "Right-click a material in the network editor and choose "
            "Save to Amaze. It is kept here, ready to drag back into "
            "any scene.",
            "", ""),
    }

    @staticmethod
    def delete_prompt(count: int, name: str = "") -> str:
        if count == 1:
            return ("Delete this material? Its saved files and "
                    "thumbnails go for good. Materials already used in "
                    "a scene are not affected.")
        return ("Delete %d materials? Their saved files and thumbnails "
                "go for good. Materials already used in a scene are "
                "not affected." % count)
    #: Info, the section's work, a divider, then the shared tail.
    #: Convert to Karma is the one CONDITIONAL entry: it exists only
    #: when the selection holds a Redshift material, which is also why
    #: the old menu needed an `is not None` guard before comparing
    #: against it - a dismissed menu and an unbuilt action are both
    #: None, and without the guard every dismissed right-click ran the
    #: converter. The builder dispatches through a dict instead.
    GRID_MENU = (
        MenuEntry("Info", verb="menu_info", needs="one"),
        MenuEntry("Copy To", verb="menu_copy_to", children="copy_to_targets"),
        MenuEntry("Convert to Karma", verb="menu_convert_to_karma",
                  shown="selection_has_redshift"),
        SEPARATOR,
    ) + GRID_MENU_TAIL

    #: A material import finds its own landing - the verb checks the
    #: release for a material library node or a network itself.
    DROP = DropRule(resolve="drop_material_at_release",
                    click_resolve="click_import_material")

    def click_import_material(self, _index) -> bool:
        """Materials aim themselves - the context-aware import reads
        the selection and the network under the cursor."""
        self.panel.import_asset("auto")
        return True

    def drop_material_at_release(self, index) -> bool:
        """Material drag released (Drag & Drop Engine gesture). THE
        LAW: the drop lands where it was dropped, and nothing was
        created before this moment.

        LOP viewport gets the ancestor-prim menu, an import into a
        materiallibrary in THAT stage and Houdini's stock assign,
        never /mat; OBJ viewport imports to /mat and assigns to the
        picked object directly; a network editor imports into the
        network under the cursor; anything else is a silent miss.

        Returns True for a hit, False for a miss, and the string
        "menu" when a menu carried the interaction - the drag widgets
        map this to the outcome icon."""
        panel = self.panel
        if not panel.material_model or index is None or not index.isValid():
            return False
        ids = panel._selected_material_ids(index)
        target = dragengine.viewport_release_target(panel)
        if target is not None:
            kind, viewer, data = target
            debug.event("drag", "material release", target=kind,
                        data=str(data), count=len(ids))
            if kind == "lop":
                if not data:
                    # Empty viewport space: no prim picked = a MISS,
                    # not an import offer.
                    return False
                shown = panel._material_lop_viewport_drop(ids, viewer, data)
                # The menu IS the feedback on this path - no outcome
                # icon on top of it, chosen or dismissed alike.
                #
                # But "menu" was returned unconditionally, and
                # _material_lop_viewport_drop returns False in three
                # cases where NO menu was ever shown: no stock LOP
                # helper, a viewer whose pwd() failed, and - the
                # reachable one - no choices at all, which happens on a
                # stale prim path or a display node whose cook failed.
                # _finish_preview reads "menu" as "suppress the miss
                # icon", so the user dropped on a visible object and got
                # nothing whatsoever: no menu, no red X, no message.
                return "menu" if shown is not False else False
            if kind == "obj" and data is not None:
                with hou.undos.group("Amaze Assign Material"), \
                        dragengine.keep_editor_focus():
                    # Propagated, not discarded: assign_material_to_obj
                    # returns False when the picked object has no
                    # shop_materialpath, and a hard True here showed the
                    # success feedback for an assignment that did not
                    # happen.
                    return bool(panel.assign_material_to_obj(ids, data))
            return False
        context = panel._drop_context_under_cursor("materiallibrary")
        if context is None:
            debug.event("drag", "material release", target="miss")
            return False
        debug.event("drag", "material release", target="network",
                    context=context.path(), count=len(ids))
        position = panel._release_position_in(context)
        panel._import_materials_into_context(context, ids, position)
        return True

    def selection_has_redshift(self, indexes, current) -> bool:
        return self.panel._selection_has_redshift()

    def copy_to_targets(self, indexes, current) -> tuple:
        """WHERE the saved material lands. The entries name the
        destination the way Houdini writes the PATH - /stage, not the
        Solaris marketing name (2026-08-08)."""
        return (("/mat", "mat", "", True),
                ("/stage", "lop", "", True))

    def menu_info(self, indexes, current, payload=None) -> None:
        # Through `edit_dialog`, the Section API's own hook for it -
        # its docstring said "NOTHING CALLS THIS" because the menu
        # reached past it into the panel. Something calls it now.
        self.edit_dialog()

    def menu_copy_to(self, indexes, current, payload=None) -> None:
        # A menu import leaves the artist where they were, like a drop:
        # the drag and click dispatchers wrap; the menu dispatcher does
        # not, so the scene-importing verbs carry it themselves.
        with helpers.preserving_selection_and_current():
            if payload == "lop":
                self.panel.import_asset_to_lop()
            else:
                self.panel.import_asset_to_mat()

    def menu_convert_to_karma(self, indexes, current, payload=None) -> None:
        self.panel.convert_selected_to_karma()

    def activate(self) -> None:
        """Materials alone has to remember the online world.

        Leaving the Materials tab and coming back must not silently
        drop out of the online browser: the button would still be
        amber, every online-aware handler would still take the online
        path, and the grid would be showing the local library.
        """
        if getattr(self.panel, "online_mode", False):
            self.panel.enter_online()
            return
        super().activate()

    library_model_attrs = ("material_model", "category_model")
    model_attr = "material_model"
    proxy_attr = "material_sorted_model"
    selection_attr = "material_selection_model"
    category_attr = "category_model"
    sidebar_attr = "category_sorted_model"
    delegate_attr = "thumb_delegate"
    filter_tooltip = "Show materials for one renderer."

    #: (label, the preference that decides whether it is offered). The
    #: labels are also the VALUES - they are matched against the
    #: renderer string stored on the material, so the two cannot drift.
    RENDERER_PREFS = (
        ("Karma", "renderer_matx_enabled"),
        ("Mantra", "renderer_mantra_enabled"),
        ("Redshift", "renderer_redshift_enabled"),
        ("Octane", "renderer_octane_enabled"),
    )

    def filter_entries(self) -> tuple:
        """The only section whose entries are not a constant: a
        renderer switched off in Preferences is not offered here.

        It used to be built once and then SHOWN and HIDDEN by
        update_renderer_toggles. Rebuilding says the same thing with
        one mechanism instead of two, and the "the checked one just
        disappeared" fallback stopped being special-cased here - the
        panel now falls back to All for any section whose remembered
        choice is no longer on offer.
        """
        prefs = self.panel.prefs
        return ((self.ALL_LABEL, None),) + tuple(
            (label, label) for label, flag in self.RENDERER_PREFS
            if getattr(prefs, flag, False)
        )

    def double_click(self, index) -> None:
        self.panel.click_on_row(self, index)

    def edit_dialog(self) -> None:
        self.panel.edit_material_info()

    def save_node(self, node) -> None:
        # Materials support multi-selection saves, so the flow is
        # selection-based - the drop handler selects the node first.
        self.panel.save_asset()


class CopSection(AssetSection):
    @staticmethod
    def delete_prompt(count: int, name: str = "") -> str:
        if count == 1:
            return ("Delete this node asset? Its saved files and "
                    "thumbnail go for good. Networks already built in "
                    "a scene are not affected.")
        return ("Delete %d node assets? Their saved files and "
                "thumbnails go for good. Networks already built in a "
                "scene are not affected." % count)

    key = "cop"
    label = "Node"
    empty_noun = "node asset"
    #: No button, for the same reason as Material.
    EMPTY = {
        "nothing-yet": (
            "No node assets saved yet",
            "Select nodes in a network, right-click and choose Save to "
            "Amaze. The whole network is kept, ready to build back in.",
            "", ""),
    }
    #: The material menu's essentials without the renderer-specific
    #: entries (Copy To targets, Karma conversion) that mean nothing
    #: for a saved network. LOAD, not Import (2026-08-01): the File
    #: section already uses Load for "bring the saved thing into
    #: Houdini", and any number of networks can be built - so unlike
    #: File's Load this one stays live on a multi-selection.
    GRID_MENU = (
        MenuEntry("Load", verb="menu_load"),
        SEPARATOR,
    ) + GRID_MENU_TAIL

    #: A saved network builds where the context allows - the verb
    #: resolves the destination itself (fill rule, approved).
    DROP = DropRule(resolve="drop_cop_at_release",
                    click_resolve="click_import_cop")

    def click_import_cop(self, _index) -> bool:
        self.panel.import_cop_assets()
        return True

    def drop_cop_at_release(self, index) -> bool:
        """Nodes drag released: same context rules as double-click, but
        against the network editor under the RELEASE POINT - released
        ON a network container (a geo, a copnet, a lopnet...) or INSIDE
        one, the saved nodes load directly into it; any other network
        gets a fresh container. An asset whose context doesn't match
        where it landed is refused with a message rather than half
        created. A release over nothing is silent - a miss is a normal
        drag outcome, not an error."""
        panel = self.panel
        if not panel.cop_model:
            return False
        if index is None or not index.isValid():
            # A drag armed on EMPTY grid space arrives here with an
            # invalid index; mapToSource() would return row -1, which
            # Python-indexes to the LAST asset in the model.
            return False
        context = panel._drop_context_under_cursor(
            panel.cop_model.is_container)
        if context is None:
            return False
        try:
            source_index = panel.cop_sorted_model.mapToSource(index)
        except Exception:
            return False
        with hou.undos.group("Amaze Import COP Network"):
            ok, reason, created = panel.cop_model.import_asset_to_scene(
                source_index, context_node=context
            )
        if not ok and reason:
            hou.ui.displayMessage(reason)  # type: ignore
        if ok:
            helpers.place_nodes(created,
                                panel._release_position_in(context))
        return True

    def menu_load(self, indexes, current, payload=None) -> None:
        # Same wrapper as menu_copy_to: a menu import must not move
        # the artist's selection, current node or view.
        with helpers.preserving_selection_and_current():
            self.panel.import_cop_assets()
    library_model_attrs = ("cop_model", "cop_category_model")
    model_attr = "cop_model"
    proxy_attr = "cop_sorted_model"
    selection_attr = "cop_selection_model"
    category_attr = "cop_category_model"
    sidebar_attr = "cop_category_sorted_model"
    # NOT thumb_delegate: Node and Code have no versions, and a shared
    # delegate painted a "Version" column reading "none" on every row.
    delegate_attr = "asset_delegate"
    filter_tooltip = "Show setups saved from one context."

    #: The contexts this section saves, spelled the way Houdini's own
    #: network tabs do. CopLibrary.SAVE_CONTEXTS is the same list in
    #: Houdini's capitalisation ("Sop"); the match is case-insensitive,
    #: so these can read as the user sees them on the node itself.
    #: Assets saved before the section learned about contexts carry an
    #: empty one and appear under All only - there is nothing truthful
    #: to file them under.
    FILTER_CHOICES = (
        ("SOP", "Sop"),
        ("COP", "Cop"),
        ("LOP", "Lop"),
        ("DOP", "Dop"),
        ("TOP", "Top"),
        ("CHOP", "Chop"),
        ("Object", "Object"),
    )

    def double_click(self, index) -> None:
        self.panel.click_on_row(self, index)

    def save_node(self, node) -> None:
        self.panel.save_cop_from_node(node)


class CodeSection(AssetSection):
    #: NO Update Preview, for the same reason Color has none: this
    #: preview is DERIVED, not rendered. `_preview_key` is content
    #: addressed - ("code", id, hash(code), language) - so editing a
    #: snippet mints a new key and repaints on its own, and asking for
    #: a re-render repaints the same text to the same image. It was
    #: offered for one commit on a consistency argument and reported
    #: immediately as "it does nothing", which was exactly right.
    offers_preview_update = False

    @staticmethod
    def delete_prompt(count: int, name: str = "") -> str:
        if count == 1:
            return ("Delete this snippet? It goes for good. Code "
                    "already applied to a node is not affected.")
        return ("Delete %d snippets? They go for good. Code already "
                "applied to a node is not affected." % count)

    def delete_rows(self, indexes) -> None:
        # remove_asset already saves per row, like every sibling - this
        # extra save is the belt on the braces for a store that keeps
        # every snippet in ONE json, where a half-written removal loses
        # more than one row.
        super().delete_rows(indexes)
        self.panel.code_model.save()

    key = "code"
    label = "Code"
    empty_noun = "snippet"
    #: A button here, because New File acts on nothing and so always
    #: works - the same reason its menu entry stays live over an empty
    #: selection.
    EMPTY = {
        "nothing-yet": (
            "No snippets yet",
            "Right-click a wrangle and choose Save to Amaze to keep its "
            "code — or start one here and paste into it.",
            "New File", "new_code_snippet"),
    }
    #: New File is the one entry in any section that acts on NOTHING,
    #: so it is the one that stays live over an empty selection.
    #: Apply and Edit act on one snippet and grey out beside it.
    #: No Update Preview - `offers_preview_update` above says why.
    GRID_MENU = (
        MenuEntry("New File", verb="menu_new_snippet", needs="always"),
        SEPARATOR,
        MenuEntry("Apply", verb="menu_apply", needs="one"),
        MenuEntry("Edit", verb="menu_edit", needs="one"),
        SEPARATOR,
    ) + GRID_MENU_TAIL

    #: A snippet hands to the node under the release; on empty network
    #: space the carrier wrangle is created where supported.
    DROP = DropRule(on_node="drop_code_at_release",
                    on_space="create_code_node_in",
                    click_on_node="drop_code_at_release")

    #: Per language AND per network kind, so the answer is a method.
    carrier_type_verb = "code_carrier_type"

    #: What this section creates per language and per network kind -
    #: names from the shipped manual (sop/attribwrangle, cop/wrangle,
    #: lop/attribwrangle, sop+cop/opencl, sop/python). A pair absent
    #: here, or a type this Houdini does not carry, refuses.
    CODE_CARRIERS = {
        "vex": {"Sop": "attribwrangle", "Lop": "attribwrangle",
                "Cop": "wrangle"},
        "opencl": {"Sop": "opencl", "Cop": "opencl"},
        "python": {"Sop": "python"},
    }

    def code_carrier_type(self, index, dest) -> str:
        """WHICH carrier a snippet becomes in `dest` - a wrangle, an
        opencl, a python - or "" where this network kind has none.

        ONE ANSWER, TWO READERS: `create_code_node_in` builds it, and
        the drag ghost draws its shape before the drop happens. A
        ghost that computed its own type could promise a wrangle and
        deliver nothing.
        """
        panel = self.panel
        if index is None or not index.isValid() or not panel.code_model:
            return ""
        source_index = panel.code_sorted_model.mapToSource(index)
        row = source_index.row()
        if not 0 <= row < len(panel.code_model.assets) or dest is None:
            return ""
        asset = panel.code_model.assets[row]
        language = str(getattr(asset, "renderer", "") or "").lower()
        try:
            category = dest.childTypeCategory()
        except (AttributeError, hou.OperationFailed):
            return ""
        return self.CODE_CARRIERS.get(language, {}).get(
            category.name() if category is not None else "", "")

    def create_code_node_in(self, index, dest, position=None) -> bool:
        """The code creation rule: the language's own carrier - a
        wrangle, an opencl, a python - wherever the network kind has
        one, loaded through the same apply the node drop uses."""
        panel = self.panel
        if index is None or not index.isValid() or not panel.code_model:
            return False
        source_index = panel.code_sorted_model.mapToSource(index)
        row = source_index.row()
        if not 0 <= row < len(panel.code_model.assets):
            return False
        asset = panel.code_model.assets[row]
        type_name = self.code_carrier_type(index, dest)
        if not type_name:
            return False
        name = helpers.sanitize_usd_path(
            str(getattr(asset, "name", "") or "")) or "snippet"
        with hou.undos.group("Amaze Create Code Node"):
            node = panel._create_carrier(dest, type_name, name, position)
            if node is None:
                return False
            ok, _reason = panel.code_model.apply_to_node(row, node)
            if not ok:
                node.destroy()
                return False
        return True

    def drop_code_at_release(self, index, node: hou.Node) -> bool:
        """Code snippet drag released (self-managed): apply the snippet to
        the node under the cursor - same as a double-click, but targeting
        where the drag landed. A release over nothing is silent; a node
        with no code/snippet parm reports why."""
        panel = self.panel
        if not panel.code_model or index is None or node is None:
            return False
        try:
            source_index = panel.code_sorted_model.mapToSource(index)
        except Exception:
            return False
        with hou.undos.group("Amaze Apply Code Snippet"):
            ok, reason = panel.code_model.apply_to_node(
                source_index.row(), node
            )
        if not ok:
            # Drag-door rule: the miss indicator carries the refusal;
            # the reason goes to the status line, never a dialog.
            ui = getattr(hou, "ui", None)
            if ui is not None and reason:
                ui.setStatusMessage(
                    "Amaze: %s" % reason,
                    severity=hou.severityType.Warning,
                )
            return False
        return True

    def menu_new_snippet(self, indexes, current, payload=None) -> None:
        self.panel.new_code_snippet()

    def menu_apply(self, indexes, current, payload=None) -> None:
        # THE CLICK DOOR, not a second reading of the same policy.
        # This called a body that vetoed on a selected node with no
        # snippet parm, where the double-click beside it falls through
        # to the creation walk.
        self.panel.click_on_row(self, current)

    def menu_edit(self, indexes, current, payload=None) -> None:
        if current is None or not current.isValid():
            return
        source = self.panel.code_sorted_model.mapToSource(current)
        if source.isValid():
            self._edit_code_row(source.row())

    def _edit_code_row(self, row: int) -> None:
        panel = self.panel
        asset = panel.code_model.assets[row]
        dialog = code_dialog.CodeDialog(
            panel.get_code_category_names(),
            name=asset.name,
            language=asset.renderer,
            category=asset.categories[0] if asset.categories else "",
            tags=", ".join(asset.tags),
            code=asset.code,
            description=asset.description,
            title="Edit Snippet",
        )
        dialog.exec_()
        if dialog.canceled:
            return
        if dialog.category:
            panel.code_category_model.check_add_category(dialog.category)
        with ui_helpers.relayout(panel.code_model,
                                 panel.code_category_model):
            panel.code_model.update_asset(
                row, dialog.code, dialog.name, dialog.language,
                dialog.category, dialog.tags, dialog.description,
            )
        panel._refresh_sidebar_categories()
    library_model_attrs = ("code_model", "code_category_model")
    model_attr = "code_model"
    proxy_attr = "code_sorted_model"
    selection_attr = "code_selection_model"
    category_attr = "code_category_model"
    sidebar_attr = "code_category_sorted_model"
    delegate_attr = "asset_delegate"
    filter_tooltip = "Show snippets in one language."

    #: The same four the Save dialog offers (code_dialog.LANGUAGES),
    #: with "Code" the catch-all a snippet lands in when nothing more
    #: specific fits. Not imported from there: this list is what the
    #: STORED strings are, and a dialog is free to stop offering one
    #: while snippets saved under it are still in the library.
    FILTER_CHOICES = (
        ("VEX", "VEX"),
        ("OpenCL", "OpenCL"),
        ("Python", "Python"),
        ("Code", "Code"),
    )

    def double_click(self, index) -> None:
        self.panel.click_on_row(self, index)

    def save_node(self, node) -> None:
        self.panel.save_code_from_node(node)


class FolderSection(Section):
    """A folder-pointer list + a files model, filtered by
    TextureFilterProxyModel. Selecting a folder browses its files;
    there is no category machinery (stack() is None). One shipped
    subclass since the merge: FileSection."""

    files_proxy_attr = ""
    folders_attr = ""
    files_attr = ""
    #: Prefs method that stores a location's colour.
    colour_pref_setter = ""
    last_folder_pref = ""
    #: The rest of what activate() varies on: the selection model and
    #: delegate to point the shared grid at, and the prefs list of
    #: registered folders behind last_folder_pref.
    selection_attr = ""
    delegate_attr = ""
    folders_pref = ""
    #: These tiles are files on disk with no tags and no categories, so
    #: the file name is genuinely all there is to match.
    search_hint = ""

    def filter_text(self, text: str) -> None:
        proxy = self._p(self.files_proxy_attr)
        if proxy is not None:
            proxy.set_name_filter(text)

    def filter_favorites(self, on: bool) -> None:
        proxy = self._p(self.files_proxy_attr)
        if proxy is not None:
            proxy.set_favorites_only(on)

    def apply_filter(self, value) -> None:
        proxy = self._p(self.files_proxy_attr)
        if proxy is not None:
            proxy.set_kind_filter(value)

    # -- the sidebar reorder contract, in FOLDER terms -------------------
    #
    # Same gesture, same one-write-on-release rule as the category
    # form; the rows are registered locations and the truth moves
    # through the FolderListModel's named prefs calls. The order is
    # this machine's own (locations.py ▸ the ORDER paragraph), so a
    # reorder here never reshuffles another machine's sidebar.

    reorders_sidebar = True

    def sidebar_movable(self, index) -> bool:
        model = self._p(self.sidebar_attr)
        if model is None or index is None or not index.isValid():
            return False
        # Row 0 is the synthetic All row; everything below it is real.
        return 1 <= index.row() <= len(model._folders())

    def move_sidebar_row(self, index, to_view_row: int) -> bool:
        model = self._p(self.sidebar_attr)
        if model is None or index is None or not index.isValid():
            return False
        to_view_row = max(1, min(int(to_view_row), model.rowCount() - 1))
        return model.move_folder(index.row(), to_view_row)

    def sidebar_order_snapshot(self):
        model = self._p(self.sidebar_attr)
        return None if model is None else list(model._folders())

    def restore_sidebar_order(self, snapshot) -> None:
        model = self._p(self.sidebar_attr)
        if model is not None and snapshot is not None:
            model.restore_folder_order(snapshot)

    def commit_sidebar_order(self) -> None:
        from amaze.core import locations
        locations.commit_registered_order(self.panel.prefs)

    def activate(self) -> None:
        """Point the shared list/grid widgets at this section's models
        and restore the folder the user last had open.

        Textures and Geometry had a copy of this each, 40 and 32 lines,
        identical but for which models they name - so a fix to one
        (the progress bar, the fallback row, the remembered folder)
        had to be remembered for the other. The attributes above are
        the whole difference.
        """
        panel = self.panel
        folders = self._p(self.folders_attr)
        folders.refresh_counts()
        if panel.cat_list:
            panel.cat_list.setModel(folders)
        panel.bind_grid_views(self._p(self.files_proxy_attr),
                              self._p(self.selection_attr),
                              self._p(self.delegate_attr))
        # Not this section's bar: whichever section owned it last may
        # have left it visible, and it sits above the grid.
        panel.texture_progress.setVisible(False)
        # Different section = different names; re-fit the Name column.
        panel.sync_list_columns()

        # cat_list has no persistent selection model of its own (unlike
        # thumblist), so setModel() above always leaves it with nothing
        # selected - auto-select something so the grid isn't left blank
        # with nothing highlighted every time this section opens.
        # Restores the last folder (or "All") the user actually picked,
        # persisted in prefs so it survives both a tab switch within
        # this session and a full Houdini relaunch; falls back to the
        # first REAL folder (not "All") if nothing has been picked yet,
        # or if the remembered folder was since removed - "All" eagerly
        # scans and queues thumbnails for every registered folder at
        # once, which should not happen by surprise as the default.
        registered = getattr(panel.prefs, self.folders_pref, []) or []
        target_row = 1 if folders.rowCount() > 1 else 0
        last = getattr(panel.prefs, self.last_folder_pref, "")
        if last == folders.ALL_LABEL:
            target_row = 0
        elif last and last in registered:
            target_row = registered.index(last) + 1
        if panel.cat_list and folders.rowCount() > 0:
            target_index = folders.index(target_row, 0)
            selection_model = panel.cat_list.selectionModel()
            if selection_model is not None:
                selection_model.select(
                    target_index,
                    QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect,
                )
                panel.cat_list.setCurrentIndex(target_index)
            panel.update_selected_cat()

    def _browse(self, path) -> None:
        """Point the files model at a folder path (None = the synthetic
        'All' row), remember it, and persist."""
        files = self._p(self.files_attr)
        folders = self._p(self.folders_attr)
        if path is None:
            setattr(self.panel.prefs, self.last_folder_pref, folders.ALL_LABEL)
            files.set_all_folders()
        else:
            setattr(self.panel.prefs, self.last_folder_pref, path)
            files.set_folder(path)
        self.panel.prefs.save()

    def select_category(self, index) -> None:
        folders = self._p(self.folders_attr)
        self._browse(index.data(folders.PathRole))

    def location_for(self, path: str):
        """(location, label, colour) for the registered location
        covering this path - label per the location's own display rule
        (custom name, else the path), colour from Set Color.

        Longest prefix wins, because a location registered INSIDE
        another one is the more specific answer for a file under it.
        """
        folders = self._p(self.folders_attr)
        registered = getattr(self.panel.prefs, self.folders_pref, None) or ()
        canonical = hostos.canonical_path_key(path)
        best = ""
        best_len = 0
        for folder in registered:
            prefix = hostos.canonical_path_key(folder).rstrip("/") + "/"
            # Both lengths are of the CANONICAL prefix. Comparing one
            # against the raw folder made the longest-prefix rule read
            # two different strings, so a nested location could lose to
            # its own parent purely on how canonicalising changed it.
            if canonical.startswith(prefix) and len(prefix) > best_len:
                best, best_len = folder, len(prefix)
        if not best or folders is None:
            return FileLocation(path="", label="", colour="")
        # display_name and folder_color are the folder model's, and it
        # is the one that already answers both for the sidebar.
        return FileLocation(path=best,
                            label=folders.display_name(best),
                            colour=folders.folder_color(best))

    def tile_models(self):
        return self._p(self.files_attr), self._p(self.files_proxy_attr)

    # -- the Grid menu: the one table whose entries depend on the KIND
    #    of the rows in hand rather than on how many there are --------

    def selected_kinds(self, indexes) -> set:
        """Every KIND in the selection. One read for the whole menu -
        the old one asked the model three separate times and built the
        set twice."""
        files = self._p(self.files_attr)
        if files is None:
            return set()
        return {index.data(files.KindRole) or "" for index in indexes}

    def _path_of(self, index) -> str:
        files = self._p(self.files_attr)
        if files is None or index is None or not index.isValid():
            return ""
        return str(index.data(files.PathRole) or "")

    def selection_has_importable(self, indexes, current) -> bool:
        return bool(self.selected_kinds(indexes)
                    & {file_library.KIND_IMAGE, file_library.KIND_GEO})

    def selection_has_scene(self, indexes, current) -> bool:
        return file_library.KIND_HIP in self.selected_kinds(indexes)

    def menu_offers_preview(self, indexes, current) -> bool:
        """A capture is hand-framed and only a new capture replaces it;
        an OS icon has nothing to regenerate. So this section CAN
        re-render (`offers_preview_update` is True) while a particular
        selection cannot."""
        return (self.offers_preview_update
                and self.selection_has_importable(indexes, current))

    def menu_import_enabled(self, indexes, current) -> bool:
        """An image loads onto ONE node parameter, so images import one
        at a time; geometry imports the whole selection."""
        kinds = self.selected_kinds(indexes)
        return len(indexes) == 1 or kinds == {file_library.KIND_GEO}

    def menu_capture_enabled(self, indexes, current) -> bool:
        """Only the scene the VIEWPORT is showing can be captured: the
        capture photographs the viewport, so capturing while a
        different scene is open would file that picture under the wrong
        name - silently, and the result looks perfectly plausible.

        THE SAME TEST THE SHARED PATH MAKES, and no more. This was the
        third copy of the gate and the only one that kept the retired
        extra requirement that AMAZE had opened the scene, so a scene
        opened through File > Open, a recent-files entry or a crash
        recovery was capturable from the toolbar and greyed out on its
        own tile, with no explanation anywhere.
        """
        path = self._path_of(current)
        return (len(indexes) == 1 and bool(path)
                and path == scene_captures.current_scene_path())

    def menu_import(self, indexes, current, payload=None) -> None:
        files = self._p(self.files_attr)
        if files is None:
            return
        if self.selected_kinds(indexes) == {file_library.KIND_IMAGE}:
            # The click door, same as a double-click on the row: the
            # old call vetoed on a selected node with no file parm.
            self.panel.click_on_row(self, current)
            return
        for index in indexes:
            if index.data(files.KindRole) == file_library.KIND_GEO:
                self.panel.import_geo_asset(index)

    def menu_load_scene(self, indexes, current, payload=None) -> None:
        self.panel.open_hip_scene(current)

    def menu_copy_path(self, indexes, current, payload=None) -> None:
        self.panel.copy_file_paths(indexes)

    def menu_reveal(self, indexes, current, payload=None) -> None:
        path = self._path_of(current)
        if not path:
            return
        try:
            hostos.reveal_path(path)
        except Exception as exc:                         # noqa: BLE001
            debug.event("file", "reveal failed", error=str(exc))

    def menu_capture(self, indexes, current, payload=None) -> None:
        self.panel.capture_hip_thumbnail(current)

    def toggle_favourite(self, indexes) -> None:
        """Keyed by PATH here, so the model takes a row and resolves it
        itself - the same shape, a different key."""
        files = self._p(self.files_attr)
        proxy = self._p(self.files_proxy_attr)
        if files is None or proxy is None:
            return
        for index in indexes:
            source = proxy.mapToSource(index)
            if source.isValid():
                files.toggle_favorite(source.row())

    colour_title = "Location Color"

    def sidebar_key(self, index) -> str:
        """A location's key is its PATH. The row shows a custom name
        when one is set, so the label is not it."""
        folders = self._p(self.folders_attr)
        if folders is None or index is None or not index.isValid():
            return ""
        return str(index.data(folders.PathRole) or "")

    def sidebar_colour(self, name: str) -> str:
        """`name` is a registered folder PATH here - the sidebar's key
        in this archetype - and the folder model already answers this
        for its own rows."""
        folders = self._p(self.folders_attr)
        return folders.folder_color(name) if folders is not None else ""

    def set_sidebar_colour(self, name: str, colour: str) -> None:
        folders = self._p(self.folders_attr)
        files = self._p(self.files_attr)
        setter = getattr(self.panel.prefs, self.colour_pref_setter, None)
        if setter is None:
            return
        setter(name, colour)
        if folders is not None:
            row = folders.row_of(name)
            if row is not None:
                index = folders.index(row, 0)
                folders.dataChanged.emit(index, index)
        # Every tile from that location repaints, role-scoped.
        if files is not None and files.rowCount():
            # Drop the paint-path colour cache BEFORE the repaint that
            # would re-fill it from the old answer.
            files.colours_changed()
            files.dataChanged.emit(
                files.index(0, 0), files.index(files.rowCount() - 1, 0),
                [files.CategoryColorRole])

    offers_preview_update = True

    def update_preview(self, indexes) -> None:
        """The files model re-renders a BATCH - image rows re-convert,
        scene rows re-read their capture - so the rows go over in one
        call rather than one at a time."""
        files = self._p(self.files_attr)
        proxy = self._p(self.files_proxy_attr)
        if files is None or proxy is None:
            return
        rows = [proxy.mapToSource(i).row() for i in indexes
                if proxy.mapToSource(i).isValid()]
        if rows:
            files.rerender_thumbnails(rows)

    def comment_subject(self, index):
        """A row here is a FILE, so its comment is keyed by its path -
        which is what makes a comment come back when the location is
        removed and registered again."""
        model = self._p(self.files_attr)
        proxy = self._p(self.files_proxy_attr)
        if model is None or proxy is None:
            return None
        source = proxy.mapToSource(index)
        if not source.isValid():
            return None
        path = model.file_key(source.row())
        if not path:
            return None
        location = self.location_for(path)
        return CommentSubject(
            key=notes.note_key(self.key, path),
            section=self.label.lower(),
            name=source.data(QtCore.Qt.ItemDataRole.DisplayRole) or "",
            type=source.data(model.FormatRole) or "",
            # A file has no category of its own; the header shows the
            # location it came from, in that location's colour.
            category=location.label,
            colour=location.colour,
        )


class FileSection(FolderSection):
    """File - the 2026-07-31 merge of Images, Geometry and HIP (the
    function-sheet decision, recorded in ROADMAP.md). One folder list,
    EVERY file shown, and each row behaves as its KIND:

    * image      - load onto a node (the Images behaviour)
    * geometry   - import in context (the Geometry behaviour)
    * hip        - open the scene (the HIP behaviour)
    * other      - Copy Path, as a Houdini path - the one honest action
                   for a file Houdini probably cannot open

    The kind dispatch is the archetype's own: `selected_kinds` reads
    FileFiles.KindRole once and the menu table above asks it which
    entries exist. The double-click routes the same way as every
    gesture: `double_click` hands the row to `panel.click_on_row`,
    which reads DROP_BY_KIND.
    """

    key = "file"
    label = "File"
    filter_tooltip = "Show one kind of file."
    empty_noun = "file"
    #: A button, because registering a folder is this panel's own
    #: gesture and needs nothing selected.
    EMPTY = {
        "nothing-yet": (
            "No folders added yet",
            "Add a folder of images, models or scenes and they show up "
            "here, ready to drag onto any parameter. Nothing is copied "
            "or moved.",
            "Add Folder", "add_file_folder_user"),
    }

    #: The three kinds this section KNOWS how to open, in the order
    #: file_library.kind_for tests them. A file it has no behaviour for
    #: is KIND_OTHER: those appear under All when Show Unknown Files is
    #: on, and get no entry of their own - "other" is the absence of a
    #: kind, not a fourth one to browse by.
    FILTER_CHOICES = (
        ("Images", file_library.KIND_IMAGE),
        ("Geometry", file_library.KIND_GEO),
        ("Hip", file_library.KIND_HIP),
    )

    #: The one KIND-aware table: the selection's kinds decide which
    #: primary actions exist, and the tail is the same as everywhere.
    #: NO Delete anywhere - `deletes_rows` is False, because these are
    #: the user's own files on disk (an os.remove here once deleted
    #: real production files).
    GRID_MENU = (
        MenuEntry("Import", verb="menu_import", needs="menu_import_enabled",
                  shown="selection_has_importable"),
        MenuEntry("Load", verb="menu_load_scene", needs="one",
                  shown="selection_has_scene"),
        MenuEntry("Copy Path", verb="menu_copy_path"),
        SEPARATOR,
        MenuEntry("Show Location", verb="menu_reveal", needs="one"),
        MenuEntry("Capture Preview", verb="menu_capture",
                  needs="menu_capture_enabled", shown="selection_has_scene"),
    ) + GRID_MENU_TAIL

    #: Per row KIND - the one section whose rows are different things.
    #: Every kind hands its spelled path to a node (ONE rule, no
    #: exceptions); what differs is the no-node door: geometry's import
    #: aims itself, a hip loads only outside the panel, an image
    #: creates its carrier on network space, anything else misses.
    #: The un-kinded "" row is a real case (a model that answers no
    #: KindRole) and behaves like unknown.
    #: An unknown file has no scene behaviour at all - its one
    #: click action is Copy Path (the function sheet).
    _PATH_ONLY = DropRule(on_node="drop_file_path_on_node",
                          click_resolve="click_copy_path")
    DROP_BY_KIND = {
        file_library.KIND_IMAGE: DropRule(
            on_node="drop_file_path_on_node",
            on_space="create_image_node_in",
            click_on_node="drop_file_path_on_node",
            # The ghost draws THIS while the image is still in the air.
            carrier_type="mtlximage"),
        file_library.KIND_GEO: DropRule(
            on_node="drop_file_path_on_node",
            resolve="drop_geo_at_release",
            click_on_node="drop_file_path_on_node",
            click_resolve="click_import_geo"),
        file_library.KIND_HIP: DropRule(
            on_node="drop_file_path_on_node",
            outside="open_hip_scene",
            click_resolve="click_open_hip"),
        file_library.KIND_OTHER: _PATH_ONLY,
        "": _PATH_ONLY,
    }

    def click_import_geo(self, index) -> bool:
        self.panel.import_geo_asset(index)
        return True

    def drop_geo_at_release(self, index: QtCore.QModelIndex) -> bool:
        """Geometry drag released: import in context at the release
        point - on a SOP-capable node (geo, SOP Create) the loader
        lands inside it; an OBJ network gets a new geo; a LOP network
        a new SOP Create. Release over nothing is silent - a miss is a
        normal drag outcome, not an error."""
        panel = self.panel
        context = panel._drop_context_under_cursor(
            panel._is_sop_container, include_viewports=True
        )
        if context is None:
            return False
        path = index.data(panel.file_files_model.PathRole)
        if not path:
            return False
        with hou.undos.group("Amaze Import Geometry"):
            created = panel._import_geo_in_context(path, context)
        if created is not None:
            helpers.place_nodes([created],
                                panel._release_position_in(context))
        return True

    def click_open_hip(self, index) -> bool:
        self.open_hip_scene(index)
        return True

    def open_hip_scene(self, index) -> None:
        """Open a scene file from the grid.

        Houdini's own save prompt is left in charge of unsaved changes -
        re-implementing that dialog would be a second, worse copy of a
        decision the user already has a well-known answer for.
        """
        path = self.panel._hip_path_for(index)
        if not path:
            return
        if not os.path.isfile(path):
            hou.ui.displayMessage(  # type: ignore
                "That scene file is no longer there:\n%s" % path,
                severity=hou.severityType.Warning)
            debug.event("hip", "scene missing", file=path)
            return
        try:
            hou.hipFile.load(path, suppress_save_prompt=False,
                             ignore_load_warnings=False)
        except hou.LoadWarning as warn:
            # A scene that loads WITH warnings is still open and still
            # worth a thumbnail - missing assets are the normal state of
            # an old library, not a failure to open.
            debug.event("hip", "opened with warnings", file=path,
                        warning=str(warn)[:400])
        except Exception as exc:                         # noqa: BLE001
            hou.ui.displayMessage(  # type: ignore
                "Could not open that scene:\n%s\n\n%s" % (path, exc),
                severity=hou.severityType.Error)
            debug.event("hip", "open failed", file=path, error=str(exc))
            return
        scene_captures.note_opened(path)
        debug.event("hip", "scene opened", file=path)

    def drop_file_path_on_node(self, index, node) -> bool:
        """A File row released on a node: the node's FIRST file
        parameter takes the spelled path - the same act as selecting
        the node and double-clicking the row, aimed by the cursor
        instead of the selection. Uniform across kinds, unknown files
        included (ROADMAP - the interaction matrix, 2026-08-07). A
        node with no file parameter answers
        False, so the gesture shows its own refusal - the miss
        indicator and the tag flying home - never a dialog; the status
        line carries the why."""
        panel = self.panel
        path = index.data(panel.file_files_model.PathRole)
        if not path:
            return False
        parm = helpers.find_file_parm(node)
        if parm is None:
            ui = getattr(hou, "ui", None)
            if ui is not None:
                ui.setStatusMessage(
                    "Amaze: %s has no file parameter to take %s"
                    % (node.name(), os.path.basename(path)),
                    severity=hou.severityType.Warning,
                )
            return False
        with hou.undos.group("Amaze Set File Path"):
            parm.set(panel._scene_path(path))
        return True

    def create_image_node_in(self, index, dest, position=None) -> bool:
        """The image creation rule: a release on empty network space
        (or a double-click with nothing selected) makes a mtlximage
        carrying the spelled path, wherever the network can hold one."""
        panel = self.panel
        path = index.data(panel.file_files_model.PathRole)
        if not path:
            return False
        base = helpers.sanitize_usd_path(
            os.path.splitext(os.path.basename(path))[0]) or "image"
        with hou.undos.group("Amaze Create Image Node"):
            node = panel._create_carrier(dest, "mtlximage", base, position)
            if node is None:
                return False
            parm = helpers.find_file_parm(node)
            if parm is None:
                node.destroy()
                return False
            parm.set(panel._scene_path(path))
        return True

    def click_copy_path(self, index) -> bool:
        """An unknown file has no scene behaviour - its one action."""
        self.panel.copy_file_paths([index])
        return True

    #: The same spine with a location's own vocabulary: Rename is a
    #: LABEL submenu (a location is not a category - Add sets a custom
    #: name for the link, Remove clears it back to the path), Locate
    #: repoints a moved folder, and two per-location TOGGLES sit
    #: between. The per-location entries need a real row: "All" is
    #: synthetic, so `sidebar_key` answers "" there.
    #:
    #: Show All Files is the one entry that means something on the All
    #: row too - there the tick IS the global preference (Preferences
    #: ▸ Look), edited from here as well - so it alone stays live.
    SIDEBAR_MENU = (
        MenuEntry("Add Location", verb="menu_add_location",
                  needs="always"),
        MenuEntry("Remove", verb="menu_remove_location", needs="always"),
        MenuEntry("Locate", verb="menu_locate_location", needs="always"),
        MenuEntry("Label", verb="menu_label", children="label_actions",
                  needs="on_a_location"),
        SEPARATOR,
        MenuEntry("Show Subfolders", verb="menu_set_recursive",
                  needs="on_a_location", checkable="is_recursive"),
        MenuEntry("Show All Files", verb="menu_set_show_all",
                  needs="always", checkable="shows_all_files"),
        SEPARATOR,
        MenuEntry("Set Color", verb="menu_set_colour",
                  needs="on_a_location"),
        MenuEntry("Clear Color", verb="menu_clear_colour",
                  needs="on_a_location"),
    )

    def _selected_location(self, current) -> str:
        return self.sidebar_key(current) if current is not None else ""

    def on_a_location(self, indexes, current) -> bool:
        return bool(self._selected_location(current))

    def is_recursive(self, indexes, current) -> bool:
        path = self._selected_location(current)
        return bool(path) and path in self.panel.prefs.file_recursive_folders

    def shows_all_files(self, indexes, current) -> bool:
        path = self._selected_location(current)
        if path:
            return bool(file_library.shows_all_files(self.panel.prefs, path))
        return bool(self.panel.prefs.file_show_unknown)

    def label_actions(self, indexes, current) -> tuple:
        """Add sets a custom name for the location link; Remove clears
        it back to the default, which is the path itself - a rename
        must be reversible. Remove greys when there is nothing to
        remove, which is why the children are built per selection."""
        path = self._selected_location(current)
        named = bool(path and self.panel.prefs.file_folder_names.get(path))
        # Remove is always OFFERED and greys when there is no
        # label to remove - it vanished in the first version of this
        # table, which the before/after recording caught: the old menu
        # greyed it, and an entry that disappears moves the row under
        # the cursor between two right-clicks.
        return (("Add", "add", "", True),
                ("Remove", "remove", "", named))

    def menu_label(self, indexes, current, payload=None) -> None:
        path = self._selected_location(current)
        if not path:
            return
        if payload == "remove":
            name = ""
        else:
            name = self.panel.ask_category_name("Add Label")
            if name is None:
                return
        self.panel.prefs.set_file_folder_name(path, name)
        folders = self._p(self.folders_attr)
        row = folders.row_of(path) if folders is not None else None
        if folders is not None and row is not None:
            index = folders.index(row, 0)
            folders.dataChanged.emit(index, index)

    def menu_add_location(self, indexes, current, payload=None) -> None:
        self.panel.add_file_folder_user()

    def menu_remove_location(self, indexes, current, payload=None) -> None:
        self.panel.remove_file_folder_user()

    def menu_locate_location(self, indexes, current, payload=None) -> None:
        self.panel._locate_folder_user(self._p(self.folders_attr))

    def menu_set_recursive(self, indexes, current, payload=None) -> None:
        path = self._selected_location(current)
        if not path:
            return
        self.panel.prefs.set_file_folder_recursive(path, bool(payload))
        self._p(self.folders_attr).refresh_counts()
        # Rescan whatever is showing under the new mode.
        self.panel.update_selected_cat()

    def menu_set_show_all(self, indexes, current, payload=None) -> None:
        path = self._selected_location(current)
        if path:
            self.panel.prefs.set_file_folder_show_all(path, bool(payload))
        else:
            # The All row edits the GLOBAL preference.
            self.panel.prefs.file_show_unknown = bool(payload)
            self.panel.prefs.save()
        self._p(self.folders_attr).refresh_counts()
        self.panel.update_selected_cat()
    files_proxy_attr = "file_sorted_model"
    selection_attr = "file_selection_model"
    delegate_attr = "file_delegate"
    sidebar_attr = "file_folders_model"
    #: The only context with scene tiles to capture onto.
    takes_capture = True
    folders_pref = "file_folders"
    colour_pref_setter = "set_file_folder_color"
    folders_attr = "file_folders_model"
    files_attr = "file_files_model"
    last_folder_pref = "last_file_folder"

    def prefs_changed(self) -> None:
        # Geometry Shading/Background changed in Preferences must show
        # without re-clicking the folder - the Geometry section's rule,
        # carried over because geometry rows still render that way.
        # Show Unknown Files changes what counts as a row, so the
        # sidebar numbers refresh with the grid (they must agree).
        folders = self._p(self.folders_attr)
        if folders is not None:
            folders.refresh_counts()
        self.panel.update_selected_cat()

    def double_click(self, index) -> None:
        self.panel.click_on_row(self, index)


class OnlineContext(Section):
    """The online world, with a Section's interface and none of its
    identity.

    It is a PARALLEL WORLD, not a view mode over Materials (overview.md
    §5), and it drives the same four widgets every section drives - so
    it belongs to the same interface even though it is not in
    `SECTION_CLASSES` and never appears in `enabled_sections`.

    Making it one retires a family of defects that all had the same
    cause: entering the online world went through its own path and
    therefore skipped everything `_on_tab_toggled` does after
    `activate()`. The Capture button kept whatever state the section
    you left had given it, the search box kept text that filtered
    nothing here, and the Comments pane went on pointing at the local
    asset you had selected. One activation path, and none of those is
    something anyone has to remember.
    """

    key = "online"
    label = "Online"
    sidebar_attr = "matx_source_model"
    proxy_attr = "matx_sorted_model"
    selection_attr = "matx_selection_model"
    #: ITS OWN, with only the roles matx_library actually has. Borrowing
    #: the Materials delegate gave the online grid a Version, Licence
    #: and Comments column that no online record can ever fill.
    delegate_attr = "matx_delegate"
    #: The online search is a third thing again - it asks the SOURCE,
    #: not a proxy. It still shows no placeholder: empty is the 08-01
    #: decree for every tab, and the box's tooltip is what teaches the
    #: leading-colon tag search here as everywhere else.
    search_hint = ""

    def activate(self) -> None:
        panel = self.panel
        if panel.cat_list:
            panel.cat_list.setModel(self._p(self.sidebar_attr))
        panel.bind_grid_views(self._p(self.proxy_attr),
                              self._p(self.selection_attr),
                              self._p(self.delegate_attr))
        panel.texture_progress.setVisible(False)
        panel.matx_online_model.reload()
        panel.sync_list_columns()

    def filter_text(self, text: str) -> None:
        """The online search asks the SOURCE, not a proxy."""
        self.panel.matx_online_model.set_search(text)

    def filter_favorites(self, on: bool) -> None:
        """Nothing to do: an online record carries no favourite state,
        which is why the star is disabled here."""

    def stack(self):
        return None

    #: Named for WHERE the material lands, not what it is: both
    #: entries build the same Karma material, and the choice the user
    #: is making is library entry vs. scene node. Refresh acts on
    #: nothing selected, so it stays live like Code's New File.
    GRID_MENU = (
        MenuEntry("Import to Materials", verb="menu_import_to_library",
                  count_suffix=True),
        MenuEntry("Import to Scene", verb="menu_import_to_scene",
                  count_suffix=True),
        MenuEntry("Refresh", verb="menu_refresh", needs="always"),
    )

    def _records(self, indexes) -> list:
        """The catalogue records behind THESE rows.

        Through the indexes the menu was built from, not a second read
        of the selection model. The old menu rendered its "(N)" from
        one read and then imported from another (`panel.
        _matx_selected_records`, retired with it), and the two could
        genuinely disagree: that helper dropped a row whose record did
        not resolve, so the label could promise three and import two.
        """
        model = self.panel.matx_online_model
        proxy = self.panel.matx_sorted_model
        records = []
        for index in indexes:
            record = model.record(proxy.mapToSource(index).row())
            if record is not None:
                records.append(record)
        return records

    def menu_import_to_library(self, indexes, current, payload=None) -> None:
        self.panel._import_online_records(self._records(indexes))

    def menu_import_to_scene(self, indexes, current, payload=None) -> None:
        # Same wrapper as menu_copy_to: a menu import must not move
        # the artist's selection, current node or view.
        with helpers.preserving_selection_and_current():
            self.panel._import_online_records_to_scene(
                self._records(indexes))

    def menu_refresh(self, indexes, current, payload=None) -> None:
        """Refresh is the user asking us to go and LOOK: sources that
        browse from a shipped table (RGL, PhysicallyBased) only query
        the live site on this path."""
        for source in self.panel.matx_online_model.sources:
            try:
                source.refresh()
            except Exception as exc:                     # noqa: BLE001
                debug.exception("refresh source", exc, source=source.name)
        # force=True - without it, a loaded catalogue just re-filters
        # and the user's explicit Refresh did nothing.
        self.panel.matx_online_model.reload(force=True)

    #: The three the online world does not offer. Each of these was an
    #: `_is_online()` branch somewhere in the panel; they are one row
    #: of declarations now, and the toolbar reads them.
    takes_comments = False
    takes_favourites = False
    takes_filter_menu = False


class GradientSection(Section):
    deletes_rows = True

    @staticmethod
    def delete_prompt(count: int, name: str = "") -> str:
        # The one section whose approved copy NAMES the thing
        # (ui-text.md): a palette's name is what the user picked it by,
        # and it is the only section where the tile label is the whole
        # identity a person has.
        if count == 1:
            return ('Delete "%s"? The gradient goes for good. Ramps '
                    "already applied to a node are not affected."
                    % (name or "this palette"))
        return ("Delete %d gradients? They go for good. Ramps already "
                "applied to a node are not affected." % count)

    def delete_rows(self, indexes) -> None:
        model = self.panel.gradient_model
        for row in sorted({index.row() for index in indexes},
                          reverse=True):
            model.remove_user_gradient(row)
        self.panel.gradient_categories_model.switch_model_data()

    key = "gradient"
    label = "Color"
    empty_noun = "palette"
    #: No button, for the same reason as Material.
    EMPTY = {
        "nothing-yet": (
            "No palettes saved yet",
            "Right-click a node with a color ramp and choose Save to "
            "Amaze. Apply it to any ramp later, in any scene.",
            "", ""),
    }
    #: The GRID model and the SIDEBAR model. The sidebar one is the
    #: eighth model - the one none of panel.py's three lists carried,
    #: which is why a library switch left Colors on the old library.
    #: Note it is a real model here, where an asset section's
    #: `sidebar_attr` names a PROXY, which is exactly why this cannot
    #: be derived from `sidebar_attr` across the archetypes.
    library_model_attrs = ("gradient_model", "gradient_categories_model")
    #: The SAME proxy class the asset sidebars go through (2026-08-14).
    #: Color showing its model bare was the last odd-one-out sidebar
    #: pipeline, which is where the sections' order behaviour drifted
    #: apart. Nothing hides here - no renderer filter is ever pushed,
    #: so every row passes - the pipeline is what is unified.
    sidebar_attr = "gradient_category_sorted_model"
    delegate_attr = "gradient_delegate"
    proxy_attr = "gradient_sorted_model"
    selection_attr = "gradient_selection_model"

    #: The base's category-sidebar reorder bodies fit unchanged.
    reorders_sidebar = True

    def _sidebar_source_row(self, index) -> int:
        """A cat_list index is a PROXY index since the sidebar proxy
        arrived; `filter_for_row` speaks source rows."""
        if index is None or not index.isValid():
            return -1
        return self.panel.gradient_category_sorted_model.mapToSource(
            self.panel.gradient_category_sorted_model.index(
                index.row(), 0)).row()

    def activate(self) -> None:
        """The same four bindings as every other section; the one thing
        of its own is that its sidebar filter is a SIZE range rather
        than a category name, so it is cleared by its own call."""
        panel = self.panel
        sidebar = self._p(self.sidebar_attr)
        if panel.cat_list and sidebar is not None:
            panel.cat_list.setModel(sidebar)
        panel.bind_grid_views(self._p(self.proxy_attr),
                              self._p(self.selection_attr),
                              self._p(self.delegate_attr))
        panel.texture_progress.setVisible(False)
        panel.sync_list_columns()
        # Start on "All" (row 0) with the size filter cleared - the
        # programmatic select below does not fire clicked(), so the
        # filter is reset explicitly.
        self._p(self.proxy_attr).set_sidebar_filter("all", None)
        panel._select_default_sidebar_row(sidebar)
    #: Apply puts the gradient on the selected node's first colour ramp
    #: exactly as it was saved; "Apply as" is the deliberate override,
    #: one entry per interpolation Houdini has. Copy Color COPIES a hex
    #: code rather than assigning it - a node carries many colour
    #: inputs, and picking "the first colour parm" for the user was a
    #: guess that was usually wrong. Both submenus are built PER ENTRY,
    #: which is why `children` names a method rather than a constant.
    #: No Update Preview: this preview is drawn from the palette's own
    #: ramp, so there is nothing to re-render.
    GRID_MENU = (
        MenuEntry("Apply", verb="menu_apply_ramp", needs="one"),
        MenuEntry("Apply as", verb="menu_apply_ramp", children="ramp_bases",
                  needs="one"),
        MenuEntry("Copy Color", verb="menu_copy_swatch",
                  children="palette_swatches", needs="one"),
        SEPARATOR,
    ) + GRID_MENU_TAIL

    #: A gradient hands to a node with a ramp; on empty network space
    #: the MaterialX ramp carrier is created where supported.
    DROP = DropRule(on_node="apply_gradient_to_node",
                    on_space="create_gradient_node_in",
                    click_on_node="apply_gradient_to_node")

    def apply_gradient_to_node(
        self, index: QtCore.QModelIndex, node: hou.Node,
        basis: str = "",
    ) -> bool:
        """Drag-drop completion for the Gradients section: apply the
        dragged combination to the node the drag was released over.
        A node that takes nothing answers False - the gesture shows
        its own miss (drag-door rule: the red indicator and the status
        line, never a dialog)."""
        panel = self.panel
        if index is None or not index.isValid():
            return False
        source_index = panel.gradient_sorted_model.mapToSource(index)
        entry = panel.gradient_model.entry(source_index.row())
        if entry is None:
            return False
        parm = helpers.find_color_ramp_parm(node)
        if parm is None:
            ui = getattr(hou, "ui", None)
            if ui is not None:
                ui.setStatusMessage(
                    "Amaze: %s has no color ramp to take the gradient"
                    % node.name(),
                    severity=hou.severityType.Warning,
                )
            return False
        with hou.undos.group("Amaze Apply Gradient"):
            parm.set(self._entry_ramp(entry, basis))
        return True

    @staticmethod
    def _entry_ramp(entry: dict, basis: str = "") -> hou.Ramp:
        # An explicit basis rebuilds the ramp from the gradient's
        # colours on that one interpolation; otherwise the recorded
        # ramp (bases/keys/values) applies exactly as saved.
        if basis:
            return helpers.build_basis_ramp(
                [c["hex"] for c in entry["colors"]], basis)
        ramp = entry.get("ramp")
        if ramp:
            return helpers.data_to_ramp(ramp)
        return helpers.build_stepped_ramp([c["hex"] for c in entry["colors"]])

    def create_gradient_node_in(self, index, dest, position=None,
                                basis: str = "") -> bool:
        """The gradient creation rule: a MtlX colour ramp carrying the
        combination, wherever the network can hold one.

        `basis` is Apply as's chosen interpolation, arriving through
        the click door's payload; empty means the gradient's own
        recorded ramp, which is every other door."""
        panel = self.panel
        if index is None or not index.isValid():
            return False
        source_index = panel.gradient_sorted_model.mapToSource(index)
        entry = panel.gradient_model.entry(source_index.row())
        if entry is None:
            return False
        return self._create_gradient_carrier(entry, dest, basis,
                                             position=position)

    def _create_gradient_carrier(self, entry, dest, basis: str = "",
                                 position=None) -> bool:
        """The carrier half shared by the drag door (an index) and the
        double-click and menu doors (an entry, optionally re-based by
        Apply as)."""
        name = helpers.sanitize_usd_path(
            str(entry.get("name") or "")) or "gradient"
        with hou.undos.group("Amaze Create Gradient Node"):
            node = self.panel._create_carrier(dest, "hmtlxrampc", name,
                                              position)
            if node is None:
                return False
            parm = helpers.find_color_ramp_parm(node)
            if parm is None:
                node.destroy()
                return False
            parm.set(self._entry_ramp(entry, basis))
        return True

    def _copy_gradient_swatch(self, color: dict) -> None:
        """Put one swatch's hex code on the system clipboard.

        Deliberately not an assignment: a material carries many colour
        inputs (base, specular, coat, emission, subsurface...), so
        choosing one for the user was a guess. A hex code pastes into
        the intended input by the user's own hand - Houdini's colour
        fields accept it, and so does every other application."""
        hex_code = str(color.get("hex", "")).strip()
        if not hex_code:
            return
        if not hex_code.startswith("#"):
            hex_code = "#" + hex_code
        hex_code = hex_code.upper()
        clipboard = QtWidgets.QApplication.clipboard()
        if clipboard is None:
            return
        clipboard.setText(hex_code)
        debug.event("gradient", "colour copied",
                    name=color.get("name"), hex=hex_code)
        hou.ui.setStatusMessage(  # type: ignore
            "Amaze: copied %s (%s)" % (hex_code, color.get("name", ""))
        )

    #: The MaterialX colour ramp, wherever a network can hold one.
    carrier_type = "hmtlxrampc"

    takes_category_drops = True

    def accepts_category_drop(self, index, name: str) -> bool:
        """Defensive: every gradient category listed is a real,
        editable user category now (the palettes are seeded as such),
        but guard in case the sidebar ever lists synthetic rows again.

        This was `if self.current_section == "gradient"` inside the
        panel's shared helper, reaching into `gradient_model` by name.
        """
        return name in self.panel.gradient_model.user_categories()

    #: The same spine, with one difference that is real: everything
    #: below "All" is a user category, so the per-category entries
    #: EXIST only on such a row. `sidebar_key` answers "" for All,
    #: which is what `on_a_category` reads.
    SIDEBAR_MENU = (
        MenuEntry("Add Category", verb="menu_add_category",
                  needs="always"),
        MenuEntry("Rename", verb="menu_rename_category", needs="one",
                  shown="on_a_category"),
        MenuEntry("Remove", verb="menu_remove_category",
                  shown="on_a_category"),
        SEPARATOR,
        MenuEntry("Set Color", verb="menu_set_colour",
                  shown="on_a_category"),
        MenuEntry("Clear Color", verb="menu_clear_colour",
                  shown="on_a_category"),
    )

    def on_a_category(self, indexes, current) -> bool:
        """Is the row under the cursor a real user category?

        Not a crash site - `filter_for_row` takes only `.row()` and
        dereferences no mapping. But a stale row is a stale ANSWER: it
        names whichever category now sits at that position, so the menu
        would offer to remove the wrong one.
        """
        return bool(self.sidebar_key(current)) if current is not None else False

    def menu_add_category(self, indexes, current, payload=None) -> None:
        name = self.panel.ask_category_name("Add Category")
        if not name:
            return
        self.panel.gradient_model.add_user_category(name)
        self.panel.gradient_categories_model.switch_model_data()

    def menu_rename_category(self, indexes, current, payload=None) -> None:
        old_name = self.sidebar_key(current)
        new_name = self.panel.ask_category_name("Rename Category")
        if not old_name or not new_name:
            return
        if self.panel.gradient_model.rename_user_category(old_name,
                                                          new_name):
            self.panel.gradient_categories_model.switch_model_data()

    def menu_remove_category(self, indexes, current, payload=None) -> None:
        name = self.sidebar_key(current)
        if not name:
            return
        count = self.panel.gradient_model.count_in_category(name)
        message = 'Remove category "%s"?' % name
        if count:
            message += " Its %s gradient%s will be kept (shown under All)." % (
                count, "" if count == 1 else "s")
        if not hou.ui.displayConfirmation(message):      # type: ignore
            return
        self.panel.gradient_model.remove_user_category(name)
        self.panel.gradient_categories_model.switch_model_data()
        # The removed row may have been the selection - fall back to
        # "All" so the sidebar never points nowhere. A PROXY index:
        # the view shows the sidebar proxy since 2026-08-14, and a
        # source index setCurrentIndex silently selects nothing.
        self.panel.gradient_sorted_model.set_sidebar_filter("all", None)
        self.panel.cat_list.setCurrentIndex(
            self.panel.gradient_category_sorted_model.index(0, 0))

    def tile_models(self):
        return self.panel.gradient_model, self.panel.gradient_sorted_model

    def _entry_at(self, index):
        if index is None or not index.isValid():
            return None
        source = self.panel.gradient_sorted_model.mapToSource(index)
        return self.panel.gradient_model.entry(source.row())

    def ramp_bases(self, indexes, current) -> tuple:
        """Every interpolation, always offered (2026-07-31). It used to
        be a single conditional "Apply as Linear Ramp"."""
        return tuple((basis, basis, "", True)
                     for basis in helpers.RAMP_BASES)

    def palette_swatches(self, indexes, current) -> tuple:
        """One row per colour in THIS palette, each carrying its own
        hex as the swatch colour - so the menu doubles as a preview.
        The pixmap is drawn by panel/grid.py; this only says which
        colour it is."""
        entry = self._entry_at(current)
        if entry is None:
            return ()
        return tuple(
            ("%s   %s" % (colour["name"], colour["hex"].upper()),
             colour, colour["hex"], True)
            for colour in entry["colors"]
        )

    def menu_apply_ramp(self, indexes, current, payload=None) -> None:
        # Apply and Apply as, through the click door. The payload is
        # the chosen ramp basis; the door hands it to whichever verb
        # runs, so re-basing works on the node AND on the carrier.
        self.panel.click_on_row(self, current, payload or None)

    def menu_copy_swatch(self, indexes, current, payload=None) -> None:
        if payload is not None:
            self._copy_gradient_swatch(payload)
    #: This proxy matches the palette's own name AND the name of every
    #: color inside it, which is the one place searching reaches further
    #: than the tile label - worth saying, since nothing else does.
    search_hint = ""
    filter_tooltip = "Show palettes of one size."

    #: (label, (fewest, most)) - `most` None means no upper end, which
    #: is what "5+" is. A RANGE rather than a plain number because the
    #: last entry is open and the proxy must not have to know which
    #: entry that is: it reads the pair it is handed and nothing else.
    FILTER_CHOICES = (
        ("1 color", (1, 1)),
        ("2 colors", (2, 2)),
        ("3 colors", (3, 3)),
        ("4 colors", (4, 4)),
        ("5+ colors", (5, None)),
    )

    def filter_text(self, text: str) -> None:
        self.panel.gradient_sorted_model.set_name_filter(text)

    def filter_favorites(self, on: bool) -> None:
        self.panel.gradient_sorted_model.set_favorites_only(on)

    def apply_filter(self, value) -> None:
        self.panel.gradient_sorted_model.set_size_filter(value)

    def select_category(self, index) -> None:
        kind, value = self.panel.gradient_categories_model.filter_for_row(
            self._sidebar_source_row(index)
        )
        self.panel.gradient_sorted_model.set_sidebar_filter(kind, value)

    def toggle_favourite(self, indexes) -> None:
        model = self.panel.gradient_model
        proxy = self.panel.gradient_sorted_model
        for index in indexes:
            source = proxy.mapToSource(index)
            if source.isValid():
                model.toggle_favorite(source.row())

    def sidebar_key(self, index) -> str:
        """Its rows are user categories; `filter_for_row` is the one
        reader of what a row means, and answers ("category", name) for
        everything below All."""
        if index is None or not index.isValid():
            return ""
        kind, value = self.panel.gradient_categories_model.filter_for_row(
            self._sidebar_source_row(index))
        return str(value or "") if kind == "category" else ""

    def sidebar_colour(self, name: str) -> str:
        # THE SIDEBAR MODEL, exactly as the asset sections read it.
        # This asked the LIBRARY, which kept its own colour dict, so
        # clearing a colour took it off one store and left it on the
        # other and the row went on wearing it.
        return self.panel.gradient_categories_model.color_of(name)

    def set_sidebar_colour(self, name: str, colour: str) -> None:
        self.panel.gradient_categories_model.set_color(name, colour)
        # The grid reads the colour through a role on the ASSET model,
        # which shares the category model's data dict, so a repaint is
        # all that is needed - role-scoped for the reason the asset
        # sections give.
        model = self.panel.gradient_model
        if model is not None and model.rowCount():
            model.dataChanged.emit(
                model.index(0, 0),
                model.index(model.rowCount() - 1, 0),
                [model.CategoryColorRole],
            )

    def comment_subject(self, index):
        """Keyed by the palette's UID, not its name: a palette can be
        renamed and the page has to follow it."""
        model = self.panel.gradient_model
        source = self.panel.gradient_sorted_model.mapToSource(index)
        if not source.isValid():
            return None
        uid = model.note_uid(source.row())
        if not uid:
            return None
        return CommentSubject(
            key=notes.note_key(self.key, uid),
            section=self.label.lower(),
            name=source.data(QtCore.Qt.ItemDataRole.DisplayRole) or "",
            type=source.data(model.RendererLabelRole) or "",
            category=str(source.data(model.CategoryLabelRole) or ""),
            colour=str(source.data(model.CategoryColorRole) or ""),
        )

    def double_click(self, index) -> None:
        self.panel.click_on_row(self, index)

    def save_node(self, node) -> None:
        self.panel.save_gradient_from_node(node)


#: The section registry, in tab order. Built by the panel after its
#: models exist. Adding a section = one class here.
SECTION_CLASSES = (
    MaterialSection,
    GradientSection,
    CopSection,
    CodeSection,
    FileSection,
)

#: The same registry keyed for lookup. CLASS-level, deliberately: the
#: gesture engine reads declarations (DROP, DROP_BY_KIND), so tests
#: drive the real tables without building a panel's worth of models.
SECTION_INDEX = {cls.key: cls for cls in SECTION_CLASSES}


def drop_rule(section, panel, index):
    """The rule THIS ROW declares, or None.

    A section declares one `DROP` for every row, unless its rows are
    different THINGS - the File section - in which case it declares
    `DROP_BY_KIND` and the row's KindRole picks. That sentence was
    written twice: once in the drag walker
    (`dragdrop_widgets._drop_rule`) and once inline in the click
    walker (`panel.click_on_row`). Two readers of one declaration is
    how the two doors end up disagreeing about the same tile, which is
    the exact bug the click walker was built to end.

    Here, beside the declarations it reads, so a section that gains a
    third way of declaring changes one reader.
    """
    if section is None:
        return None
    by_kind = getattr(section, "DROP_BY_KIND", None)
    if by_kind:
        kind = index.data(panel.file_files_model.KindRole) or ""
        return by_kind.get(kind)
    return getattr(section, "DROP", None)


def drop_verb(section, name):
    """The bound verb a declaration names - the section's own.

    The panel fallback this carried while ROADMAP line 24 moved the
    verbs over is REMOVED (B3), and the pin in test_area_bindings
    walks every declaration to keep it removed: the panel owns the
    widgets and the shared plumbing, the section owns the meaning.
    A name that resolves nowhere raises - a broken declaration must
    fail loudly, never miss quietly.
    """
    return getattr(section, name)


def all_sections() -> tuple:
    """((key, label), ...) in tab order - the ONE source.

    Anything that lists the sections reads this: the tab strip, the
    Show/Hide toggles, and the pref that persists them."""
    return tuple((cls.key, cls.label) for cls in SECTION_CLASSES)


def renderer_prefs() -> tuple:
    """((label, preference-attribute), ...) - the ONE renderer table.

    Beside all_sections() and for the same reason. The SECTION list in
    Preferences was converted to read all_sections() after a hardcoded
    copy left the HIP tab with no switch AND had it deleted by toggling
    any other one; the renderer table twelve lines above it in the same
    function was left a copy, and there is a third as an if/elif chain
    in enable_renderer_on_add.

    What three copies cost: add a renderer to this tuple alone and the
    Filter menu offers it while Preferences has no switch, so it can
    never be hidden. Add it to Preferences alone and the switch toggles
    a preference no menu reads. Add it to both and not to
    enable_renderer_on_add, and saving the first material of that
    renderer leaves its own filter entry off - so the material the user
    just saved is invisible in the tab they saved it from, which is the
    exact defect enable_renderer_on_add exists to prevent.
    """
    return MaterialSection.RENDERER_PREFS


def build_sections(panel) -> dict:
    """Instantiate every section against a constructed panel."""
    return {cls.key: cls(panel) for cls in SECTION_CLASSES}
