# Amaze architecture & terminology

This is the **shared vocabulary** for the project. When a term here is
written in **Bold Caps** it is a *named part* — say "update the **Material
Engine**" or "the **Colors Section** is broken" and we both know exactly
what is meant. Rename a term in this file and the new name is the one to
use from then on.

Read this before a big change. Keep it current when the architecture
changes (this is the *what exists now* map; a private development log,
kept outside this repo, is the *what we did and why* log).

---

## 1. The one-paragraph picture

Amaze is a single Houdini **Python Panel** — one window with a
**Toolbar**, a **Section Tab Strip**, a **Sidebar**, and a **Grid**.
Metadata is edited in floating **Dialogs** (see §6) — Materials has the
**Edit Info Dialog**, Code its editor — one per section, not a docked
panel.

The same widgets are reused for every kind of
asset; switching tabs just repoints them at different data. Behind the
panel are six standalone **Engines** (thumbnails, image conversion,
keyed stores, Karma materials, debug, OS integration) that the rest of
the code calls through small, stable APIs. Each
tab is a **Section** object — a node-type-like plug-in that defines how the
panel uses the shared widgets. Data is read/written through
**Models** backed by a **Library** folder on disk.

---

## 2. The shell — what you see

| Term | What it is | In code |
|---|---|---|
| **Panel** | The whole window. One class, built once. | `panel/panel.py` → `AmazePanel` |
| **Toolbar** | Top strip, laid out left to right in one place (`_lay_out_toolbar`, frame B01): Categories, Renderer + View menus, Online, Grid/List toggle, Favourites star, the Preferences gear and Capture (every section, greyed online), then the size slider and the Search box, and at the far right Comments and Info (every section, greyed online). The View menu holds Generate Material, the imports and the two package exports, each export greyed unless the shown context has what it writes. Categories and Online were moved out of the View menu (2026-08-01): a control that toggles state is a button, not a menu row, and having both lets the button and the menu row show different states. Every chip's four state pixmaps come from `ChipToggleButton.set_art` — the SVG as drawn at rest, hover lightens, and a chip whose ON state is shown by COLOUR (star amber, Online green, Comments purple, Info amber) does not lighten at all. Disabled chips paint at 50%. | built in `init_ui()`, states in `ui_helpers.ChipToggleButton.set_art` |
| **Section Tab Strip** | The Material/Color/Node/Code/File tabs (singular since the 2026-07-31 merge; stored keys keep their historical names): Houdini's own QML tab bar (`houdini.pluto` TabBar and TabButton, in `ui/section_tabs.qml`, set up with Houdini's theme as its own QML views are), each tab with its section icon drawn at the size frame S01 draws it and 2 px from its name, and a 1 px line along the strip's bottom row over the tab bar. Carries a standard **Cancel button** at its right end: shown exactly while the conversion bar shows — the pane engine's `show_progress` is the only way the bar shows or hides, and the panel's `set_conversion_bar_visible`, which follows it, shows or hides both — it stops a background thumbnail render while one runs (`husk_job.jobs`, which controls the bar meanwhile), otherwise the File section's image batch (flush first, then cancel). | `ui_helpers.SectionTabBar` |
| **Sidebar** | Left list: categories (asset sections + Color) or folders (File). ONE view, `sidebar.SidebarTreeView`, which is the app's one table class (`ui_helpers.Table`, a tree view the host's style paints) over a model of two columns: the row's colour as a fixed-width cell shown first, then the name, with the style's own arrow in the name column (`setTreePosition`). In File each location unfolds to its subfolders. The view has no mouse code: Qt selects, opens and closes rows, and the panel shows a row's content on `Table.row_chosen`, emitted when the user moves the current row by mouse or keyboard. Rows are shown in the STORED order with "All" fixed at row 0 by the database (and, in File, `$HIP` fixed at row 1 by the model), and the ORDER IS THE USER'S: a row is dragged with Qt's own drag and drop (`InternalMove`) and the model's `RowMoves` mixin answers `canDropMimeData` and writes the order once in `dropMimeData`. A model that cannot be reordered (Online) gives no drag flag. Whether a dragged tile may be DROPPED on a row is decided by the context — `Section.takes_category_drops` and `accepts_category_drop`. | the `cat_list` widget, `panel/sidebar.py`, `core/sidebar_model.py` |
| **Grid** | The main thumbnail area. GRID scales 64-512 and snaps to 128 when near it; LIST is a table fixed at its smallest size (the slider greys out) whose row is as wide as its COLUMNS need, scrolling sideways rather than squeezing or dropping any. LIST mode is a tree view over a real `QAbstractTableModel`, made by `ui_helpers.striped_rows` like every other row list with its header shown, so the host style paints its rows, the space under them and its headline ▸r/list-mode-is-a-tree (a `QTableView` from 2026-08-04 to 1.41.1); the painted header strip, `ListColumnHeader`, `ListColumns` and the delegate's list-painting branch are all removed. **The grid selection is read in ROWS** (2026-08-06): a SelectRows selection returns one index per CELL - ten per row, hidden thumb column included - so every caller reduces it to one index per row at column 0 through `grid_columns.selected_rows`, and the current, double-click and drag indexes are normalised to column 0 the same way (`live_current_index`, the panel's double-click entry, the drag press). The table carries the same context-menu and double-click wiring as the list view. The column ORDER is defined once, in `core/grid_columns.COLUMNS`; every grid model reads it, and sorts its own rows, through the **Grid Engine** (§4i). WIDTHS are fixed defaults the user can DRAG (`panel.COLUMN_DEFAULT_WIDTH`, derived from the real library), with the last column filling the remaining width — nothing is measured at runtime. Tile badges are grid-only: at list size a badge is 12px and its SVG rasterises to a dark smudge, so those four facts are columns there instead. | the `thumblist` and `thumbrows` widgets, `panel/grid.py`, `panel/delegates.py` |
| **Tile** | One item in the Grid (thumbnail + name + subtitle). Painted by the **Tile Delegate**. | `AssetItemDelegate` |
| **Tile Badges** | ONE drawn family (2026-08-01): each glyph on its own dark backdrop (`ui/badge_*.svg` — the colours are in the SVG files, never in code), rendered AS DRAWN by one function (`_badge_pixmap`) at one size rule (`_badge_side`). Corners: top-left open scene, top-right favourite, lower-left versions, lower-right comment. TWO are BUTTONS, driven by the `BADGES` table: versions (click opens the Versions dialog) and, since 2026-08-21, favourite — always drawn where a section wires its click (every local grid, never Online): dim white star at rest, brighter on hover, amber when favourite, and a click toggles the selection's stars through the section's own `toggle_favourite`. Wiring the click (`set_badge_click`) is what MAKES a badge a button; hit-testing, hover and tooltips all derive from the same table. | `delegates.py` `_paint_badges`, `button_badge_at` |
| **Filter Box** | The search field in the Toolbar. | `line_filter` |

---

## 3. Sections — the node-types of the panel

A **Section** is one tab. It is a small object that defines what the
pane shows for its kind of asset and what its rows do. The **Pane
Engine** (`pane/pane.py`, held by the Panel as `panel.pane`) holds the
data and the models and builds no widget; the Panel holds the widgets
and follows the engine's signals; a Section only defines *what to do
with the data*, and touches no widget. What the engine needs a window
for (a name, a colour, the drop menu, Versions, Save, Code, Customize,
Preferences) it asks its host through `pane.ui` (`pane/asks.py`), and
each answer comes back through a callback, so a host that does not
block can answer later.

**Files:** one per section in `sections/` (`material.py`, `node.py`,
`code.py`, `color.py`, `file.py`, `online.py`), the shared base in
`sections/base.py`. **Registry:** `SECTION_CLASSES` in
`sections/__init__.py`, built in
the order of `core/section_list.py`, the only `((key, label), ...)` list,
which needs neither the panel nor Houdini to read. Adding a section = a
new file with its class, its line in the registry and in the list; a class takes its
label from the list, and everything that lists the sections reads the
list - the tab strip, the UI toggles, and the pref that persists
them. `Pane.ALL_SECTIONS` is the same tuple, not a second list to keep
in step.

Read a KEY as an identifier, never as a name: keys are stored in
saved preferences and in every asset record, and the removed
`texture`/`geometry`/`hip` must never be stripped.

The five sections, grouped by **Archetype** (they share machinery):

| Section (term) | Archetype | Key | Stores |
|---|---|---|---|
| **Material Section** | Asset | `material` | Karma/Redshift/Octane materials |
| **Color Section** | Gradient | `gradient` | curated + user colour palettes |
| **Node Section** | Asset | `cop` | saved node setups from any context (SOP, COP, LOP, DOP, TOP, CHOP, object level) |
| **Code Section** | Asset | `code` | VEX/Python snippets |
| **File Section** | Folder | `file` | EVERY file in registered folders, each row a KIND: image / geometry / hip / other (the 2026-07-31 merge of the Images, Geometry and HIP sections) |

Plus one *view mode*, not a section:

- **Online Browser** — a separate context with a Section's interface:
  `online.OnlineContext`, returned by `pane.active_section()` like any
  section, so no code path has to check whether the panel is online. It is
  NOT in `SECTION_CLASSES` and never appears in `enabled_sections`,
  because it is not a section. Its delegate carries only the roles
  `matx_library` has — no version, licence, comments or category
  colour — so the online grid cannot paint a column no online record
  can fill. Entering and leaving go through `pane.show_context`, the
  same function a section switch uses, which fixed the Capture button,
  the search box and the Comments subject showing stale state when you
  went online. (2026-08-03; it was a view mode over Materials before.)

### The three Archetypes

- **Asset Archetype** (`AssetSection`) — a **Library Model** over a JSON
  file + a **Categories Model** in the Sidebar, filtered by the **Filter
  Proxy**. Material, Node, Code.
- **Folder Archetype** (`FolderSection`) — a **Folders Model** (pointers
  to real directories) + a **Files Model** listing what's inside. One
  shipped subclass since the merge: the File section
  (`core/file_library.py` — `FileFolders` + `FileFiles`). Each row
  carries a KIND and keeps its pre-merge section's behaviour: images
  convert in the background (`('tex', path, size)` engine keys),
  geometry renders in the blocking ESC-interruptable pass
  (`('geo', path, cache_dir)`), scene rows show their CAPTURE from the
  library's `captures` folder (`core/captures.py`), and unknown files show their OS
  icon. Per-location recursion, custom names and the remove-time cache
  cleanup are implemented in `FileFolders`. A subfolder row browses its own path
  (`BrowseRole`) by the rules of the location it is in
  (`locations.owner_of`, the innermost when locations nest), and has
  no `PathRole`, so every location action skips it. The `$HIP` row is
  one more top row of the same model, fixed at row 1 before the
  registered locations (`FolderTreeModel.set_scene_folder`, no record on
  disk): the scene's folder, shown only while the scene has a file on
  disk (`actions/files.scene_saved`), browsed and counted by those same rules,
  re-pointed in place by one `hou.hipFile` callback per panel
  (`actions/files.watch_scene`, on AfterSave, AfterLoad and AfterClear)
  and remembered in `last_file_folder` by the token `$HIP`.

- **Gradient Archetype** (`GradientSection`) — the palette library.
  Color. Fully read-write: gradients are added (including from a
  dropped ramp node), renamed, recategorised and deleted, and so are
  their categories.


### The Section API (what every Section implements) {#o/section-api}

| Method | Called when | 
|---|---|
| `activate()` | its tab is selected — one implementation: `pane.bind` shows its Models on the host's sidebar and grid views, then its **Sidebar** row is selected; what differs is a hook a section overrides (`before_sidebar_shown`, `after_views_bound`, `restore_sidebar_selection`) |
| `stack()` | returns the **Asset Stack** — `base.AssetStack`, read by NAME — or None |
| `filter_text(text)` | the **Filter Box** changes |
| `filter_favorites(on)` | the **Favourites Star** toggles |
| `filter_entries()` | the **Filter Menu** is rebuilt — `((label, value), …)`, everything-entry first |
| `apply_filter(value)` | an entry is picked, or the section is entered — narrow the grid to it |
| `select_category(index)` | a **Sidebar** row is clicked |
| `comment_subject(index)` | the **Comments** pane re-points — a `base.CommentSubject` for that row, or None |
| `toggle_favourite(indexes)` | Favorite, on the **Grid** selection |
| `update_preview(indexes)` | Update Render — offered only where `offers_preview_update` is True, i.e. where a preview is RENDERED rather than derived from the row's own content |
| `delete_rows(indexes)` | Delete, highest row first — offered only where `deletes_rows` is True (File has no Delete: its rows are files on disk) |
| `delete_prompt(count, name)` | what deleting costs, in this section's words — the wording lives in the UI text register |
| `sidebar_key(index)` | what a **Sidebar** row is keyed by, read from the row's `category.SIDEBAR_KEY_ROLE` — a stored category name, the folder a File row shows, an online category, `""` on All; File reads a registered location through `location_key(index)` |
| `sidebar_colour(name)` / `set_sidebar_colour(name, colour)` | read and write that row's colour — one implementation, which asks the section's sidebar list (`color_of`, `set_color`); each list keeps it in its own store (a category's in the section's database, a File location's in its location record), and `repaint_grid_colours()` repaints the tiles after a change |
| `takes_file_drops` + `accepts_file_drop` / `drop_folder` / `move_files_to` / `can_undo_move` / `menu_undo_move` | a **Grid** tile released on a **Sidebar** folder moves the selected files there on disk (File only; `core/file_moves.py`), and Undo Move puts the last move back |
| `menu_copy` / `menu_paste` / `menu_paste_enabled` | File's **Grid** menu: Copy puts the selected files on the system clipboard (`pane/files.copy_files`); Paste copies the clipboard's files into the folder shown on the same worker (`file_moves.copy`), asking once about names in use |
| `double_click(index)` | a **Tile** is double-clicked (the *primary action*) — calls `pane.loading.click_on_row` (below) |
| `GRID_MENU` / `SIDEBAR_MENU` | right-click on the **Grid** or the **Sidebar** — the host renders the table (`grid.open_grid_menu`, `grid.open_catlist_menu`) |
| `edit_dialog()` | open the section's edit **Dialog** (see §6), if any |
| `can_save(nodes)` / `save_categories()` / `takes_language` | `pane.saving.save_from_node` (through `_save_targets`) calls every section to learn whether it can save these scene nodes, and what its Category row offers; `takes_language` lights the Language row (Code only). One right-click entry and the panel drop both go through `pane.saving.save_from_node` |
| `prefs_changed()` | Preferences closed — re-scan live filesystem/render state |

The engine's shared handlers dispatch to `pane.active_section().<method>()`
instead of branching on the section key.

Plus one piece of DATA, alongside `key` and `label`: **`search_hint`** —
what the **Filter Box** shows while this section is active. It is set on the
ARCHETYPE, because the archetype decides what a search matches (Asset
sections take `:tag`, the File section has only a file name, Color also
matches the colour names inside a palette). The Panel writes it in
`_sync_filter_placeholder()`, called wherever the section or the view
mode changes; the **Online Browser** supplies its own, since its search
matches something different again. Wording in the UI text register.

**A VALUE CARRIES ITS OWN NAME.** Several values passed together are
a named tuple, never a bare tuple read by position:

| named tuple | fields | what to watch |
|---|---|---|
| `base.AssetStack` | `model proxy selection categories` | the four models an Asset section works through; read by NAME |
| `base.CommentSubject` | `key name type` | `key` is the notes key (`notes.note_key`); `type` is the row's renderer label, or its file format in File |
| `base.FilterEntry` | `id label value icon` | `id` is what the remembered choice saves, so a label can change |

**The two DECLARATIONS a section author writes.** Both are data — names
of methods, never callables — and every field has a default, so a field
can be left undeclared.

`base.DropRule`, the drag and click actions a row offers:

| field | used for | the method takes |
|---|---|---|
| `on_node` | DRAG, cursor over a node | `(index, node)` |
| `on_space` | DRAG, cursor over empty network space | `(index, network, position)` |
| `resolve` | DRAG, finds its own target | `(index)` |
| `click_on_node` | CLICK, the SELECTION | `(index, node)` |
| `click_resolve` | CLICK, finds its own target | `(index)` |
| `holder_node_type` | — | name of the node type the `on_space` method CREATES, where that is a constant, so the drag preview draws its shape from the same declaration the creating method reads |
| `context` | — | the `childTypeCategory` a network must have to accept this drop; empty for any network |

`base.MenuEntry`, one row of a menu table:

| field | what it declares |
|---|---|
| `label` | the row's text, from the UI text register; an empty one is a divider, and leading, doubled and trailing ones are dropped, so a table with conditional rows never places them by hand |
| `handler` | NAME of a method on the section, called as `handler(indexes, current, payload)` |
| `needs` | what makes the row LIVE — `any` (the default), `one`, `always`, or the name of a fact — and it greys, never hides |
| `shown` | the fact deciding whether the row EXISTS at all |
| `children` | a method returning `((label, payload, icon, live[, checked]), ...)`; the icon is a hex colour, painted as a chip at `amazetheme.MENU_CHIP`, a `ui/` icon name, drawn by `ui_helpers.menu_icon` as the Filter menu's are, or empty. A renderer's icon is named once, in `core/renderers.py` |
| `count_suffix` | appends ` (N)` on a multi-selection |
| `checkable` | the fact giving the CURRENT state, making it a tick-box whose handler receives the state the user chose |

**The Grid Menu** (2026-08-03) is the same idea for right-click. Every
context declares `GRID_MENU` — a tuple of `MenuEntry` rows, one per
entry — and `panel/grid.py` is the ONLY code that turns one into a
QMenu. A row holds its label (from the UI text register), the NAME of
the Section method that performs it, the fact deciding whether it EXISTS
(`shown`), what it needs to be LIVE (`needs`), and optionally the method
building a submenu's children. Names, not callables. The last three rows
are `GRID_MENU_TAIL` — the Thumbnail submenu (Render Image, Capture Scene,
Customize, its rows from `Section.thumbnail_actions`), Favorite, Delete —
shared by every context and gated on facts it already declares, so
adding a section adds no copy of them. Dispatch is a dict keyed by
QAction, never `==` against an action that may be None.

`pane.loading.click_on_row` is the one function a double-click AND the menu entry
labelled with the same verb both call — one
order of precedence, read from the section's own `DROP` / `DROP_BY_KIND`
declaration (2026-08-09).

**One READER for that declaration**, `base.drop_rule(section,
pane, index)`, beside the declarations themselves (2026-08-10). A
section declares one `DROP` unless its rows are different THINGS — the
File section — and then `DROP_BY_KIND`, with the row's `KindRole`
choosing the rule. That lookup was written twice, once in the drag code and
again inline in the click code, which is how a drag and a click end up
doing different things to the same tile: the exact bug `click_on_row` was built
to end, reintroduced one level down. The drag code keeps only its
key-to-class lookup, because a drag provides a section key and
a click provides the section.

**One RESOLVER for the handlers a rule names**, `base.drop_handler(
section, name)` (2026-08-13, ROADMAP line 24): every named handler — the
release bodies, the click handlers, the creation rules, the holder node
type — is a method of the declaring Section, and both drag and click
look it up there. The panel fallback the migration kept is REMOVED; a
declaration naming a handler its section does not define raises an error,
and `test_area_bindings` checks every declaration to keep it that way.
The panel keeps the shared release plumbing the handlers call
(`drop_placement.context_under_cursor`,
`drop_placement.release_position_in`, `drop_placement.create_holder_node`,
`drop_placement.scene_path`, `drop_placement.node_under_cursor`) — shared because it
has no per-type behaviour.

**THE SELECTION IS A HINT, NOT A VETO.** One visible selected node is
tried first; a node that cannot accept the drop FALLS THROUGH to
the creation step. Anything other than exactly one visible selected node
skips straight to that step. A menu's extra value (Color's ramp basis)
is passed as a `payload`, and only to handlers that declare they take one.

**WHICH MODELS A LIBRARY SWITCH REPOINTS is derived, not listed.**
Each section declares `library_model_attrs` — the panel attributes
holding data read from `prefs.dir` — and `pane.library.models()`
collects them for `switch_all_models()`, the ONE function. It was three
hand-written lists carrying seven models where there are eight, and
the missing one was the Colors sidebar, so a library switch left it
showing the previous library's categories with the new library's
counts (every row zero). A ninth model is included once declared;
`test_area_bindings` fails a repointable model no section names.

**EVERY WAY ONTO A LIBRARY IS ONE SEQUENCE**, `pane.library.open_library()`:
the newer-library check, `actions/library.py`'s `prepare`, the models
built (`setup`) or switched (`switch_all_models`), `$AMAZELIB`, the
version update, then the shipped starters. Opening the pane, Reload
Library, Apply on Preferences ▸ Library and closing Preferences on another
library all call it, and `test_switch_rereads` checks the order for all four. What each caller does itself: Reload Library saves
first, opening the pane and closing Preferences apply the log and cache
settings, and Apply asks `takes_library` before it writes anything.

**A LIBRARY AND ITS USER ARE PICKED TOGETHER** (Preferences ▸ Library,
P01). The Library list is settings.json's `libraries`; picking one shows
its users from its own `DataBase.json` ▸ `users` and preselects by name, then the
only user. Nothing switches until Apply, which opens the library with
the picked user and restores both when it fails to open. A user named
for a library not yet made is created after the library opens. At start
`open_library(needs_user=True)` stops after `prepare` when no user is
picked; once the pane has drawn, `ensure_library_user` asks to open
Preferences on this tab.

**The Sidebar Menu** is the same table, same builder (2026-08-04):
`Section.SIDEBAR_MENU`, rendered by the same `panel/grid.py` code that
renders `GRID_MENU`. Material, Node and Code share ONE table object -
not three equal copies - and File has its own entries for a location
(Label instead of Rename, Locate, and two per-location toggles). Moving
the three sidebar menus to tables needed exactly two additions to the builder: a
`checkable` field, and a per-CHILD enabled state so a submenu row greys
rather than vanishes.

**The Filter Menu** (the eye button, 2026-08-02) works the same way and
is the fuller form of the same idea: the Panel holds ONE menu and ONE
button for every tab, the Section defines what it offers (`filter_entries`,
plus `FILTER_CHOICES` and `filter_tooltip` as data) and what an entry
MEANS (`apply_filter`). The Panel passes the label to the Section and
the value back **without ever looking inside the value** — which is what
lets five tabs filter on five unrelated things through one control:
renderer (Material), palette size (Color), node context (Node), language
(Code), file kind (File). The three asset sections share one implementation,
because all three keep their kind in the same `RendererRole` field. The
choice is remembered per section in `settings.json` ▸ `section_filters`,
by LABEL; a remembered entry no longer on offer falls back to All.

---

## 4. The Engines — standalone, API-driven

An **Engine** is a FUNCTION of the system, not a piece of code: one
named responsibility the rest of the code calls through a small
stable API. An engine may span several scripts (the Drag & Drop Engine
is in core/dragengine.py + the gesture widgets + the panel's release
handlers) — the file listings below say where each one is TODAY,
which is an implementation detail, not the engine's identity. There are
six mapped here, plus the Drag & Drop Engine (its own
section below).

### 4a. The **Thumbnail Engine**

One byte-budgeted image cache + loader for *every* section. Keyed by
asset identity, never by row, so reloads/reorders can't show an image
on the wrong tile.

- **File:** `core/thumbnails.py` · **Singleton:** `thumbnails.engine`
- **API:** `request_file(key, path)` · `deposit(key, image)` ·
  `peek(key)` · `discard(key)` · `is_missing(key)` · `clear()`
- **Providers** (how an image is produced): **FILE** (materials/cop —
  load a PNG), **CONVERT** (one call to the **Conversion Engine** per
  image, off the UI thread), **RENDER** (geometry — Houdini flipbook),
  **PAINT** (colors/code — drawn in memory).
- **RAM budget:** the `ram_cache_mb` pref; evicted images reload from
  disk on demand.
- **Storage rule (no exceptions):** a LIBRARY-OWNED asset's thumbnail is part
  of the library — `<library>/img/<id>.png`, copied with it to other
  machines (Material, Node; an online import's preview becomes its
  library thumbnail). A thumbnail for content the library only POINTS
  AT (the File section's folders) is a regenerable local artifact — it
  goes in the OS-Integration Engine's per-OS cache, never synced. A
  CAPTURE, any tile's, is hand-framed and cannot be regenerated, so it
  is stored in the library too: `<library>/captures` (`core/captures.py`).
  Color/Code paint their pictures in RAM; a capture is the one picture
  they store.

### 4b. The **Conversion Engine** {#o/conversion}

One code path from a file on disk to a thumbnail-sized image, for every
section that shows a picture. It returns an image OR a **reason** —
never a bare None that hides which.

- **File:** `core/conversion.py` · **Entry point:**
  `convert_image(path, size, cancelled) -> Conversion`
- **Adapter API:** `produce(source, out_path, ctx) -> (wrote_it, why_not)`.
  An adapter writes a PNG into a scratch file the engine gives it and
  returns whether it worked. It does not set the order, does not verify
  output and does not log.
- **Adapters:** Qt-native (in-process, scaled decode), **sips**
  (macOS/ImageIO — registered TWICE, see below), **iconvert**
  (Houdini's own, correct for everything Houdini reads, `.rat`
  included), **Pillow** (in Houdini's own Python, so Windows and Linux
  have a converter).
- **The engine handles:** the order, the size contract, VERIFICATION of
  every adapter's output, the scratch-file lifetime, and one log line
  naming which adapter succeeded and why the one before it failed.
- **No preference.** There was a `Force iconvert only` preference, and a
  second adapter order to serve it; it was the manual workaround for a
  converter that returned a wrong picture and reported success, which
  is what the verification below now catches by itself. Removed
  2026-08-03. A control that reorders the adapters is a second adapter
  order in the engine, set from a preference.

**FORMAT and FIT are two different problems.** **FIT** is an image Qt
can read whose whole decode would pass its 256MB allocation limit —
the fix is another process, and it MUST resample while converting,
because a full-size temp file would pass the same limit again. **FORMAT** is
an image Qt cannot read at all (exr, hdr, rat) — not oversized, just
unsupported, so any converter may return any size and the engine scales
the result. **Which one applies is measured per FILE and is never a
property of the format**, which is why there is no `.hdr` special case
anywhere: `sips -Z` on a Radiance .hdr returns exit 0 and a solid
black picture, and `-Z` is used for FIT only. An unsupported
format that is ALSO oversized gets both steps, by the same
measurement applied to the converted temp.

Above a **1GB decoded ceiling** Amaze does not convert and returns the reason,
because every converter decodes the whole image before shrinking it.

**AN ENGINE VERIFIES ITS OWN OUTPUT; AN ADAPTER IS NEVER TRUSTED.** A
uniform result is treated as possibly wrong, not as a failure: try the next
adapter, and return the uniform one if no adapter does better.

### 4c. The **Database Engine**: guard, documents, library_db {#o/keyed-store}

Library format 2.0 (library version 4, `Format: v2.0`) keeps six
databases at the library root, each a JSON document of named sections,
every section a table keyed by id or key:

| File | Sections |
|---|---|
| `DataBase.json` | `policy`, `settings` (shared settings), `users`, `manifest`, `marks` |
| `materials.json`, `nodes.json`, `code.json`, `colors.json` | `assets`, `categories`, `comments`, `icons`, `favorites` (per user) |
| `files.json` | `locations` (per user), `paths`, `comments`, `icons`, `favorites` (per user) |

Beside them: `backup/` (every backup, named by database, date and time;
the newest 3 and one a day for 30 days; an unreadable copy once per
content) and `trash/` (one folder per day, each file under the path it
had, removed after 30 days). `.amaze-journal` is there only while a
change of several files is being applied.

- **`core/guard.py`** is the only module that reads and writes a library's files: a read
  returns a `Ticket`, a write must pass it back, and a change of several
  files is applied through a journal.
- **`core/documents.py`** holds each database as keyed sections and
  merges two users' changes per entry and per field.
- **`core/library_db.py`** keeps one `Library` per open library and
  keeps a pending save until the panel's timer writes it.
- **`core/library_conversion.py`** is the only code that reads an older
  library; it leaves `policy.json` so an older Amaze does not open it.

- **A location is an id, its path one property**: `files.json` ▸
  `paths` holds id → path, and every per-file key is
  `loc:<id>/<relative>`, so Locate Folder is one field edit. A file
  inside two nested locations belongs to the innermost
  (`locations.file_ident`).
- **A user writes only their own stars**: a file move or a location
  removal moves or removes this user's stars, never another user's.
- **Check Library never removes a location's file data**: a folder absent from
  this machine is removed from this user's `locations` only
  (`repair.set_aside_folders`), so its per-file keys stay in `files.json`.
- **`core/library_settings.py`** holds the shared settings and the
  overwrite switch in `DataBase.json` ▸ `settings`;
  **`core/library_policy.py`** the library's version stamp.

### 4d. The **Material Engine**

The single function every Karma material is built through. The engine handles
the container, the wiring, activation and verification; each input is an
**Adapter** that only produces a shader network.

- **File:** `render/nodes.py` · **Entry point:**
  `build_karma_material(parent, name, produce)`
- **Adapter API:** `produce(builder) -> (shader, displacement)`
- **Adapters:**
  - **MaterialX Translator** (`core/matx_translate.py`) — online `.mtlx`
    → clean VOP nodes, via Houdini's MaterialX Python API.
  - **USD Reader** (`core/matx_usd.py`) — a SimReady USD material's
    composed OpenPBR graph → the flat `.mtlx` the translator builds; the
    SimReady source reads its release zips by ranged requests
    (`matx_sources.open_remote_zip`, split archives included).
  - **Redshift Converter** (`render/material_converter.py`) — a Redshift
    material → equivalent Karma nodes.
  - **Karma → Redshift** (`render/redshift_converter.py`) — the reverse:
    any Karma container → a Redshift builder (`build_redshift_material`
    creates the container and its USD terminal), the online sources imported
    as Redshift through `matx_import`'s `renderer` switch.
  - **Values Adapter** (`matx_import._values_to_standard_surface`) —
    PhysicallyBased measured values → a preset shader.
  - **Classic Rebuild** (`render/classic_rebuild.py`) — the library
    conversion's node work: a Material saved in a classic container is
    loaded, rebuilt as its renderer's USD builder and saved back.
- **The Builder** — the container the engine makes:
  `make_karma_builder()` → a MaterialX Material Builder subnet matching
  **KARMA_REF** (see §8). Wired via `wire_builder_output()`; verified by
  `surface_terminal_wired()`.
- **The Material Conversion Engine** (`render/material_conversion/`) — every
  conversion between renderers, converted through MaterialX as the middle step.
  `engine.py` provides: `targets()` in menu order, `can_convert(source,
  target)` and `why_not` (a route exists and both plugins are loaded),
  `convert(container, source, target, parent, name)` returning
  `Converted(builder, shader, wired, report)`, and
  `ready_for_solaris(container, renderer)` for Copy To /stage. Each renderer is one API with the same
  calls - `available()`, `build(parent, name, produce)`,
  `to_materialx(container, builder, report)`, `from_materialx(container,
  parent, name, report)`, `for_solaris(container)`: `materialx.py` (the middle step,
  built by the Material Engine above), `redshift.py` (the Redshift Converter
  and Karma → Redshift), and `octane.py` (MaterialX copied into Octane's own
  builder, which renders MaterialX; the classic container rebuilt for
  Solaris) reading through `octane_reader.py` (Octane's nodes → MaterialX).
  A new renderer is a new module here and one entry in `core/renderers.py`,
  which names the module, its node types and the order every menu lists it. The callers:
  `MaterialLibrary.convert(index, target)`, the Convert to menu, the online
  import's `matx_import.to_renderer`, and `NodeHandler.load_items_file` on
  the way into a LOP library. `ConversionReport` is in `report.py`.

### 4e. The **Generator Engine**

Materials from MEASURED DATA. A generation is a **spec** — a plain dict of
named float/colour values — turned into a material through the
Material Engine's entry point. The spec is the interface a parametric UI or
rule system would set.

- **File:** `render/generator.py` · **Entry point:**
  `generate_random_material(parent, rng)` → `(builder, spec)`
- **Corpora** (shipped tables, no network, written by
  `tests/harvest_online.py`):
  - `res/physicallybased_materials.json` — 86 CC0 **reference**
    constants (real copper, water's 1.333 IOR, skin scattering radii).
    Its metals are idealised: roughness 0, a spectral identity.
  - `res/rgl_materials.json` — 62 CC0 **measured** materials (real
    surface roughness for brushed aluminium, felt, silk, paper).
  - `res/material_specs.json` — 287 **authored** materials, used only
    for the rates at which artists add clearcoat/sheen/emission.
- **Generation is per CLASS** (`fact_kind`): metals keep their
  spectrum (colour shifted, or blended toward another measured metal)
  and take their finish from the measured set; transmissive materials
  copy their IOR exactly; scattering materials keep their measured
  mean free path (cm → scene metres); only opaque dielectrics get a
  free hue, because pigment is arbitrary.
- **Provenance** — every generated material's node comment names the
  measurement it came from and what was varied.

### 4f. The **Debug Engine** {#o/debug-engine}

Structured session logging, JSON Lines. **Two tiers:**

- **Crash recorder — always on, only a real crash.** An *uncaught*
  exception (via the hook `install()` sets at panel construction) is
  written *even with Debug Mode off* — carrying the environment header
  (Houdini version, renderer plugins loaded). Nothing else is always-on.
  A quiet session writes nothing; a crash starts the log.
- **The settings snapshot — also always on.** `prefs_snapshot()` writes
  with Debug Mode OFF, deliberately: it is the recovery file the
  unreadable-settings dialog names for the user, and the session that
  needs it is exactly the one nobody had Debug Mode on for. Making it depend
  on Debug Mode would silently break that dialog, which is why it is named here.
- **Verbose tier — Debug Mode gated** (Preferences → Debug): `event()` /
  `note()` / handled `exception()`. Debug Off means off. Development
  sessions run with it on.

- **File:** `core/debug.py` · **Log:** `amaze_debug.jsonl` in the
  OS-Integration Engine's per-OS log dir
- **API:** `install()` · `configure(on)` · `exception(where)` ·
  `event(cat, msg)` · `ledger(cat, msg)` (an `event` the repeat limit
  never limits, one record per call: every database save) · `note(...)` ·
  `timed(cat, msg)` · `alert(msg)` · `refuse(reason)` · `set_ui(ui)` ·
  snapshots: `node_snapshot()` · `material_snapshot()`
- **The log imports neither `hou` nor Qt.** An alert's dialog, a
  refusal's status line and the session header's Houdini facts go
  through what `set_ui` was given: `utils/rc_calls.HoudiniUI`,
  passed in by `rc_calls.start()`, the first call of the pane, of every
  shelf tool and of the node menu's Amaze ▸ Save and Convert to entries.
  Until then alerts and refusals print.
- **`$AMAZE_LOG_DIR` moves the whole log dir, read ONCE at import** so a
  process can be isolated before any module has logged anything. The
  test runner sets it: the crash tier writes with Debug Mode off, so a
  suite that raises on purpose would otherwise fill the user's own log
  with genuine-looking crash records.
- **One repeating failure is written a limited number of times.** Identity is the
  event kind plus the exception type plus its deepest frame, so one
  frequent failure never suppresses a different failure. The first
  `REPEAT_VERBATIM` are written in full, then one marker at each power of
  ten and every `REPEAT_MARKER_EVERY` after that; a key quiet for
  `REPEAT_DECAY_SECONDS` counts as a new occurrence rather than a
  continuing repeat. An atexit flush writes each key's exact total, so a
  session that ended mid-repeat still records the full count.
- **A new file starts from zero — three functions reset the state.**
  `configure()` with a changed path, `redirect()` and `clear_log()` all
  reset the session id, the record counter, the rotation latch and the
  repeat counts, because `n` is a record's place in ITS OWN file and the
  counters are per-file too. The single exception is the alert history:
  a dialog the user dismissed stays dismissed through a move or a Debug
  Mode toggle, and only Clear Log forgets it.
- **The off-marker is written BEFORE logging is switched off.** `configure()`
  records *debug mode turned off* while `_enabled` is still true,
  because `event()` drops records the moment it goes false — and a
  verbose session log that simply stops looks like a crash. The ordering
  is required and has no test; reordering those two lines loses the
  marker silently.
- **Two of the snapshots are CONSOLE TOOLS, not wired** (2026-08-05):
  `image_stats` and `texture_snapshot` are called from the thumbnail
  path and are defined beside it in `preview/usd_scene.py`, `node_snapshot` and
  `material_snapshot` by hand from the
  Python shell during a diagnosis — they were written for the
  material/builder questions that keep coming back ("is it actually a
  Karma builder", "is the shader wired", "is the material wrong or
  only its thumbnail"). Noted here because a search for uncalled names
  finds them every time and reports them as unused.

### 4g. The **OS-Integration Engine**

Every platform branch is HERE - nothing else in the codebase may
test `sys.platform` or hardcode an OS path convention.

- **File:** `helpers/hostos.py`
- **API:** `cache_root()` / `log_root()` (per-OS conventional dirs -
  macOS `~/Library`, Windows `%LOCALAPPDATA%/Amaze`, Linux XDG - with
  one-time migration from every legacy location by rename) ·
  `open_path(p)` (system file browser) ·
  `bundled_binary(hfs, name)` (.exe-aware `$HFS/bin` lookup) ·
  `is_macos()/is_windows()/is_linux()`
- **Filename rules are here too**, because case-insensitivity is a
  platform fact: `matched_extension(name, extensions)` (the entry a
  filename ends with, LONGEST first so `x.bgeo.sc` is not `.bgeo`; one
  function for geometry, scenes and images, which had two copies and a
  third mechanism between them) and `migrate_legacy_file(dir, old, new)`
  (rename-once, best-effort, same-directory; three copies before).
- **`rename_exclusive(source, dest)`** — a rename that checks for an existing
  name in the same call, False when it exists: `renamex_np(RENAME_EXCL)` on
  macOS, `renameat2(RENAME_NOREPLACE)` on Linux, `os.rename` on Windows.
  It raises `NoExclusiveRename` where the drive has none, as a Mac's
  exFAT, FAT32 and network shares do; `file_moves.place` then tries a
  hard link, then creates the name as an empty file before renaming
  over it (▸r/no-replace-rename).
- **`disk_state(path)`** — `(mtime_ns, size)`, or None when the file is
  not there: the cheap stat the content stale-write guard keeps per
  asset (`AssetLibrary._content_stat`). The stores compare content
  fingerprints instead, through `file_fingerprint` and `peer_read`.
- **`why_failed(exc, path)` → `(cause, sentence)`** — the ONE place an
  `OSError` becomes something a user can act on: unreachable /
  read-only / full / held, from the errno. `database.save()` handled
  this inline and gave the same cause every time — *the file is
  held by another program* — which measured on macOS cannot happen at
  all, so a dropped synced folder was reported as a program holding the
  library. **An errno it has not measured gets NO cause**; a general
  message is correct when the cause has not been verified.
  Which errno means what is a platform fact, which is why it is
  here (2026-08-10).

### 4h. The **Preview Engine**

The scene a material thumbnail is rendered IN — ball, floor, lights,
camera, output — built per renderer, used once, destroyed. WHEN a
thumbnail is made and where the file goes are decided by the **Thumbnail
Engine** and the thumbnail runner (`render/thumbs.py`), its callers.

- **Package:** `preview/` · **Imported only as:** `amaze.preview`
- **API:** `ocio_from_viewer()` · `safe_set(node, parm, value)` ·
  `build_usd_scaffold(prefs, renderer)` · `write_batch(scaffold, items, out_dir)` ·
  `exr_to_png(exr, png, ocio, id)`
- **One scene.** Karma, Octane and Redshift render the SAME USD stage
  (`preview/usd_scene.py`): the shaderball USD with its own USD lights, a
  MaterialX floor, and per renderer only the render settings LOP, the USD
  Render ROP's delegate, the floor texture's format and a light scale
  differ, so the three tiles are lit alike by construction. Every renderer
  writes an ACEScg EXR that one conversion turns into the PNG through the
  viewer's OCIO display and view. A classic `octane_vopnet` is rebuilt into
  Octane's Solaris builder and a classic `redshift_vopnet` into the Redshift
  USD builder for the render, which LOPs can read. The `/obj` Redshift scene
  of 1.0 to 1.29 is gone: a render inside Houdini could not be ended, and
  twice froze a session until a force quit (▸r/redshift-thumbnail-stall).
- **One stage and ONE husk per batch, in the background.** `write_batch`
  writes the batch's stage once, every material its own prim, with the
  USD Render ROP's Run Command off; `render/husk_job.py` then runs ONE
  husk over it, frame N rendering material N — a pre-frame script binds
  it to the ball, since a binding cannot be animated — and a post-frame
  script names each frame's EXR, which `exr_to_png` turns into the tile's
  PNG as it is written. husk starts without the Houdini plugins of renderers
  it does not use; Octane restarts its delegate per frame or keeps the
  first material. Most of a thumbnail was husk starting, once per
  material (▸r/husk-startup). Like the `/obj` scene, it
  writes where the caller says: `png_path` is the caller's, per material.
- **The background job** (`husk_job.jobs`): one husk at a time, the rest
  queued; `progressed` updates the panel's thin bar, the Cancel button calls
  `jobs.cancel()` (husk is stopped, finished PNGs stay), and
  `thumbnailWritten(asset_id)` repaints that one tile. With no event loop
  (hython, the suite) `render_batch` runs the same husk to the end.
- **The part that is not Python:** the scene's node has seven spare
  parameters the caller sets — `mat`, `path`,
  `cop_out_img`, `resx`/`resy`, `obj_exclude`, `lights`, `render` — and
  `safe_set` ignores a missing one, so a replacement scene spelling one
  differently produces a wrong thumbnail rather than an error.
- **The scene's lifetime is the CALLER'S:** `thumbs.py` builds inside
  `hou.undos.disabler()` and destroys in a `finally`.

`tests/test_preview_boundary.py` checks that other code imports `amaze.preview`, never its submodules.

### 4i. The **Grid Engine** {#o/grid-engine}

What every grid model shows, and in what order, once: Materials, Nodes,
Code, Colors, File and Online all run on it. A model writes
`row_data(row, role)`, what one row returns, and names the lists it keeps
one entry per row (`GRID_ROWS`). The engine implements `data()`: column 0 is
the row's value, and a later column is the row's value for that
column's role, read from `row_data` directly - never a second `data()`
through a sibling index.

The engine also SORTS, the way Qt describes a model that sorts itself
(Model/View Programming ▸ Sorting): a header click is passed to the model
through `GridProxyModel.sort`, and the model moves its rows with one key
per row and one Python sort, as a single layout change that updates
every persistent index. The proxies never sort; their `sortColumn()`
stays -1, so they show the model's order and a filter change shows rows
again in it. New rows are sorted in at once by
`AssetLibrary._append_record`, which returns the row the record is at
now; rows another session added are sorted in at once too; a change to
a value the order uses, a rename say, re-sorts on the next event-loop turn;
a new thumbnail changes nothing the order uses and costs nothing. Two
panels on one library share each tab's order, because they share its
model (§5, the one model set). It is in `core/grid_engine.py`.

---

## 5. Models & storage

| Term | What it is | In code |
|---|---|---|
| **Library** | The on-disk folder holding every section's data: the six databases (§4c) + each asset section's folder (`materials/`, `nodes/`) + `backup/`, `trash/` + `matX/` (downloaded MaterialX). Path in `settings.json`. | — |
| **Library Model** | The Qt model over a **Library**'s JSON. The shared base class is `AssetLibrary` (records, categories, tags, tile icons, saves, deletes, the connector's guards — nothing renderer-specific); the four section models subclass it over their own JSON. `MaterialLibrary` adds what a MATERIAL is: its USD and shader-type labels, and the repaint when a render finishes; saving, updating, converting, loading and rendering one are `actions/materials.py`'s. Colors uses the same base class with its palette payload (`colors`/`ramp`) stored on the record. | `core/library.py` → `AssetLibrary`, `MaterialLibrary`; `cop_library.py`; `code_library.py`; `gradient_library.py` |
| **Material** | One asset record (id, name, categories, tags, renderer, date, …). **NOT a favourite and NOT a tile icon**: those are the database's `favorites` (per user) and `icons` sections. **One category per asset** — multi-category was removed 2026-07-27; tags are the many-to-many axis. | `core/material.py` |
| **Tile Icon** | A chosen Feather symbol on a colour, for assets with nothing to render; the section's database ▸ `icons` is the only store, keyed by asset id (a file key in `files.json`). Composed to `<id>_icon.png` BESIDE the render, never over it — except Color, which composes in memory. | `core/tile_icons.py` |
| **Comment** | A page of text + to-dos per asset (the Comments pane, toggled from the toolbar). Stored in the section's database ▸ `comments`, keyed by asset id or file key; a comment item belongs to its author. WHICH asset the pane shows is decided by the context — `Section.comment_subject(index)`, one of the four area hooks — because only the context can map an index through its proxy and read its roles; the panel finds the live current index and delegates. `takes_comments` is the separate, selection-free half that the toolbar chip reads. EVERY section takes notes, Color included - a gradient carries a full-uuid4 identity in `id` (from creation, or from the schema-8 migration that creates one for any row loaded without it — a construction-time backfill did this until 2026-08-20; the field was `uid` before 2026-08-09 and the VALUE never changed, so existing keys still resolve), keyed `gradient:<value>`. | `core/notes.py`, `panel/notes_panel.py` |
| **Category Colour** | A colour on a category, painted under every tile in it and down its sidebar row. Stored beside the category names in the same JSON, so the grid reads it from the connector's shared data dict. | `core/category.py` → `Categories.set_color` |
| **Sidebar Model** | What every Sidebar list is: All on row 0, the top rows, and the rows under a row, each row keyed by its parent row and its key. It answers the key role, `index_of(key)` and the reorder calls; the Categories Model, the Folders Model and the online source list are built on it. | `core/sidebar_model.py` → `SidebarModel` |
| **Categories Model** | The Sidebar list for an Asset section, a Sidebar Model with top rows only. | `core/category.py` → `Categories` |
| **Sidebar Proxy** | Presents the STORED category order (no sort — the manual order, 2026-08-14) and hides empty categories (renderer-aware). All four category sidebars go through it, Color included; the save dialog's dropdown keeps its own alphabetical sort. | `category.CategoriesSidebarProxy` |
| **Filter Proxy** | The Grid's search/renderer/favourite/tag filter (Asset sections). | `core/multifilterproxy_model.py` |
| **Asset Stack** | The four models an Asset section works through — Library Model, Filter Proxy, selection model, Categories Model — as `base.AssetStack`, whose fields are `model` / `proxy` / `selection` / `categories`. A bare 4-tuple until 2026-08-03: it was unpacked in nine places and read by NUMBER in three more (`st[0]`, `st[3]`), which is where a reorder would have gone unnoticed. | `section.stack()` |
| **Folders Model / Files Model** | The Folder-archetype pair (registered dirs / files inside). Folders share ONE base — `core/folders.py` `FolderTreeModel` (counts, add/remove/relocate, the scene row, and each folder's subfolders, read with its count on the same worker once its row shows), a Sidebar Model whose keys are folder paths; each section only names its prefs surface + extension predicate. | `core/folders.py`, `texture_library.py`, `geo_library.py`, `scene_captures.py` |
| **Online world** | A PARALLEL world, not a view mode over Materials (which is what it was until 2026-08-01). The toolbar's Online button enters it and turns green — the colour is the only indication — and the tab strip becomes the SOURCES in source order (Amaze first, then GPUOpen, PolyHaven, SimReady, PhysicallyBased, RGL) from `matx_sources.all_sources()`. The Amaze source browses the `AmazePackages` repository per TILE: folders under `packages/` are categories, every entry in every `.amazepkg` is one record read by ranged requests (a plain-file entry becomes a bare tile), and importing fetches only the chosen tiles' members. No File tab, and `enabled_sections` does not apply, because these are not sections. ONE strip, two lists: `_build_section_tabs` already rebuilt on an `enabled_sections` change, so switching worlds reuses that path. A tab click picks a source. Leaving returns you to the section you left from. `_is_online()` is now just the mode — it used to be `online_mode AND current_section == "material"` — and since 2026-08-15 six panel paths that branched on it call the CONTEXT instead: this world implements `search_hint`, `filter_text`, `filter_favorites`, `select_category`, `double_click` and an empty `SIDEBAR_MENU` like any section, so the eleven `_is_online()` reads left are all WORLD questions (which tab strip to build, which world a progress bar draws over) rather than section ones. Favourites and Comments are disabled here: an online record has no favourite state, and a comment is written against a library asset. | `panel.py` `enter_online_mode` / `leave_online_mode`, `core/matx_sources.py` |
| **Designed dialogs** | Every dialog is built on `base_dialog.AssetDialog` and takes its sizes and places from its drawn frame in `amazetheme.DIALOG_LAYOUT`, read through `theme.ui_px` like every other chrome measurement. No sizing path reads a device ratio: Houdini's UI scale is one number fixed at startup and it never rescales when a window moves between monitors, so neither does a dialog. A dialog's list (D01, D15) is `library_dialog.DialogTable`: the app's one table class with two columns, a name and a second text, painted by the host's style. The first designed shell, `ui_helpers.DesignedDialog` (the Versions dialog, 2026-08-02), was removed on 2026-10-25 with D01's dropdown. | `dialogs/base_dialog.py`; `helpers/ui_helpers.py` places each widget at its drawn box (`fit_drawn`) |
| **Filtering & sorting** | THREE proxies, one base: `core/grid_proxy.py`'s `GridProxyModel`, inherited by `MultiFilterProxyModel` (the asset sections and Online), `TextureFilterProxyModel` (File) and `GradientFilterProxyModel` (Color). They differ in what they FILTER ON; the base decides WHAT IS SHOWN, and the ORDER is the model's (the Grid Engine, §4i) - a proxy's `sortColumn()` stays -1, so rows coming back from a filter come back in the model's order and nothing re-sorts after an insert. `setDynamicSortFilter(False)` also turns off the re-test of a row whose DATA changed (2026-08-03 — un-favouriting a tile with Favourites-only on left it in the grid, star off), so the base restores that: role-aware (`watched_roles`) and coalesced onto one pass per event-loop turn. | `core/grid_proxy.py`, `core/multifilterproxy_model.py` |
| **Scrolling** | Both axes go through one handler: per-PIXEL scroll mode and `dragdrop_widgets.wheelEvent`, which reads the dominant axis, converts a classic wheel's 120-unit notches, and applies the `scroll_speed` preference. Horizontal was on Qt's per-ITEM default until 2026-08-01 — one step is a whole row, which feels like extreme acceleration — and it went unnoticed because nothing could scroll sideways until list rows grew wider than the panel. | `panel/dragdrop_widgets.py` |
| **Info** | A read-only table of facts about the selection (the Info pane, toggled from the toolbar; it and the Comments pane are never open together and share one saved width). WHAT it shows is the context's: `Section.info_subject(index)` for one row and `info_subject_for(indexes)` for several return a `file_info.Subject` - the header, the rows known at once, and at most one `Request` for rows that need a file read (a picture's facts from its header through `OpenImageIO`, or from Houdini's `iinfo` when OpenImageIO has no reader for the file, a geometry file's from `ginfo`, a USD stage's from `pxr`, the largest of a material's textures, the total size of several items). `file_info.Reader` runs that read on a worker thread and the pane puts its rows between the others. When one image file is selected, the pane also shows the picture above the table, whole and centred in an area whose height the drag line under it sets (the user setting `info_preview_height`), never taller than the picture is at the page's width; picture, line and table are one page that `side_pane.Body` places and scrolls as a whole, the table showing all its rows. `image_preview.Reader` reads the picture from the file at the pane's width in screen pixels on a worker thread, and reads it again when the pane is dragged wider. A button at the right of the header hides the picture and shows it again; the choice is the user setting `info_preview`, and while the picture is hidden the file is not read. `.rat` and `.pic` have no reader in OpenImageIO and get no picture; nor does any selection that is not one image file. A file is read only while the pane is shown: hiding it stops the read. `takes_info` is the selection-free half the toolbar chip reads. | `core/file_info.py`, `core/image_preview.py`, `panel/info_panel.py` |
| **Splitter panes** | THE construction: categories \| grid \| side pane, with exactly ONE flexible pane — the grid (stretch 1). Both other panes are `side_pane.Pane`, the pane engine's one pane class: it keeps its place in the splitter and returns its width from `sizeHint` (the width last dragged to, else the drawn width), so a pane that does not stretch is given exactly that. The side pane's Comments and Info are two PAGES of one pane, swapped in place, so they share one width by construction (`notes_panel_width`) and a switch resizes nothing. Every part of a pane — header, header buttons, picture, drag line, striped rows — is built once in the engine; a page is a `side_pane.Page` description listing its parts, and the engine's `Body` alone gives each part its place and size, so no part sets its own size and nothing depends on a scrollbar's width ▸r/info-pane-layout-loop. | `panel/side_pane.py`, `panel/panel.py` |
| **Prefs** | Settings, one shared instance injected into every model. `settings.json` is stored where the OS keeps preferences (`~/Library/Preferences/Amaze` on macOS, `%APPDATA%/Amaze` on Windows, `$XDG_CONFIG_HOME/Amaze` on Linux) — never in the install — and holds bootstrap, this machine's view state and last-known copies; the SHARED settings are the library's own, in `DataBase.json` ▸ `settings` (`core/library_settings.py`), read at load and written on save. Split in two 2026-08-09: `prefs.py` defines what a setting IS (64 property pairs plus the location, favourite and section-filter accessors), and `prefs/persistence.py` reads and writes it on disk — save, load, the field-wise merge between two panes of one session, the migration out of older installs, and the portable path encoding. `_Persistence` is mixed into `Prefs`, so every call site still calls `prefs.save()` and the document's shape is untouched. | `prefs/prefs.py` → `Prefs`, from `settings.json` |
| **Database** | One of the six JSON documents of keyed sections, read and written through the guard (§4c). | `core/guard.py`, `core/documents.py`, `core/library_db.py` |

### The stamp every library carries

`DataBase.json` ▸ `policy` ▸ `library` ▸ `version` (`library_policy`)
decides what this build may do: a library with a newer version opens read-only
and directs the user to the updater. There is no schema chain; an older library
is converted once by `core/library_conversion.py`, and
`prefs.create_library` writes the current version into a new library.

---

## 6. Dialogs — a convention, not an Engine

A **Dialog** is a modal form (save, edit, preferences, about). Dialogs
are *not* an Engine — they have no runtime pipeline, they're just forms —
but they share one house style, so that style is a **base class**, not
copied per dialog.

- **AssetDialog** — the shared base: a `QFormLayout` with right-aligned
  labels + fields right, native 5px margins, fixed size fitted to content,
  OK/Cancel. Helpers `add_line` / `add_combo` / `add_row` / `finish`. A
  new dialog is a few `add_*` calls, identical by construction.
  `dialogs/base_dialog.py`.
- **Section-owned** — a Section provides its own dialog through the
  Section API's `edit_dialog()` hook, as it defines its menu. Material →
  **Edit Info Dialog**; Code → its editor. File/Node can get
  one the same way when they need it.

| Dialog | Section | In code |
|---|---|---|
| **Edit Info Dialog** | Materials | `edit_material_info` / `details_dialog` |
| **Code Dialog** | Code | `dialogs/code_dialog.py` ✓ AssetDialog — typing a snippet (New Snippet, Edit), its versions behind the band's **+**; Apply saves and stays open. Houdini's Fixed face and its syntax colours (`helpers/vex_syntax.py`); a node's code saves through the Save Dialog |
| **Save Dialog** | every section a scene node saves into | `dialogs/save_dialog.py` ✓ AssetDialog — D09: Section, Name, Category, Language, Tags. The Section row is guessed from the node and changeable; `dialogs/gradient_dialog.py` keeps only `CategoryDialog` |
| **Preferences** | — (app-wide) | `dialogs/prefs_window.py` — Houdini's own kind of QML Preferences window: Houdini's prefs state on Amaze's Prefs, its `houdini.prefs` rows, Apply / Accept / Cancel; its pages are `ui/prefs/*.qml` (Library, Render, UI, Add-On, About), their rows in Houdini's `Group`s. A library and its user are picked there and opened on Apply; buttons act at once |
| **Icon Dialog** | any tile | `dialogs/icon_dialog.py` ✓ AssetDialog (non-modal) |
| **Manage Libraries** | — (app-wide) | `dialogs/library_dialog.py` ✓ AssetDialog — D15: the Library list, the most recently opened first; Remove from List takes libraries off it and leaves their folders alone |
| **Versions** | Materials | `dialogs/versions_dialog.py` ✓ AssetDialog — D01: a material's versions, newest first; Select makes the picked one active |
| **About** | — | a page of Preferences (`ui/prefs/AboutPage.qml`), with its Developer group — there is no separate About dialog |

*Adoption is complete* (R51, 2026-08-21) — every dialog is built on AssetDialog,
and `test_headless_dialogs` checks it: a new QDialog subclass in `dialogs/`
either subclasses the base or records its reason in a `HOUSE_STRAY` attribute.

---

## Drag & Drop Engine (core/dragengine.py + panel/dragdrop_widgets.py + core/lop_assign.py)

**`core/lop_assign.py`** is the USD half of a LOP viewport drop, split
out of the panel 2026-07-27: what is already bound under a prim,
rebinding it, naming an assign after the geometry it applies to, and
removing a material nothing references any more. No Qt, no panel — it
reports reasons rather than showing dialogs, so it is testable
headlessly (`tests/test_lop_assign.py`). The panel keeps the menu,
because choosing the prim is UI.

One SELF-MANAGED gesture for every section — no native QDrag, no drop
hooks. The widgets run press-move-release on the live event loop; the
engine handles everything about position and timing: throttled per-move picking
(`locateSceneGraphPrim` / `queryNodeAtPixel`), the drag image's target check
and the rect-tracked pane (`ghost_tick` / `pane_under_cursor_tracked` —
target checks at the picking rate, the pane kept by its screen rect
and checked again slowly, the outline following every move; a full
per-move lookup kept the event loop fully busy at the mouse's event rate,
2026-08-23), the hover highlight (in LOPs the viewer's own prim highlight;
at object level the host's own drop glow, asked for by `ViewportGlow` with drag
events sent to the viewport's window while no drag runs - no selection is read
or changed), release-target resolution (`viewport_release_target`),
container placement (`first_materiallibrary(connected_to=)`,
`find_assignmaterial`), Houdini's stock LOP helpers (`stock_lop()`), and
`keep_editor_focus` — a viewport release never moves the user's editors.
A drag has ONE end, `GridGestureMixin._end_drag`, reached by the release, Esc
(the view grabs the keyboard for the length of the drag), another mouse button,
a hidden view and an error while following the pointer; it is the only caller
of `dragengine.end()`. The name tag is hidden while another application is in front.
Sections' release handlers call the import code; the panel keeps
the shared plumbing. The one native drag left is the texture file drag.
Rules: an item is placed where it is dropped; nothing is created before release;
SOP and LOP contexts never reference each other; empty viewport space is a
miss (red X); a drop that opens a menu shows no icon.

## Storage format

An asset is two files in its section's folder: `<id>.mat`, a
Houdini-native node archive (via `saveItemsToFile`), and `<id>.json`,
its `metadata` and its `builder` (library format 4, 2026-11-16).
Recoverable with vanilla Houdini without the plugin, but not portable
outside Houdini (not `.mtlx`/`.usda`).

**Format 3 wrote two more**, `.interface` (Python from `asCode()`) and
`.builder.json`, and kept the metadata in `.stamp.json`. Only
`core/library_conversion.py` reads them: opening a format 3 library shows
the user a message once, then converts all of it before any model reads it - each
asset written new, read back and compared, and only then its old files
removed; an asset that fails to convert is set aside, its row removed
and its old files left untouched, and the user chooses whether they go to
the trash. The `.interface` is READ for its first `createNode("<type>"`
there, never executed. Nothing else reads an old format, and a test searches
the code to keep it so.

Executing `.interface` is what the builder data replaced. `asCode()` output is
Python whose only documented contract is that it RUNS, so importing a
material used to run whatever was in a file chosen by an id read
verbatim out of the database. The sidecar records the one thing only the
executed file held - the container's own parameter
interface and values - in a form that is parsed. Measured on a real
548-asset library: with sidecars present, every importable asset
reproduces byte-identically without executing a line.

### Where version files live — settled 2026-08-08, before Versions is built

    materials/versions/<asset id>/<writer>-<n>.mat
    materials/versions/<asset id>/<writer>-<n>.json    (the builder alone)
    materials/versions/<asset id>/<writer>-<n>.png
    nodes/versions/<asset id>/...                       (the same)
    code/versions/<snippet id>/<writer>-<n>.txt

A directory per asset id, and a file trio per version named for its
writer and an increasing number. A snippet's version is one text file:
code goes through the same module, `core/versions.py` taking the section,
with the same `versions.json`. Check Library reads every folder,
`code/` and both `versions/` trees included, and
`core/library_files.py` names a version file as one whose stem is
`<writer>-<n>` or `<n>` with a version suffix, in a folder named for an
alphanumeric id. Only the unlisted asset files of `materials/`, `nodes/`,
`mat/` while it is there are counted against the lists; a version file is a known
name and never one of them. Settled ahead of the Versions build so
that the classifier could be written against a shape that is known
rather than guessed: without a decided name, the first check after
Versions shipped would have counted every version file as unlisted.

`<writer>` is the artist's own **Library User** — the `library_user`
preference — never a machine or account name read from the system.

`library_user` is ONE identity: the name in version file names and
the key every per-user record is stored under. The removed `version_author`
is COPIED into it on load, so existing `<name>-<n>` stems still match their
writer. What prevents two writers using one filename is not the name — it is
skipping any stem already on disk before writing.

### The library's policy — `DataBase.json` ▸ `policy`

`allow_overwrite`, default **true**. When false, `update_asset_content`
(`actions/materials.py`) does not replace an existing asset's files,
and the Save dialog no longer offers Overwrite. It is checked in the function
every caller calls. Preferences has a control for it
(`_cbx_allow_overwrite`), and the value is stored in the library, so
two machines using one library have the same value. A policy that cannot be read
returns False (`library_settings.allow_overwrite`). `library` holds the
library's version (4, shown as `v2.0`).

### Housekeeping semantics (settled 2026-07-31)

Behaviour the reliability work changed, stated here because these are
contracts other code and the docs rely on:

- **Check Library never deletes.** Missing-file rows are reported and
  kept. Every move is into the library's `trash/<date>/` through one
  guarded change; a day expires after 30 days (`guard.TRASH_DAYS`), and
  every check and every open removes expired days (`guard.expire_trash`). Its
  check of the databases is `guard.health()`; every fix goes
  through `core/guard.py`: restore a backup, move to the trash, add orphaned
  files back, rebuild a lost database from each asset's `<id>.json`.
- **One survey, two callers.** `repair.survey` reads the library once
  (`library_files.walk`, one `os.scandir` per folder) and every report,
  button and count reads that one dict. In the panel it is called from Preferences ▸
  Library's Databases row (`prefs_window.AmazePrefsState._survey_open_library`):
  its button saves every model first (`check.save_before_check`), surveys, and
  shows `library_check.summary` as three lights; once something can be
  fixed it reads Repair and opens `repair_dialog.repair_found`, whose
  Fix Safe and Fix All act with `guard=False`, read every model again
  (`check.reload_after_check`) and check again. A part that cannot be checked
  (a database in use, a folder that cannot be listed) is never fixed.
  The shelf tool's function (`repair_dialog.run`) acts with `guard=True`,
  stops with a message while an Amaze pane is open, and only reports once this
  session holds a list.
- **The default Move Aside moves only files Amaze created**: unlisted asset
  files, scratch past an hour (`repair.SCRATCH_MIN_AGE`), `.pre-adopt`
  backups, and a sync service's duplicate of a backup tier, undo copy or
  preserved copy, or of a live file whose bytes equal the original's. A
  duplicate that differs, or whose original is absent, is listed and
  left in place. An unknown file or folder moves only by its own button and its
  own confirm.
- **Stars are per user IN THE LIBRARY**: each section's database holds
  `favorites` {user: {id: true}}, `files.json` the File stars; a user writes
  only their own (`locations.set_favourites`).
- **Backups**: a new one at most every 30 minutes, from the bytes the
  save already read, never of content that does not parse; the newest 3
  and one a day for 30 days are kept.
- **Shared entries merge per field**: different fields from two users
  are both kept; the same field keeps this session's value and the alert
  names the other user.

### What a library directory may contain

**`core/library_files.py` is the only module that defines it**: every name below, with
the exact patterns, is stated there once, and `library_files.classify`
returns what kind any path is. The table is the reading guide, not a second
copy. Anything else is one of four kinds, and the classifier returns
which: **scratch** (a write by Amaze that stopped partway: `.writing`,
`.capturing`, `.tmp`, `.lock` and the other suffixes in `SCRATCH_TAILS`,
or an `.amaze_scratch*` name), **pre-adopt** (`mat/<id>.mat.pre-adopt`,
`mat/<id>.builder.json.pre-adopt`), **duplicate** (a known name with
` <n>` before its last suffix, a sync service's second copy) or
**unknown**. OS noise (`.DS_Store`, `Thumbs.db`, `._*` and the rest of
`OS_NOISE`) is left alone and not reported. Check Library reports all
four; `tools/library-audit.py` loads the same module by path and
reports them too (`--strict` exits non-zero, so a script can fail on it).

| entry | what it is |
|---|---|
| `DataBase.json` | the library's own database: `policy` (`library` version, `allow_overwrite`), `settings` (the shared settings, one `{value}` per key), `users` (a `uuid4` UID per person with a `name`; names unique; nobody made silently), `manifest` (the databases this library has, so a missing one is detected), `marks` (the starters offered here once) |
| `materials.json` `nodes.json` `code.json` `colors.json` | each section's database: `assets` {id: row}, `categories` {name: {order, color}}, `comments` {id: {items}}, every item with its `id` and `author`, `icons` {id: face}, `favorites` {user: {id: true}}. Named once in `library_files` (`LISTS`, `LABELS`, `NOUNS`) and declared in `guard.DATABASES` |
| `files.json` | the Files section: `locations` {user: {`loc:<id>`: record}}, `paths` {id: {path}}, the one place a location's path is stored, and `comments`, `icons`, `favorites` keyed `loc:<id>/<relative>` |
| `backup/` | every backup: `<database>.<date>_<time>.bak`, the newest 3 and one a day for 30 days; `.before-restore.bak`, the undo copy a restore keeps; `.unreadable-<hash>`, one copy of a database that could not be read |
| `trash/<date>/…` | what a delete or Check Library moved, under its library path, removed after 30 days |
| `.amaze-journal` | there only while a change of several files is applied; finished at the next open |
| `policy.json` | after a conversion only: the file `{"library_version": 4}` an older Amaze reads, so it does not open the library. Nothing in this Amaze reads it |
| `materials/` `nodes/` | **each asset section's own folder** (library format 4), named once in `library_files.SECTION_FOLDERS` beside the section's database: `materials.json`'s rows use `materials/`, `nodes.json`'s use `nodes/`. Every path to an asset file is built from (section database, id) by `material.payload_path` |
| `materials/<id>.mat` | the asset's nodes |
| `materials/<id>.json` | everything else about the asset, through `core/asset_record.py` alone: `metadata` (the row as its database holds it - what a lost database is rebuilt from, an unlisted asset added back by, and the rows a put-back brings up to date) and `builder` (the container's type, its interface as a dialog script, and its changed values - read, never executed). Two writers share it, the save and the background metadata writer, so each replaces only its own section, under one lock |
| `materials/<id>_cop.mat` | a material's companion COP network |
| `materials/versions/<id>/<n>.*` + `versions.json` | the version store: each version's `.mat`, its `.json` holding the builder ALONE (so a metadata edit never makes two versions differ), its `.png`, and the version list. The conversion rewrote every archive made before format 4 the same way. The BASE files are always the active version's - losing this folder loses the history, never the material. Deleting the asset deletes the folder too: `asset_directories()` names it and `remove_asset` removes it |
| `nodes/…` | the same, for the Nodes section |
| `mat/` | **format 3's shared asset folder**, every section's files together, with `<id>.interface`, `<id>.builder.json` and `<id>.stamp.json` beside each `.mat`. The conversion (`library_conversion.convert`, from the panel's `open_library`, never by a headless open) moves each id's files and version folder to the folder of the database that names it, a file no database names to `materials/`; an id two databases name stays and is logged. It runs only while every database can be read. An empty `mat/` is removed; one with anything unknown left in it stays, and Check Library reports it as a leftover. The library stays below library version 3 until the conversion finishes, so after a crash the conversion runs again |
| `code/versions/<id>/<n>.txt` + `versions.json` | a snippet's versions: each one's text, and the same version list. The snippet's text in `code.json` is always the active version's; deleting the snippet deletes the folder too |
| `materials/<id>.png` (and `nodes/`, `code/`, `colors/`) | **the asset's only picture**, beside its files: a render or a capture, each replacing the other in place (`tile_icons.thumbnail_path`). The Icon menu's Image face shows it; Generic and Custom are composed for display and write no file. Code and Colors rows paint their own preview and have a picture file only once one is captured |
| `<section folder>/comments/` | the pictures pasted into that section's comments (`materials/`, `nodes/`, `code/`, `colors/`, `files/`) |
| `files/<40 hex>.png` | a File row's scene capture, by the SHA-1 of its key |
| `img/<id>.png` `img/<id>_icon.png` `captures/<id>.png` | format 3's pictures. The conversion keeps the one each tile showed as `<section>/<id>.png` and removes the rest |
| `matX/<package>/…` | MaterialX packages and their textures; Check Library does not enter it, the audit tool reports scratch there only |

**`backup/` is not clutter.** It is how a damaged database is restored;
a cleanup that removes it removes the recovery.

**Nothing temporary belongs here.** A surviving `.writing`,
`.capturing`, `.lock` or `.tmp` is always Amaze's and always means a save
stopped partway — reported separately from a merely unknown file, because
an unknown file might be the user's and a leftover scratch never is.
Check Library's default Move Aside moves a scratch file once it is an hour
old, so a live write in another session is left alone; an unknown file
moves only by its own button.

## 7. The Renderer terms

- **Renderer** — a material's render-engine label: `Karma`, `Redshift`,
  `Octane`, `COP`. Sets the Tile subtitle and the Renderer filter.
  `Mantra` was one until 2026-08-14, when it was dropped: SideFX is
  retiring the renderer, and 1.0 had not shipped, so nothing needed
  to be kept. A `materialbuilder` or `principledshader::2.0` now matches
  no renderer and is rejected at save rather than labelled. Online imports are plain Karma materials (their origin is recorded
  in the About/License credit, not the renderer tag).
- **Karma-family** — Karma plus the legacy stored labels MaterialX and
  MtlX, treated identically for routing, thumbnails and capability, and
  normalized to "Karma" everywhere via `renderers.normalized()`.
  One predicate: `renderers.is_karma()`.
- **The renderer table** — `core/renderers.py` holds every renderer once:
  the key libraries store, the name every menu shows, its icon, its
  converter module, its Preferences ▸ UI switch (and the key that
  switch is stored under), its Render tab samples row, and its plugin's
  node types: the classic container, the USD-builder a classic one is
  rebuilt as, and the user-data mark on its own builder, which save, load
  and import read from the table. A switch turned
  off hides that renderer from the Filter, Convert to and both Import
  menus and from the Render tab (`renderers.offered`); renaming one changes its
  `label`; the `key` never changes, because it is stored on disk.
- **USD-builder** — a material that can be used in a LOP/Solaris context
  (`rs_usd_material_builder`, `octane_solaris_material_builder`, and all
  Karma-family). MAT-only otherwise. Its tile shows `USD Redshift` or
  `USD Octane`.
- **Octane's own builder** — what Octane 2026.6's Create Material makes:
  a plain `subnet` carrying the user data `octane_material_builder = "1"`,
  which is how Amaze recognises it (`nodes.is_octane_builder`). It works
  in both /mat and LOPs like a Karma builder and saves WHOLE like one, so
  the marker is restored on import; its tile shows `Octane`, no `USD`.

---

## 8. Reference fixtures & conventions

- **KARMA_REF** — the hand-built reference material, the canonical
  structure every generated Karma material must match: a MaterialX
  Material Builder (`render_context = mtlx`) with `surface_output` /
  `displacement_output` subnetconnectors. The **Material Engine** builds
  to this shape. (A second, textured KARMA_REF is planned.)
- **`__activate__` toggle** — the per-input on/off switch that
  `editmaterial` adds and that drops a deactivated input from the USD
  export (the black-material bug). `activate_shader_inputs()` turns them
  all on; the **MaterialX Translator** avoids them entirely.
- **The 2× rule** — on a 2× (HiDPI/Retina) display, widget geometry
  renders at ~2× the code pixel value; QSS `border-width` renders 1:1.
  Pixel values are specified as *end* (rendered) pixels; code halves
  them.

---

## 9. Where things live (quick map)

```
panel/panel.py            The Panel: the widgets only - built, wired to the
                          pane engine's signals, and the dialogs it asks for
pane/pane.py              THE PANE ENGINE (`panel.pane`): no widget. Prefs, the
                          models, the sections and the shown one, tabs and
                          online, search, favourites, Filter choice, progress
pane/asks.py              what the engine asks of its host window (`pane.ui`):
                          names, colours, the drop menu, Versions, Save, Code,
                          Customize, Preferences; answers come by callback
pane/library.py           every way onto a library (`pane.library`): open,
                          switch, reload, update, users, older libraries
pane/sidebar.py           the sidebar's rows and selection (`pane.sidebar`)
pane/assets.py            favourite, delete, render, convert, Versions,
                          Customize, export (`pane.assets`)
pane/loading.py           a click on a row and Load Asset into the scene
                          (`pane.loading`)
pane/saving.py            scene nodes saved through D09, versions, snippets,
                          galleries (`pane.saving`)
pane/files.py             File's locations, paths, clipboard, file browser
                          (`pane.files`)
pane/online_import.py     The online import: catalogue records into the
                          library or the scene (`pane.online_import`)
pane/package_import.py    The package import: .amazepkg files and store
                          tiles into the library (`pane.package_import`)
pane/drop_placement.py    Where a drop or a click creates nodes: the network,
                          the position, the holder node (`pane.drop_placement`)
pane/tile_capture.py      Capture: the Scene View onto one tile, or the
                          open scene onto its File tile (`pane.tile_capture`)
sections/__init__.py      The Section registry: SECTION_CLASSES in tab order,
                          SECTION_INDEX, save_guess, build_sections
sections/base.py          Section and AssetSection, the declarations
                          (MenuEntry, DropRule, FilterEntry...), the shared
                          GRID_MENU_TAIL, drop_rule and drop_handler
sections/{material,node,code,color,file}.py  one Section each: its GRID_MENU and
                          SIDEBAR_MENU tables, DROP rules and every handler they
                          name, filters and empty texts; file.py holds
                          FolderSection, File's archetype
sections/online.py        The Online context, a Section's interface, no tab
panel/grid.py             The GRID area - the one right-click menu
                          builder over those tables
panel/sidebar.py          The SIDEBAR area - what a row means and what
                          may be dropped on it (the drag-hover handling)
panel/empty_state.py      EMPTY STATE ENGINE - which empty state an empty
                          grid is showing, and its text
panel/dragdrop_widgets.py Drag-and-drop into the network editor
core/thumbnails.py        THUMBNAIL ENGINE (cache, budget, loaders)
core/conversion.py        CONVERSION ENGINE (file -> QImage, verified)
core/guard.py             DATABASE ENGINE: the only module that reads and writes a library's files
core/documents.py         each database as keyed sections, the merge
core/library_db.py        one Library per open library, the save timer
core/library_conversion.py  the only code that reads an older library
render/nodes.py           MATERIAL ENGINE (build_karma_material) + save/import
render/cop_nodes.py       the Node section's contexts and containers: which context
                          a network holds, which container to create, and
                          where saved nodes load inside a wrapper HDA
core/debug.py             DEBUG ENGINE
core/workers.py           how every engine stops its QThreads (one shared
                          timeout, then terminate, then kept until exit) and
                          is replaced on a reload; base layer
core/grid_engine.py       GRID ENGINE (every grid model's cells and row order)
core/library.py           Library Model (Materials) + base for Cop/Code;
                          no cleanup of its own - Check Library is
                          core/repair.py's
core/model_registry.py    the ONE source-model set per library; panels are views
core/material.py          Material record
core/renderers.py         the renderer table: names, icons, switches, samples, converters,
                          and RENDERABLE_CONTEXTS, the node contexts whose tile can hold a render
core/category.py          Categories Model + Sidebar Proxy
core/sidebar_model.py     SidebarModel: what every sidebar list is (All, top rows, rows under a row)
core/multifilterproxy_model.py   Filter Proxy
core/matx_translate.py    Adapter: online .mtlx -> clean VOP
core/matx_usd.py          Adapter: a USD OpenPBR material -> that .mtlx
render/material_converter.py     Adapter: Redshift -> Karma
render/redshift_converter.py     Engine + adapter: Karma -> Redshift
render/material_conversion/engine.py      Material Conversion Engine: every pair via MaterialX
render/material_conversion/materialx.py   its MaterialX API, the middle step of every pair
render/material_conversion/redshift.py    its Redshift API, over the two converters above
render/material_conversion/octane.py      its Octane API: the MaterialX copy, classic -> Solaris
render/material_conversion/octane_reader.py   Adapter: Octane -> MaterialX
render/material_conversion/report.py      ConversionReport: what a conversion skipped
core/matx_sources.py      Online source adapters (GPUOpen/PolyHaven/...)
core/matx_import.py       Online import orchestration + Values Adapter
core/matx_library.py      Online Browser model
core/{gradient,cop,code}_library.py   the other sections' models
core/file_library.py      File Section models (rows by kind, folder cache cleanup);
                          the kinds themselves are core/locations.py's
core/users.py             WHO uses this library - a uuid4 UID per
                          person with a name beside it. Everything a
                          user owns is keyed by the UID, so a rename
                          changes the name and moves nothing
core/notes.py             comments: each database's `comments` section
core/packages.py          the .amazepkg container (library packages are
                          format 2): export collectors, guarded writer,
                          a reader that rejects a malformed package
core/addons.py            add-on packages (format 4, a Houdini package):
                          the one writer, the reader, the Add-On tab's
                          rows, the store's newest versions, the installer
                          into $AMAZE/addons/<folder> with the package file
                          Amaze.json's package_path reads, the on/off
                          switch (off/ is not loaded), the updater's copy
actions/addons.py         the add-on check and install the Add-On tab
                          runs: which store versions are newer, then
                          fetching and installing them, each result
                          shown in one sentence
actions/check.py          Check Library in the panel: `save_before_check`
                          saves every model and the settings before the
                          check acts, `reload_after_check` re-reads the
                          settings and every model after each action
                          (the Reload path without its save)
actions/code.py           the Code section's Houdini actions: a Python
                          snippet run as one undo step with a shelf
                          click's kwargs, and a snippet set onto a
                          node's code parm
actions/files.py          the File section's Houdini side: the geometry
                          render pass, and what the File models are
                          given when the panel builds them - $HFS, the
                          open scene, Write Paths As and the OS icons
actions/nodes.py          the Node section's Houdini actions: saving a
                          network or a selection as an asset, loading it
                          back, and re-rendering its tile
actions/materials.py      the Material section's Houdini actions: saving a
                          material, updating one in place, converting it
                          to another renderer, loading it and
                          re-rendering its tile in one batch
actions/library.py        the steps of opening a library that need no
                          panel: rejecting one a newer Amaze updated,
                          preparing its folder, updating it to this
                          Amaze's version, adding the shipped starters
core/texstore.py          the texture store: $AMAZELIB tokens, the
                          FileReference scan, the save-time copy of
                          referenced files and the scene-side path expansion
core/library_settings.py  the SHARED settings: DataBase.json ▸ settings
core/library_policy.py    the library's version stamp in DataBase.json
panel/side_pane.py        the pane engine: every part of a pane beside the
                          grid, built once (pane with its saved width,
                          header, buttons, picture, drag line, striped
                          rows); a pane or page is a description of parts
panel/notes_panel.py      the Comments page of the side pane
panel/info_panel.py       the Info page of the side pane: an image file's
                          picture, a drag line, then the selection's facts
                          as two-column rows
core/file_info.py         what the Info pane shows: the Subject a section
                          returns, the system's facts for a file, a picture's
                          header through OpenImageIO, the reads of Houdini's
                          iinfo and ginfo and of a USD stage, and the Reader
                          that runs one read on a worker
core/image_preview.py     an image file read straight into a picture as wide
                          as the Info pane shows it: Qt's reader for JPG, PNG,
                          BMP and GIF, OpenImageIO for the rest, the OCIO
                          display view on float files
core/{texture,geo}_library.py   per-kind models: image cache/proxy, geometry handling
render/thumbs.py          Thumbnail SCENE building (shaderball, flipbook)
render/husk_job.py        ONE background husk per thumbnail batch:
                          its command, progress, Cancel, each PNG
prefs/prefs.py            Prefs - what a setting IS (the property pairs)
prefs/settings_store.py   settings.json on this computer: read, merge, write
prefs/persistence.py      how it is STORED - save/load/merge/migrate,
                          mixed into Prefs, plus the portable paths
core/folders.py           FolderTreeModel (shared Folder-archetype base over SidebarModel, locations and subfolders)
core/file_moves.py        moves files between folders on a worker, never over an existing
                          name; a file's star, comment, icon and capture move with it.
                          Copies files too (Paste); a copy replaces a name only when told to
core/scene_captures.py    Scene View screenshots as tile thumbnails + open-scene state
core/scene_files.py       which file names are Houdini scenes (.hip,
                          .hiplc, .hipnc)
core/material_files.py    what a saved material's files contain, read as
                          text: its builder type and its shader type
core/captures.py          the capture store: <library>/captures, any tile
core/repair.py            CHECK LIBRARY's engine: one `survey` from one
                          folder scan, the one `report_lines`, and every
                          action (add back, put back, `repair_index`,
                          `move_aside`, set aside, uncategorised), each
                          taking `guard`; the only module that opens a
                          format 3 stamp; no `hou`, no Qt, no dialog
core/library_check.py     Preferences' Databases row over `repair`: the
                          three lights (`summary`: Errors, Files, Ref),
                          the Repair dialog's lines, and the two fixes,
                          `fix_safe` and `fix_all`; no `hou`, no Qt
dialogs/repair_dialog.py  the shelf tool's report, buttons, confirms
                          and answers (`run`, `check_failed_library`;
                          past `MOST_BUTTONS` actions, Choose an
                          Action), and `repair_found`, the Repair dialog
                          Preferences opens; never imports the pane
core/updater.py           is a newer Amaze released, and can this one
                          update to it - checked only on request, never at
                          launch (shelf tool + the About tab button)
core/asset_files.py       the files one asset owns, by kind - the one
                          module that names them, used by both the library
                          model and the version store
core/asset_record.py      the only module that reads and writes `<id>.json`: its
                          `metadata` and `builder`, a section at a time
core/library_conversion.py  library format 3 to 4, the ONLY module that
                          reads the old formats (`mat/`, `.interface`,
                          `.builder.json`, `.stamp.json`, `img/<id>.png`,
                          captures, old faces, old version archives);
                          converts a whole library before the models read
                          it, removes what it converted
core/versions.py          the version store of materials and code - the
                          base is always the ACTIVE version's, each
                          version also has an archived copy, and
                          versions.json is the version list
core/library_files.py     the naming convention, defined only here: every
                          name a library file may have, and what
                          anything else is - scratch, a duplicate,
                          unknown - plus `walk`, one scandir per folder
core/gallery_import.py    Houdini .gal gallery entries -> library assets
core/matx_icon.py         the PhysicallyBased icon, for value-only
                          online sources that ship no texture to render
core/bsdf_reader.py       reads the `tensor_file` container the measured
                          EPFL RGL BSDFs ship in
preview/                  THE PREVIEW ENGINE (below) - the scene a
                          material thumbnail is rendered in. Callers
                          use `amaze.preview`, never its submodules
preview/thumbnail_scene.py   what every path shares: safe_set and the
                          viewer's OCIO
preview/usd_scene.py      every renderer's one USD stage: written once
                          per batch, a material prim each
helpers/hostos.py         OS-INTEGRATION ENGINE (all platform branches)
helpers/wording.py        `and_list`, a sentence's list of names, and
                          `sanitize_usd_path`, a name USD accepts; every
                          layer shares one
helpers/hostver.py        HOST-CAPABILITY ENGINE - every "does this
                          environment behave differently here?" question
helpers/                  theme, ui widgets, vex syntax, generic helpers
utils/rc_calls.py         the entry points Houdini itself calls: the
                          OPmenu's Amaze submenu (Convert to Redshift,
                          Convert to Karma, Save), and the shelf's
                          Capture, Updates and Reload, one call each -
                          finds the open panel by its pane-tab label;
                          `start()` gives the log its `HoudiniUI`
branding.py               the app's DISPLAY name, once
amazetheme.py             THE DESIGN, in one document: every colour,
                          size, placement and word the designs set and
                          Houdini's theme does not. Edit a Figma
                          change here and nowhere else; helpers/theme.py
                          holds what FOLLOWS Houdini's live theme
messages.py               EVERY message Amaze shows in a dialog, in one
                          document - `displayMessage` and `debug.alert`
                          alike. Keyed by NAME, never a line number, so
                          the Figma register stays correct when lines move
                          ▸p/messages-in-three-places
dialogs/                  save / preferences / about / code / gradient dialogs
dialogs/user_dialog.py    the User list's rows, A to Z then the create
                          row
dialogs/library_dialog.py the Library list's Manage window: it removes
                          libraries from the list, never a folder
dialogs/versions_dialog.py a material's versions as a list; Select
                          makes the picked one active
dialogs/prefs_window.py   Preferences as Houdini's own QML window: its
                          prefs state reads and writes Amaze's Prefs;
                          the pages are ui/prefs/*.qml
dialogs/update_dialog.py  what an update asks and shows - Continue or
                          Cancel when it updates the library, then how
                          the install went; the About tab, the shelf's
                          Updates tool and the panel share it

tests/test_support.py     fixture_panel() - the ONLY way a test builds a
                          panel: own settings, library, caches, network
                          blocked, own registered file location
tests/assets/library/     the fixture library (a copy per test)
tests/assets/files/       the fixture File-section location, GENERATED by
                          make_file_fixtures.py - one tiny file per KIND
tests/test_no_live_data.py  the check: no test may read the machine's own
                          files. Source text check + runtime path check.
```

**A test never touches the machine's own data.** Never construct the
panel directly — use `test_support.fixture_panel(testcase)`, or
`fixture_panel(class_scope(cls))` for a class-scoped one. It asserts
every path it would touch is inside the temp dir before it returns.

---

## 10. How to use this doc

- To point at something: use the **Bold Caps** term. "The **File
  Section** filter is wrong", "add an event to the **Debug Engine**",
  "the **Redshift Converter** is producing X".
- To rename something: change the term here. The new name is canonical
  from then on (renaming code identifiers is a separate, explicit
  step).
- To add a concept: add a row/section here so it has a name before it
  is built.
- To reword the app's copy: edit the UI text register — every
  user-facing string, grouped by where it appears.
