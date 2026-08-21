# Amaze architecture & terminology

This is the **shared vocabulary** for the project. When a term here is
written in **Bold Caps** it is a *named part* — say "update the **Material
Engine**" or "the **Colors Section** is broken" and we both know exactly
what is meant. Rename a term in this file and the new name is the one to
use from then on.

Read this before a big change. Keep it current when the architecture
moves (this is the *what exists now* map; a private development log,
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
the code talks to through small, stable APIs. Each
tab is a **Section** object — a node-type-like plug-in that tells the
panel how to drive the shared widgets. Data is read/written through
**Models** backed by a **Library** folder on disk.

---

## 2. The shell — what you see

| Term | What it is | In code |
|---|---|---|
| **Panel** | The whole window. One class, built once. | `panel/panel.py` → `MatLibPanel` |
| **Toolbar** | Top strip, mirrored left: Categories, View + Filter menus, Online, Comments, Grid/List toggle, Favourites star, size slider, Filter box, then Capture (File tab only) and the Preferences gear at the far right. Categories and Online were promoted out of the View menu (2026-08-01): a control that toggles state is a button, not a menu row, and having both is how a toggle ends up disagreeing with the thing it toggles. Every chip's four state pixmaps come from `ChipToggleButton.set_art` — art as drawn at rest, hover lightens, and a chip whose ON state is carried by COLOUR (star amber, Online amber) does not lighten at all. Disabled chips paint at 50%. | built in `init_ui()`, states in `ui_helpers.ChipToggleButton.set_art` |
| **Section Tab Strip** | The Material/Color/Node/Code/File tab bar (singular since the 2026-07-31 merge; stored keys keep their historical names). Carries the **Cancel chip** at its right end: shown exactly while the conversion bar shows — `panel.set_conversion_bar_visible` is the bar's ONE visibility door and moves both — it stops the File section's image batch (flush first, then cancel). | `ui_helpers.SectionTabBar` |
| **Sidebar** | Left list: categories (asset sections + Color) or folders (File). Rows sit in the STORED order — the name sort retired 2026-08-14 — with "All" pinned to row 0 by the database, and the ORDER IS THE USER'S: hold a row for the platform's press-hold time (`QApplication.startDragTime`) and it grabs — live moves under the mouse, one write on release, Esc restores. One controller (`sidebar.SidebarReorder`) speaks the Section contract (`reorders_sidebar` + four verbs), so every section works the same and Online simply answers no. Whether a dragged tile may be DROPPED on a row is the context's answer — `Section.takes_category_drops` and `accepts_category_drop` — not a list of section keys held by the panel (`CATEGORY_SECTIONS`, retired 2026-08-04). | the `cat_list` widget, `panel/sidebar.py` |
| **Grid** | The main thumbnail area. GRID scales 64-512 with a magnet at 128; LIST is a table fixed at its smallest size (the slider greys out) whose row is as wide as its COLUMNS need, scrolling sideways rather than squeezing or dropping any. LIST mode is a real `QTableView` over a real `QAbstractTableModel` (the migration completed 2026-08-04); the painted header strip, `ListColumnHeader`, `ListColumns` and the delegate's list-painting branch are all retired. **The grid selection speaks in ROWS** (2026-08-06): a SelectRows selection answers one index per CELL - ten per row, hidden thumb column included - so every reader collapses to one index per row at column 0 through `grid_columns.selected_rows`, and the current, double-click and drag indexes are normalised to column 0 the same way (`live_current_index`, the panel's double-click entry, the drag press). The table carries the same context-menu and double-click wiring as the list view. The column ORDER lives once, in `core/grid_columns.COLUMNS`, which every grid model answers per column. WIDTHS are fixed defaults the user can DRAG (`panel.COLUMN_DEFAULT_WIDTH`, derived from the real library), with the last column taking the slack — nothing is measured at runtime. Tile badges are grid-only: at list size a badge is 12px and its art rasterises to a dark smudge, so those four facts are columns there instead. | the `thumblist` and `thumbtable` widgets, `panel/grid.py`, `panel/delegates.py` |
| **Tile** | One item in the Grid (thumbnail + name + subtitle). Painted by the **Tile Delegate**. | `AssetItemDelegate` |
| **Tile Badges** | ONE drawn family (2026-08-01): each glyph on its own dark backdrop (`ui/badge_*.svg` — the palette lives in the ART, never in code), rendered AS DRAWN through one engine (`_badge_pixmap`) at one size rule (`_badge_side`). Corners: top-left open scene, top-right favourite, lower-left versions, lower-right comment. TWO are BUTTONS, driven by the `BADGES` table: versions (click opens the Versions dialog) and, since 2026-08-21, favourite — always drawn where a section wires its click (every local grid, never Online): dim white star at rest, brighter on hover, amber when favourite, and a click toggles the selection's stars through the section's own `toggle_favourite`. Wiring the click (`set_badge_click`) is what MAKES a badge a button; hit-testing, hover and tooltips all derive from the same table. | `delegates.py` `_paint_badges`, `button_badge_at` |
| **Filter Box** | The search field in the Toolbar. | `line_filter` |

---

## 3. Sections — the node-types of the panel

A **Section** is one tab. It is a small object that tells the **Panel**
how to drive the shared widgets for its kind of asset. The Panel owns the
widgets and the data; a Section only says *what to do with them*.

**File:** `panel/sections.py`. **Registry:** `SECTION_CLASSES`. Adding a
section = a new class there, and nothing else: `sections.all_sections()`
derives `((key, label), ...)` from the classes, and everything that
lists the sections reads that one function - the tab strip, the
Show/Hide toggles, and the pref that persists them. `panel.ALL_SECTIONS`
is its cached result, not a second list to keep in step.

Read a KEY as an identifier, never as a name: keys are load-bearing in
saved preferences and in every asset record, and the retired
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

- **Online Browser** — a parallel WORLD with a Section's interface:
  `sections.OnlineContext`, reached through `panel._section()` like any
  section, so every area path stops asking which world it is in. It is
  NOT in `SECTION_CLASSES` and never appears in `enabled_sections`,
  because it is not a section. Its delegate carries only the roles
  `matx_library` has — no version, licence, comments or category
  colour — so the online grid cannot paint a column no online record
  can fill. Entering and leaving route through `_apply_context`, the
  one path a section takes, which is what stopped the Capture button,
  the search box and the Comments subject drifting when you went
  online. (2026-08-03; it was a view mode over Materials before.)

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
  (`('geo', path, cache_dir)`), scene rows serve viewport CAPTURES
  from `scene_captures`'s durable store, and unknown files draw their OS
  icon. Per-location recursion, custom names and the remove-time cache
  sweep live on `FileFolders`.

- **Gradient Archetype** (`GradientSection`) — the palette library.
  Color. Fully read-write: gradients are added (including from a
  dropped ramp node), renamed, recategorised and deleted, and so are
  their categories.


### The Section API (what every Section implements) {#o/section-api}

| Method | Called when | 
|---|---|
| `activate()` | its tab is selected — point the widgets at its Models |
| `stack()` | returns the **Asset Stack** — `sections.AssetStack`, read by NAME — or None |
| `filter_text(text)` | the **Filter Box** changes |
| `filter_favorites(on)` | the **Favourites Star** toggles |
| `filter_entries()` | the **Filter Menu** is rebuilt — `((label, value), …)`, everything-entry first |
| `apply_filter(value)` | an entry is picked, or the section is entered — narrow the grid to it |
| `select_category(index)` | a **Sidebar** row is clicked |
| `comment_subject(index)` | the **Comments** pane re-points — a `sections.CommentSubject` for that row, or None |
| `toggle_favourite(indexes)` | Favorite, on the **Grid** selection |
| `update_preview(indexes)` | Update Preview — offered only where `offers_preview_update` is True, i.e. where a preview is RENDERED rather than derived from the row's own content |
| `delete_rows(indexes)` | Delete, highest row first — offered only where `deletes_rows` is True (File has no Delete: its rows are files on disk) |
| `delete_prompt(count, name)` | what deleting costs, in this section's words — the wording lives in the UI text register |
| `sidebar_key(index)` | what a **Sidebar** row is keyed by — a category name in three sections, a registered folder PATH in File |
| `reorders_sidebar` + `sidebar_movable` / `move_sidebar_row` / `sidebar_order_snapshot` / `restore_sidebar_order` / `commit_sidebar_order` | the press-hold reorder (`sidebar.SidebarReorder` asks) — the base speaks the category form, File overrides in folder terms, Online answers no |
| `sidebar_colour(name)` / `set_sidebar_colour(name, colour)` | read and write that row's colour, in whichever store this context keeps it |
| `double_click(index)` | a **Tile** is double-clicked (the *primary action*) — routes through the **Click Door** below |
| `rc_menu()` | right-click on the **Grid** — renders `GRID_MENU` (below) |
| `catlist_menu()` | right-click on the **Sidebar** — renders `SIDEBAR_MENU` |
| `edit_dialog()` | open the section's edit **Dialog** (see §6), if any |
| `save_node(node)` | a scene node is dropped on the panel — route to this section's save flow |
| `prefs_changed()` | Preferences closed — re-scan live filesystem/render state |

The Panel's shared handlers dispatch to `panel._section().<method>()`
instead of branching on the section key.

Plus one piece of DATA, alongside `key` and `label`: **`search_hint`** —
what the **Filter Box** says while this section is active. It sits on the
ARCHETYPE, because the archetype is what decides the answer (Asset
sections take `:tag`, the File section has only a file name, Color also
matches the colour names inside a palette). The Panel writes it in
`_sync_filter_placeholder()`, called wherever the section or the view
mode changes; the **Online Browser** supplies its own, since its search
is a third thing again. Wording in the UI text register.

**A VALUE CARRIES ITS OWN NAME.** Several values travelling together go
as a named tuple, never a bare tuple read by position:

| named tuple | fields | what to watch |
|---|---|---|
| `sections.AssetStack` | `model proxy selection categories` | the four models an Asset section works through; read by NAME |
| `sections.CommentSubject` | `key section name type category colour` | `colour` is the CATEGORY's colour, not the comment's |
| `sections.FileLocation` | `path label colour` | the registered folder a File row came from; `label` is its custom name, else the path |

**The two DECLARATIONS a section author writes.** Both are data — names
of methods, never callables — and both fall through where a field is
undeclared.

`sections.DropRule`, the doors a row offers:

| field | aimed by | the verb takes |
|---|---|---|
| `on_node` | DRAG, cursor over a node | `(index, node)` |
| `on_space` | DRAG, cursor over empty network space | `(index, network, position)` |
| `resolve` | DRAG, finds its own landing | `(index)` |
| `outside` | DRAG, released outside the panel | `(index)` |
| `click_on_node` | CLICK, the SELECTION | `(index, node)` |
| `click_resolve` | CLICK, finds its own landing | `(index)` |
| `carrier_type` | — | name of what the space door CREATES, where that is a constant, so the drag ghost draws its shape from the same declaration the creator builds from |

`sections.MenuEntry`, one row of a menu table:

| field | what it declares |
|---|---|
| `label` | the row's text, from the UI text register; an empty one is a divider, and leading, doubled and trailing ones are dropped, so a table with conditional rows never places them by hand |
| `verb` | NAME of a method on the section, called as `verb(indexes, current, payload)` |
| `needs` | what makes the row LIVE — `any` (the default), `one`, `always`, or the name of a fact — and it greys, never hides |
| `shown` | the fact deciding whether the row EXISTS at all |
| `children` | a method returning `((label, payload, swatch_colour), ...)`, the colour a hex string or empty |
| `count_suffix` | appends ` (N)` on a multi-selection |
| `checkable` | the fact giving the CURRENT state, making it a tick-box whose verb is handed the state the user asked for |

**The Grid Menu** (2026-08-03) is the same idea for right-click. Every
context declares `GRID_MENU` — a tuple of `MenuEntry` rows, one per
entry — and `panel/grid.py` is the ONLY code that turns one into a
QMenu. A row carries its label (from the UI text register), the NAME of
the Section method that performs it, the fact deciding whether it EXISTS
(`shown`), what it needs to be LIVE (`needs`), and optionally the method
building a submenu's children. Names, not callables. The last four rows
are `GRID_MENU_TAIL` — Update Preview, Customize, Favorite, Delete —
shared by every context and gated on facts it already declares, so
adding a section adds no copy of them. Dispatch is a dict keyed by
QAction, never `==` against an action that may be None.

**The Click Door** is where a double-click AND the menu entry
labelled with the same verb both land — `panel.click_on_row`, one
precedence, read from the section's own `DROP` / `DROP_BY_KIND`
declaration (2026-08-09).

**One READER for that declaration**, `sections.drop_rule(section,
panel, index)`, beside the declarations themselves (2026-08-10). A
section declares one `DROP` unless its rows are different THINGS — the
File section — and then `DROP_BY_KIND`, with the row's `KindRole`
picking. That sentence was written twice, once in the drag walker and
again inline in the click walker, which is how two doors end up
disagreeing about the same tile: the exact bug the Click Door was built
to end, reintroduced one level down. The drag walker keeps only its
key-to-class lookup, because a drag arrives carrying a section key and
a click arrives carrying the section.

**One RESOLVER for the verbs a rule names**, `sections.drop_verb(
section, name)` (2026-08-13, ROADMAP line 24): every named verb — the
release bodies, the click verbs, the creation rules, the carrier-type
answer — is a method of the declaring Section, and both doors resolve
it there. The panel fallback the migration carried is REMOVED; a
declaration naming a verb its section does not define fails loudly,
and `test_area_bindings` walks every declaration to keep it that way.
The panel keeps the shared release plumbing the verbs call
(`_drop_context_under_cursor`, `_release_position_in`,
`_create_carrier`, `_scene_path`, `_node_under_cursor`) — shared
because it carries no per-type meaning.

**THE SELECTION IS A HINT, NOT A VETO.** One visible selected node is
offered the payload first; a node that cannot take it FALLS THROUGH to
the creation walk. Anything other than exactly one visible selected node
skips straight to that walk. A menu's extra word (Color's ramp basis)
rides as a `payload` and reaches only verbs that declare they take one.

**WHICH MODELS A LIBRARY SWITCH REPOINTS is derived, not listed.**
Each section declares `library_model_attrs` — the panel attributes
holding data read from `prefs.dir` — and `panel.library_models()`
walks them for `switch_all_models()`, the ONE route. It was three
hand-written lists carrying seven models where there are eight, and
the missing one was the Colors sidebar, so a library switch left it
showing the previous library's categories with the new library's
counts (every row zero). A ninth model joins by declaring itself;
`test_area_bindings` fails a repointable model no section names.

**The Sidebar Menu** is the same table, same builder (2026-08-04):
`Section.SIDEBAR_MENU`, rendered by the same `panel/grid.py` code that
renders `GRID_MENU`. Material, Node and Code share ONE table object -
not three equal copies - and File brings a location's own vocabulary
(Label instead of Rename, Locate, and two per-location toggles). Taking
the three sidebar menus needed exactly two additions to the builder: a
`checkable` field, and a per-CHILD enabled state so a submenu row greys
rather than vanishes.

**The Filter Menu** (the eye button, 2026-08-02) works the same way and
is the fuller form of the same idea: the Panel owns ONE menu and ONE
button for every tab, the Section says what it offers (`filter_entries`,
plus `FILTER_CHOICES` and `filter_tooltip` as data) and what an entry
MEANS (`apply_filter`). The Panel carries the label to the Section and
the value back **without ever looking inside the value** — which is what
lets five tabs filter on five unrelated things through one control:
renderer (Material), palette size (Color), node context (Node), language
(Code), file kind (File). The three asset sections share one route,
because all three keep their kind in the same `RendererRole` field. The
choice is remembered per section in `settings.json` ▸ `section_filters`,
by LABEL; a remembered entry no longer on offer falls back to All.

---

## 4. The Engines — standalone, API-driven

An **Engine** is a FUNCTION of the system, not a piece of code: one
named responsibility the rest of the code talks to through a small
stable API. An engine may span several scripts (the Drag & Drop Engine
lives in core/dragengine.py + the gesture widgets + the panel's release
handlers) — the file listings below say where each one lives TODAY,
which is an implementation detail, not the engine's identity. There are
six mapped here, plus the Drag & Drop Engine (its own
section below).

### 4a. The **Thumbnail Engine**

One byte-budgeted image cache + loader for *every* section. Keyed by
asset identity, never by row, so reloads/reorders can't misroute an
image.

- **File:** `core/thumbnails.py` · **Singleton:** `thumbnails.engine`
- **API:** `request_file(key, path)` · `deposit(key, image)` ·
  `peek(key)` · `discard(key)` · `is_missing(key)` · `clear()`
- **Providers** (how an image is produced): **FILE** (materials/cop —
  load a PNG), **CONVERT** (one call to the **Conversion Engine** per
  image, off the UI thread), **RENDER** (geometry — Houdini flipbook),
  **PAINT** (colors/code — drawn in memory).
- **RAM budget:** the `ram_cache_mb` pref; evicted images reload from
  disk on demand.
- **Storage rule (the law):** a LIBRARY-OWNED asset's thumbnail is part
  of the library — `<library>/img/<id>.png`, travelling with it across
  machines (Material, Node; an online import's preview becomes its
  library thumbnail). A thumbnail for content the library only POINTS
  AT (the File section's folders) is a regenerable local artifact — it
  goes in the OS-Integration Engine's per-OS cache, never synced —
  except scene CAPTURES, which are hand-framed and therefore durable
  (config_root, not the cache). Color/Code paint in RAM and store
  nothing.

### 4b. The **Conversion Engine** {#o/conversion}

One funnel from a file on disk to a thumbnail-sized image, for every
section that shows a picture. It returns an image OR a **reason** —
never a bare None that hides which.

- **File:** `core/conversion.py` · **Entry point:**
  `convert_image(path, size, cancelled) -> Conversion`
- **Adapter API:** `produce(source, out_path, ctx) -> (wrote_it, why_not)`.
  An adapter writes a PNG into a scratch file the engine hands it and
  says whether it worked. It chooses no order, trusts nothing, judges
  nothing and logs nothing.
- **Adapters:** Qt-native (in-process, scaled decode), **sips**
  (macOS/ImageIO — registered TWICE, see below), **iconvert**
  (Houdini's own, correct for everything Houdini reads, `.rat`
  included), **Pillow** (in Houdini's own Python, so Windows and Linux
  have a route).
- **The engine owns:** the order, the size contract, VERIFICATION of
  every adapter's output, the scratch-file lifetime, and one log line
  naming who answered and why the one before it did not.
- **No knob.** There was a "Force iconvert only" preference, and a
  second adapter order to serve it; it was the manual workaround for a
  converter that returned a wrong picture and reported success, which
  is what the verification below now catches by itself. Retired
  2026-08-03. A control that reorders the adapters is a second route
  through the engine wearing a preference's clothes.

**DECODE and FIT are two different problems.** **FIT** is an image Qt
can read whose whole decode would pass its 256MB allocation limit —
the way out is another process, and it MUST resample while converting,
because a full-size temp file is refused all over again. **FORMAT** is
an image Qt cannot read at all (exr, hdr, rat) — not oversized, just
foreign, so any converter answers at any size and the engine scales
the result. **Which one applies is measured per FILE and is never a
property of the format**, which is why there is no `.hdr` special case
anywhere: `sips -Z` on a Radiance .hdr returns exit 0 and a solid
black picture, and `-Z` belongs to the FIT route only. A foreign
format that is ALSO oversized gets both halves, by the same
measurement applied to the converted temp.

Above a **1GB decoded ceiling** Amaze declines and says so, because
every route inflates the whole image before shrinking it.

**AN ENGINE VERIFIES ITS OWN OUTPUT; AN ADAPTER IS NEVER TRUSTED.** A
uniform result is a SUSPICION, not a verdict: try the next adapter, and
deliver the uniform one if nothing does better.

### 4c. The **Keyed Store Engine** {#o/keyed-store}

One guarded JSON side-table, keyed by a stable identity, for every
store that keeps per-key choices beside the thing they belong to.

- **File:** `core/keyed_store.py` · **Entry point:**
  `open_store(spec, preferences) -> Store`
- **ONE FILE, ONE TABLE.** `open_store` caches per file, so every
  reader of a store shares one table and one stale-write baseline —
  and the cache identity is the CANONICAL path, because
  `preferences.dir` is not stable as text and two spellings of one
  directory would otherwise mint two Stores over one file.
  `own_store` is the deliberate opt-out, for a document whose holders
  legitimately disagree (two panes of one Houdini).
- **Adapter API:** a store is DATA — `register(filename, payload,
  keyspace, label, noun, …)` declares it; the adapter attaches its
  normaliser with `bind()`. **Registration is how a store comes into
  existence**, so `stores()` is the ONE enumeration for every consumer
  that may import the package — **Repair and the restore picker.**
  **`tools/library-audit.py` is NOT one of them and never can be**: it
  is deliberately pure stdlib, with no Houdini and no import from the
  package, so it runs on a machine where Houdini will not start or
  against a library copied onto a stick. It keeps its own hardcoded
  list, so **a new store has to be added in two places**, and the audit
  is the one that fails loudly — `--strict` reports an undeclared file
  as UNKNOWN and exits 1.
- **Adapters:** the **Comments store** (`core/notes.py` → `notes.json`),
  the **Tile Icon store** (`core/tile_icons.py` → `icons.json`), the
  **User store** (`core/users.py` → `users.json`), the **Shared
  Settings store** (`core/library_prefs.py` → `prefs.json`, the
  eighteen settings that are one answer for everyone who opens the
  library; `prefs/persistence.py` is the one consumer, with a
  last-known `shared_settings` copy in settings.json for when the
  library is unreachable), the **Location record** and **Favourites**
  (`core/locations.py` → `locations.json`, `favourites.json`), and
  **this machine's own settings** (`prefs/persistence.py` →
  `settings.json`) — the one store NOT in the library, because it holds
  the pointer to it.

  settings.json is a DOCUMENT, not a table of rows, and four
  declarations carry that: `payload=""`, `falsy_is_a_value` (`False`,
  `0` and `""` are answers, so removal is `retire`), `absence_is_fresh`
  (deleting it is its own prescribed recovery), and `merge_rules` keyed
  by a PATH with a wildcard so `users/*/file_folders` reaches a
  collected key. Its write door is `replace(document, retire=…)`, and
  retired keys drop AFTER the peer adoption or they are adopted
  straight back on every save.
  Favourites serve EVERY section since 2026-08-13, through one door —
  `locations.is_favourite` / `set_favourite` — keyed by file PATH for
  File rows and by bare asset id for Material/Node/Code/Color, the
  icons.json scheme; an id rides through the path conversion
  unchanged, and no path prefix can ever match one, so the location
  fan-outs never touch it.
  All six are files IN THE LIBRARY. The last two were views onto
  `settings.json` until 2026-08-05, which is why an icon or a comment on
  a file could disappear when you switched library while the file stayed
  registered: a File row's facts answered to two different scopes.
  `settings.json` keeps a COPY of both, written from the store and never
  read back into it — it is what the File section shows when the library
  is unreachable, and the shape an older build reads after a rollback on
  the SAME machine — `settings.json` is per-machine and does not travel
  between computers, so the copy is not back-compatibility for anyone
  else. Two computers sharing a library share these files directly, and
  a second computer's own registered folders MERGE in, adopt-only, the
  first time it runs this build. The pointer
  to the library (`directory`) stays in `settings.json`; it is the one
  thing that cannot live inside what it points at.
- **The engine owns:** the absence verdict, the damage latch, the
  restore tier, the field-wise merge, the atomic write, the key
  lifecycle, the user tag, and the one answer that carries a REASON.

**A store may declare its keys PER-USER**, and the engine tags them:
`Spec.user_tagged` prefixes the owner's UID as `<uid>|<key>` inside
`storage_key()`, the one door every read and write already passes
through. So one library holds everyone's per-user choices with each
person seeing only their own, and a rename relabels somebody without
moving a key.

- `all()` is SCOPED to the current user. `everyones()` is the unscoped
  read, for repair and migration only.
- No user picked means NO key rather than a shared one — the write is
  refused with `REASON_NO_USER`. An empty write still answers
  UNCHANGED, because doing nothing cannot fail.
- A key carrying no tag is DROPPED from every read surface and never
  held with the foreign values (those are written back). It waits in
  an orphan bucket until the first commit retires it from the file, so
  a store that decides its pre-tag rows are ADOPTED can file them
  under the current user first — `adopt_orphans()`, one write for the
  whole move. Favourites decided against and drop theirs for good;
  locations adopt theirs into whoever opens the library.
- Tagged today: `favourites.json` and `locations.json` — every star
  and every registered folder is one user's. A location removal still
  sweeps EVERY user's keys under the folder (`retire_stored`): a
  removal is a shared act, and the clean slate holds across the tag.
  With a library present and nobody picked yet, the File sidebar
  serves the settings copy instead of opening empty while the ASK
  dialog waits, and location writes refuse like a favourite's.

**Absence is a VERDICT the engine resolves, never a value a caller
receives.** Opening answers **READ** (parsed from a file that is
there), **FRESH** (absent, and nothing says it was ever here) or
**BLIND** (absent-but-proven, or present-but-unparseable). Only the
first two may be written. There is no `if os.path.exists(path):` in
any store, so there is no missing `else` for a store to be missing —
which is exactly what `icons.json` was missing.

**A read hands out a COPY; a write STAGES and commits only on
success.** The cache is a projection of the last successful write,
never a scratchpad a caller mutates in place — so a refused save can no
longer light a tile's comment badge for a note that was never written.

**The engine performs all three failure reports; the store supplies the
WORDS.** `unreadable_alert` when the file will not parse,
`refused_sentence` when a latched store declines a write, and
`denied_alert` when the disk refuses one — the last of which the
adapters used to do themselves, so `notes.py` and `tile_icons.py` held
the same ten lines with two words different and the other two stores
held none. The engine appends the CAUSE from
`hostos.why_failed` (§ 4g), so an instruction names the object that is
actually wrong.

**A blank `denied_alert` is a DECISION, and only two stores speak.**
Telling someone about a failure they can already see is worse than
silence. A comment and a tile icon stay on screen looking saved, so
nothing but an alert says otherwise — those two speak. A registered
location and a File favourite are DERIVED from their store and the
cache does not move on failure, so the folder never appears and the
star never lights: the gesture visibly does nothing, and that IS the
report. `test_alert_sink` asserts the whole SET, because an omission
and a deliberate silence read identically in a registry (2026-08-10).

**A key that MOVES moves in one write.** `rekey(moves)` is one guarded
commit for the whole rename, because a half-rewritten keyspace is worse
than the orphaning it fixes. Expressed as delete-then-add it is two
independent trips to disk, and a denial between them loses what was
being moved: `relocate_file_folder` did exactly that with a location's
own record until 2026-08-10, so one transient outage of a synced
library deregistered the folder and took its colour, custom name,
recursion and Show All Files with it. The door is
`locations.relocate_record(prefs, old, new)`.

**The owner announces, the engine fans out.** A folder that moved is
one call — `relocate(prefs, old, new)` — naming the prefix and no
store; a location that is gone is `retire_prefix(prefs, path)`. The
caller never enumerates the stores, because a list held by a caller is
a list someone can write short, and both callers that held one already
had been. Whether a store SURVIVES a location removal is
`survives_forget` on its spec — a product decision said once (comments
and tile icons stay; the location record dies with the pointer).

`<file>.json.bak-first` arrives on the FIRST write —
`hostos.seed_restore_floor` mints the write-once floor from the file
just created, since `snapshot_before_write` has nothing to copy yet.

### 4d. The **Material Engine**

The single funnel every Karma material is built through. The engine owns
the container, the wiring, activation and verification; each input is an
**Adapter** that only produces a shader network.

- **File:** `render/nodes.py` · **Entry point:**
  `build_karma_material(parent, name, produce)`
- **Adapter API:** `produce(builder) -> (shader, displacement)`
- **Adapters:**
  - **MaterialX Translator** (`core/matx_translate.py`) — online `.mtlx`
    → clean VOP nodes, via Houdini's MaterialX Python API.
  - **Redshift Converter** (`render/material_converter.py`) — a Redshift
    material → equivalent Karma nodes.
  - **Values Adapter** (`matx_import._values_to_standard_surface`) —
    PhysicallyBased measured values → a preset shader.
- **The Builder** — the container the engine makes:
  `make_karma_builder()` → a MaterialX Material Builder subnet matching
  **KARMA_REF** (see §8). Wired via `wire_builder_output()`; verified by
  `surface_terminal_wired()`.

### 4e. The **Generator Engine**

Materials from FACTS. A generation is a **spec** — a plain dict of
named float/colour values — turned into a material through the
Material Engine's funnel. The spec is the interface a parametric UI or
rule system would drive.

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
  spectrum (colour drifted, or blended toward another measured metal)
  and take their finish from the measured set; transmissive materials
  copy their IOR exactly; scattering materials keep their measured
  mean free path (cm → scene metres); only opaque dielectrics get a
  free hue, because pigment is arbitrary.
- **Provenance** — every generated material's node comment names the
  measurement it came from and what was varied.

### 4f. The **Debug Engine** {#o/debug-engine}

Structured session logging, JSON Lines. **Two tiers:**

- **Crash recorder — always on, only a real crash.** An *uncaught*
  exception (via the hook `install()` arms at panel construction) is
  written *even with Debug Mode off* — carrying the environment header
  (Houdini version, renderer plugins loaded). Nothing else is always-on.
  A quiet session writes nothing; a crash starts the log.
- **The settings snapshot — also always on.** `prefs_snapshot()` writes
  with Debug Mode OFF, deliberately: it is the recovery route the
  unreadable-settings dialog points the user at, and the session that
  needs it is exactly the one nobody had Debug Mode on for. Gating it
  would destroy that promise silently, which is why it is named here.
- **Verbose tier — Debug Mode gated** (Preferences → Debug): `event()` /
  `note()` / handled `exception()`. Debug Off means off. Development
  sessions run with it on.

- **File:** `core/debug.py` · **Log:** `amaze_debug.jsonl` in the
  OS-Integration Engine's per-OS log dir
- **API:** `install()` · `configure(on)` · `exception(where)` ·
  `event(cat, msg)` · `note(...)` · `timed(cat, msg)` · snapshots:
  `image_stats()` · `texture_snapshot()` · `node_snapshot()` ·
  `material_snapshot()`
- **`$AMAZE_LOG_DIR` moves the whole log dir, read ONCE at import** so a
  process can be isolated before any module has logged anything. The
  test runner sets it: the crash tier writes with Debug Mode off, so a
  suite that raises on purpose would otherwise fill the user's own log
  with genuine-looking crash records.
- **One repeating failure cannot flood the file.** Identity is the
  event kind plus the exception type plus its deepest frame, so a noisy
  neighbour never suppresses a different failure. The first
  `FLOOD_VERBATIM` are written in full, then one marker at each power of
  ten and every `FLOOD_MARKER_EVERY` after that; a key quiet for
  `FLOOD_DECAY_SECONDS` counts as a new occurrence rather than a
  continuing flood. An atexit flush writes each key's exact total, so a
  session that ended mid-flood still says how bad it got.
- **A new file starts from zero — one blank slate, three doors.**
  `configure()` with a changed path, `redirect()` and `clear_log()` all
  reset the session id, the record counter, the rotation latch and the
  flood counts, because `n` is a record's place in ITS OWN file and the
  counters are per-file too. The single exception is the alert history:
  a dialog the user dismissed stays dismissed through a move or a Debug
  Mode toggle, and only Clear Log forgets it.
- **The off-marker is written BEFORE the switch flips.** `configure()`
  records *debug mode turned off* while `_enabled` is still true,
  because `event()` drops records the moment it goes false — and a
  verbose session log that simply stops reads as a crash. The ordering
  is load-bearing and has no test; reordering those two lines loses the
  marker silently.
- **Two of the snapshots are CONSOLE TOOLS, not wired** (2026-08-05):
  `image_stats` and `texture_snapshot` are called from the thumbnail
  path, `node_snapshot` and `material_snapshot` by hand from the
  Python shell during a diagnosis — they were written for the
  material/builder questions that keep coming back ("is it actually a
  Karma builder", "is the shader wired", "is the material wrong or
  only its thumbnail"). Said here because a scan for uncalled names
  finds them every time and reads them as dead.

### 4g. The **OS-Integration Engine**

Every platform branch lives HERE - nothing else in the codebase may
test `sys.platform` or hardcode an OS path convention.

- **File:** `helpers/hostos.py`
- **API:** `cache_root()` / `log_root()` (per-OS conventional dirs -
  macOS `~/Library`, Windows `%LOCALAPPDATA%/Amaze`, Linux XDG - with
  one-time migration from every legacy location by rename) ·
  `open_path(p)` (system file browser) ·
  `bundled_binary(hfs, name)` (.exe-aware `$HFS/bin` lookup) ·
  `is_macos()/is_windows()/is_linux()`
- **Filename semantics live here too**, because case-insensitivity is a
  platform fact: `matched_extension(name, extensions)` (the entry a
  filename ends with, LONGEST first so `x.bgeo.sc` is not `.bgeo`; one
  function for geometry, scenes and images, which had two copies and a
  third mechanism between them) and `migrate_legacy_file(dir, old, new)`
  (rename-once, best-effort, same-directory; three copies before).
- **`disk_state(path)`** — `(mtime_ns, size)`, or None when the file is
  not there: the fingerprint every store keeps so it can tell whether
  ANOTHER session wrote the file since this one read it. Three stores
  (`Prefs`, `keyed_store.Store`, `texture_library.ThumbnailCache`) each
  built it inline on both the remember and the compare side — six
  sites, 2026-08-05.
- **`why_failed(exc, path)` → `(cause, sentence)`** — the ONE place an
  `OSError` becomes something a user can act on: unreachable /
  read-only / full / held, from the errno. `database.save()` answered
  this inline and answered it the same way every time — *the file is
  held by another program* — which measured on macOS cannot happen at
  all, so a dropped synced folder was reported as a program holding the
  library. **An errno it has not measured claims NO cause**; saying
  nothing specific is the right answer to a cause nobody verified.
  Which errno means what is a platform fact, which is why it lives
  here (2026-08-10).

### 4h. The **Preview Engine**

The scene a material thumbnail is rendered IN — ball, floor, lights,
camera, output — built per renderer, used once, destroyed. WHEN a
thumbnail is made and where the file goes belong to the **Thumbnail
Engine** and the thumbnail runner (`render/thumbs.py`), its callers.

- **Package:** `preview/` · **Door:** `amaze.preview`
- **API:** `ThumbNailScene(renderer)` → `.get_node()` · `.rop` ·
  `ocio_from_viewer()` · `safe_set(node, parm, value)` ·
  `rig_key(renderer)` · `build_karma_scaffold(prefs)` ·
  `render_karma_into(scaffold, node, id, png_path)`
- **The two light rigs are ONE table.** Redshift and Octane place their
  key lights from shared constants and differ only in the size parm's
  spelling (`areasize1/2/3` against `sx/sy/sz`); `rig_key` answers which
  spelling a renderer uses and RAISES on one the table does not name,
  rather than placing a light with no size. Intensity is not shared —
  the two use different physical models.
- **Karma is the odd shape and the caller still names the file.** Its
  scene is a USD stage, too expensive to build per material, so it is
  built once and rendered into many times — but like the other three it
  writes where the caller says, which is why `png_path` is an argument
  rather than something the engine works out from the library.
- **The part that is not Python:** the scene's node carries seven spare
  parameters the caller drives it through — `mat`, `path`,
  `cop_out_img`, `resx`/`resy`, `obj_exclude`, `lights`, `render` — and
  `safe_set` swallows a missing one, so a replacement spelling one
  differently produces a thumbnail-shaped no-op rather than an error.
- **The scene's lifetime is the CALLER'S:** `thumbs.py` builds inside
  `hou.undos.disabler()` and destroys in a `finally`.

`tests/test_preview_boundary.py` keeps the door a door.

---

## 5. Models & storage

| Term | What it is | In code |
|---|---|---|
| **Library** | The on-disk folder holding an asset section's data: `library.json` (index) + `mat/` (node archives) + `img/` (thumbnails) + `matX/` (downloaded MaterialX). Path in `settings.json`. | — |
| **Library Model** | The Qt model over a **Library**'s JSON. The shared engine is `AssetLibrary` (records, categories, tags, tile icons, saves, deletes, the connector's guards — nothing renderer-shaped); the four section models subclass it over their own JSON. `MaterialLibrary` adds what a MATERIAL is: renderer detection, USD/shader labels, the Karma render batch, MAT/LOP routing, the Redshift conversion. Colors rides the same engine with its palette payload (`colors`/`ramp`) carried on the record. | `core/library.py` → `AssetLibrary`, `MaterialLibrary`; `cop_library.py`; `code_library.py`; `gradient_library.py` |
| **Material** | One asset record (id, name, categories, tags, renderer, date, …). **NOT a favourite and NOT a tile icon** — both were retired from the record by schema 5 and live in `favourites.json` (per-user, since 2026-08-13) and `icons.json` respectively; schema 7 retired `builder` the same way (write-only since the Mantra import path left, 2026-08-14); `Material._RETIRED_KEYS` names all three so they are recognised and dropped rather than carried as unknown keys. **One category per asset** — multi-category was removed 2026-07-27; tags are the many-to-many axis. | `core/material.py` |
| **Tile Icon** | A chosen Feather symbol on a colour, for assets with nothing to render; **`icons.json` is the ONE home**, keyed by asset id in every section, and since schema 5 the ONLY home — the record field that used to back it up is stripped from every row, so there is no second answer to drift. Composed to `<id>_icon.png` BESIDE the render, never over it — except Color, which composes in memory. | `core/tile_icons.py` |
| **Comment** | A page of text + to-dos per asset (the Comments pane, toggled from the toolbar). Renamed from Notes 2026-08-01 - the WORDS changed, every identifier did not: `NotesRole`, `notes.json`, `notes_panel.py` and the `show_notes` / `notes_panel_width` keys are contracts with data on disk and with other machines. Stored in `notes.json` beside the index, keyed `<section>:<id>` / `file:<path>`, wearing icons.json's guard set (unreadable latch, adopt-on-write, snapshot tier). Tiles with a note carry the lower-right badge via `NotesRole` (UserRole + 10, both model families). WHICH asset the pane points at is the context's own answer — `Section.comment_subject(index)`, one of the four area hooks — because only the context can map an index through its proxy and read its roles; the panel finds the live current index and delegates. `takes_comments` is the separate, selection-free half that the toolbar chip reads. EVERY section takes notes, Color included - a gradient carries a full-uuid4 identity in `id` (from birth, or from the schema-8 migration that mints one for any row arriving without it — a construction-time backfill did this until 2026-08-20; the field was `uid` before 2026-08-09 and the VALUE never changed, so existing keys still resolve), keyed `gradient:<value>`. | `core/notes.py`, `panel/notes_panel.py` |
| **Category Colour** | A colour on a category, painted under every tile in it and down its sidebar row. Stored beside the category names in the same JSON, so the grid reads it from the connector's shared data dict. | `core/category.py` → `Categories.set_color` |
| **Categories Model** | The Sidebar list for an Asset section. | `core/category.py` → `Categories` |
| **Sidebar Proxy** | Presents the STORED category order (no sort — the manual order, 2026-08-14) and hides empty categories (renderer-aware). All four category sidebars go through it, Color included; the save dialog's dropdown keeps its own alphabetical sort. | `category.CategoriesSidebarProxy` |
| **Filter Proxy** | The Grid's search/renderer/favourite/tag filter (Asset sections). | `core/multifilterproxy_model.py` |
| **Asset Stack** | The four models an Asset section works through — Library Model, Filter Proxy, selection model, Categories Model — as `sections.AssetStack`, whose fields are `model` / `proxy` / `selection` / `categories`. A bare 4-tuple until 2026-08-03: it was unpacked in nine places and read by NUMBER in three more (`st[0]`, `st[3]`), which is where a reorder would have gone unnoticed. | `section.stack()` |
| **Folders Model / Files Model** | The Folder-archetype pair (registered dirs / files inside). Folders share ONE base — `core/folders.py` `FolderListModel` (counts, All row, add/remove/relocate); each section only names its prefs surface + extension predicate. | `core/folders.py`, `texture_library.py`, `geo_library.py`, `scene_captures.py` |
| **Online world** | A PARALLEL world, not a view mode over Materials (which is what it was until 2026-08-01). The toolbar's Online button enters it and turns amber — the colour is the whole signal — and the tab strip becomes the SOURCES in source order (GPUOpen, PolyHaven, PhysicallyBased, RGL) from `matx_sources.all_sources()`. No File tab, and `enabled_sections` does not apply, because these are not sections. ONE strip, two lists: `_build_section_tabs` already rebuilt on an `enabled_sections` change, so switching worlds reuses that path. A tab click picks a source. Leaving returns you to the section you left from. `_is_online()` is now just the mode — it used to be `online_mode AND current_section == "material"` — and since 2026-08-15 six panel paths that branched on it ask the CONTEXT instead: this world answers `search_hint`, `filter_text`, `filter_favorites`, `select_category`, `double_click` and an empty `SIDEBAR_MENU` like any section, so the eleven `_is_online()` reads left are all WORLD questions (which tab strip to build, which world a progress bar draws over) rather than section ones. Favourites and Comments are disabled here: an online record has no favourite state, and a comment is written against a library asset. | `panel.py` `enter_online_world` / `leave_online_world`, `core/matx_sources.py` |
| **Designed dialogs** | `ui_helpers.DesignedDialog` is the shell the UI designs describe, and the one to reuse: a dark header band (icon, subtitle, bold title, kind line) over a body column inset equally both sides, `add_field()` placing the design's uneven gaps and `add_buttons()` the pair that fills the column. Measurements come from the Figma frame and are stated once as the class CONSTANTS, HALVED — the pages are drawn at 2×, so a design number is halved at source and then goes through `theme.ui_px` like every other chrome measurement (the 2× rule, §8). No sizing path reads a device ratio: Houdini's UI scale is one number fixed at startup and it never rescales when a window moves between monitors, so neither does a dialog. The two SURFACE colours follow Houdini's theme; the INK is literal, being the design's own answer rather than a token. First use: the Versions dialog, 2026-08-02. | `helpers/ui_helpers.py` |
| **Filtering & sorting** | THREE proxies, one base: `core/grid_proxy.py`'s `GridProxyModel`, inherited by `MultiFilterProxyModel` (the asset sections and Online), `TextureFilterProxyModel` (File) and `GradientFilterProxyModel` (Color). They differ in what they FILTER ON; the base owns WHAT IS SHOWN AND IN WHAT ORDER. `setDynamicSortFilter(False)`, set for performance, turns off three things at once, and each came back as a caller remembering: the re-sort after a filter change (2026-08-01 — picking a category then going back to All came back unsorted), the re-sort after an INSERT (2026-08-03 — a newly saved asset landed at the bottom of 548), and the re-test of a row whose DATA changed (2026-08-03 — un-favouriting a tile with Favourites-only on left it in the grid, star off). The re-test is role-aware (`watched_roles`) and every pass is coalesced onto one per event-loop turn. | `core/grid_proxy.py`, `core/multifilterproxy_model.py` |
| **Scrolling** | Both axes go through one handler: per-PIXEL scroll mode and `dragdrop_widgets.wheelEvent`, which reads the dominant axis, converts a classic wheel's 120-unit notches, and applies the `scroll_speed` preference. Horizontal was on Qt's per-ITEM default until 2026-08-01 — one step is a whole row, which reads as wild acceleration — and it went unnoticed because nothing could scroll sideways until list rows grew wider than the panel. | `panel/dragdrop_widgets.py` |
| **Splitter panes** | THE construction (2026-08-01): sidebar \| grid \| comments, with exactly ONE flexible pane — the grid (stretch 1); both side panes hold (stretch 0), so every redistribution Qt performs lands on the grid. Each side pane OWNS its width: BOTH are `ui_helpers.HeldPane`, which asks for the remembered drag or the design width through `sizeHint`, and `_on_splitter_moved` records both into `sidebar_width` / `notes_panel_width`. Nothing on the panel computes a pane's width: measured 2026-08-03, the splitter has already honoured the hint before any post-show code runs, so the 50 lines that redistributed for the Comments pane were recomputing what was true. Never bookkeeping around Qt's relayout — that shipped once and lost. | `panel.py` `_build_splitter_and_sidebar`, `ui_helpers.HeldPane` |
| **Prefs** | Settings, one shared instance injected into every model. `settings.json` lives where the OS keeps preferences (`~/Library/Preferences/Amaze` on macOS, `%APPDATA%/Amaze` on Windows, `$XDG_CONFIG_HOME/Amaze` on Linux) — never in the install — and holds bootstrap, this machine's view state and last-known copies; the eighteen SHARED settings are the library's own, in `prefs.json` through the Shared Settings store (§4c), adopted at load and pushed on save. Split in two 2026-08-09: `prefs.py` answers what a setting IS (64 property pairs plus the location, favourite and section-filter accessors), and `prefs/persistence.py` carries it to and from disk — save, load, the field-wise merge between two panes of one session, the migration out of older installs, and the portable path encoding. `_Persistence` is mixed into `Prefs`, so every call site still says `prefs.save()` and the document's shape is untouched. | `prefs/prefs.py` → `Prefs`, from `settings.json` |
| **Database** | The JSON read/write layer, one connector per JSON filename — **all four databases, since 2026-08-09**. | `core/database.py` |

### The two stamps every database carries

- **`version` — the SCHEMA**: what shape the document is in. A load
  applies `_MIGRATIONS` up to `SCHEMA_VERSION` (**7**), and three steps
  are registered. **4→5** strips the retired `favorite` and `icon`
  fields from every row; `icon` moved to `icons.json`, and neither is
  left to the unknown-key courtesy, because a key carried verbatim
  would be written straight back by the next save. **5→6** strips
  `favorite` again, and the second pass is the interesting one: Colors
  is the one section whose rows never pass through `Material`, so
  nothing dropped the field on read and every colour star toggled after
  the 4→5 step landed back on the shared document. Stars live in
  `favourites.json` now, per-user and owner-tagged — a field on a
  shared record is everyone's, which was the defect. Stripped rather
  than adopted, matching the File store's rule that a star with no
  owner is nobody's. **6→7** strips `builder` — written by every save
  since the fork, read by nothing since the Mantra import path was
  removed 2026-08-14, so the field came off the format (decided
  2026-08-17); `Material._RETIRED_KEYS` names it so a row that still
  carries one is dropped on read rather than ridden back by `_extra`.
  The steps that upgraded pre-release shapes were
  deleted — a document with no step for its version keeps that version,
  records an incomplete chain, and is refused rather than stamped as
  current.
- **`format` — whether this build may WRITE at all**
  (`branding.LIBRARY_FORMAT`, **2**). A library stamped ahead of this
  build opens read-only and points at the updater. It is the general
  answer to an old build meeting a new library, which is why per-field
  compatibility shims are not written.

**A FRESH document is BORN at `SCHEMA_VERSION`; it does not start low
and climb.** There is no step below 4, so anything created unstamped
reads as legacy 1, stops in a gap, records an incomplete chain, and is
then held at 1 by every subsequent save — it cannot climb out, and it
cannot adopt a peer's stamp either. So every creation door stamps at
creation, deriving the number from `SCHEMA_VERSION` and
`branding.LIBRARY_FORMAT` rather than writing a literal. The doors are
`DatabaseConnector`'s absent-sibling seed, which stamps by going through
`save()`, and `prefs.write_fresh_index`, which the other two both call —
`prefs.seed_test_folder` for the Test Library, and
`prefs.seed_starter_index` for `panel.load()`'s seed from
`res/def/library.json`. **The shipped starter itself carries no
`version` key on purpose**: a literal there would be a second source of
truth that goes stale at the next bump, so the stamp belongs to the door
and one writer applies it. `tests/test_fresh_library.py` pins both.

A PEER's document is migrated before it is merged (`_migrate_peer` —
shape only). **Absence is not a delete**: `set()` unions by id, so a
delete is said out loud through `forget()`.

---

## 6. Dialogs — a convention, not an Engine

A **Dialog** is a modal form (save, edit, preferences, about). Dialogs
are *not* an Engine — they have no runtime pipeline, they're just forms —
but they share one house style, so that style is a **base class**, not
copied per dialog.

- **AssetDialog** — the shared base: a `QFormLayout` with right-aligned
  labels + fields right, native 5px margins, content-hugging fixed size,
  OK/Cancel. Helpers `add_line` / `add_combo` / `add_row` / `finish`. A
  new dialog is a few `add_*` calls, identical by construction.
  `dialogs/base_dialog.py`.
- **Section-owned** — a Section provides its own dialog through the
  Section API's `edit_dialog()` hook, like it owns its menu. Material →
  **Edit Info Dialog**; Code → its editor. File/Node can get
  one the same way when they need it.

| Dialog | Section | In code |
|---|---|---|
| **Edit Info Dialog** | Materials | `edit_material_info` / `details_dialog` |
| **Code Dialog** | Code | `dialogs/code_dialog.py` ✓ AssetDialog |
| **Save Dialog** | Materials / Cop | `dialogs/save_dialog.py` ✓ AssetDialog |
| **Gradient / Category Dialog** | Colors | `dialogs/gradient_dialog.py` ✓ AssetDialog |
| **Preferences** | — (app-wide) | `dialogs/prefs_dialog.py` ✓ AssetDialog (live-apply: no OK/Cancel, 12px recorded margin) |
| **Icon Dialog** | any tile | `dialogs/icon_dialog.py` ✓ AssetDialog (non-modal) |
| **User Picker** | — (app-wide) | `dialogs/user_dialog.py` — raised after the first paint, only when the library has users and this machine is none of them |
| **About** | — | a TAB inside `dialogs/prefs_dialog.py`, shared with Debug — there is no separate About dialog |

*Adoption is complete* (R51, 2026-08-21) — every dialog rides AssetDialog,
and `test_headless_dialogs` pins it: a new QDialog subclass in `dialogs/`
either rides the base or records its reason in a `HOUSE_STRAY` attribute.

---

## Drag & Drop Engine (core/dragengine.py + panel/dragdrop_widgets.py + core/lop_assign.py)

**`core/lop_assign.py`** is the USD half of a LOP viewport drop, split
out of the panel 2026-07-27: what is already bound under a prim,
rebinding it, naming an assign after the geometry it drives, and
removing a material nothing references any more. No Qt, no panel — it
reports reasons rather than showing dialogs, so it is testable
headlessly (`tests/test_lop_assign.py`). The panel keeps the menu,
because choosing the prim is UI.

One SELF-MANAGED gesture for every section — no native QDrag, no drop
hooks. The widgets run press-move-release on the live event loop; the
engine owns everything spatial and temporal: throttled per-move picking
(`locateSceneGraphPrim` / `queryNodeAtPixel`), the hover highlight with
restore-on-end, release-target resolution (`viewport_release_target`),
container placement (`first_materiallibrary(connected_to=)`,
`find_assignmaterial`), Houdini's stock LOP helpers (`stock_lop()`), and
`keep_editor_focus` — a viewport release never moves the user's editors.
Sections' release verbs bridge to the import machinery; the panel keeps
the shared plumbing. The one native drag left is the texture file drag.
Law: a drop lands where it is dropped; nothing exists before release;
SOP and LOP worlds never cross-reference; empty viewport space is a
miss (red X); a menu is its own feedback (no icon).

## Storage format

Materials are Houdini-native node archives: `.mat` (via
`saveItemsToFile`) + `.interface` (Python from `asCode()`) + a JSON
index. Recoverable with vanilla Houdini if the plugin dies, but not
portable outside Houdini (not `.mtlx`/`.usda`).

**The `.interface` file is READ, never executed.** `asCode()` emits a
literal `createNode("<type>", ...)` call, so the first such type is the
saved builder - recovered by regex, which is what drives capability
routing and USD/renderer labelling on every material already in the
library with no re-save.

Executing it is what the builder sidecar replaced. `asCode()` output is
Python whose only documented contract is that it RUNS, so importing a
material used to run whatever was in a file chosen by an id read
verbatim out of `library.json`. The sidecar records the one thing the
executed file uniquely carried - the container's own parameter
interface and values - in a form that is parsed. Measured on a real
548-asset library: with sidecars present, every importable asset
reproduces byte-identically without executing a line.

### Where version files live — settled 2026-08-08, before Versions is built

    mat/versions/<asset id>/<writer>-<n>.mat
    mat/versions/<asset id>/<writer>-<n>.interface
    mat/versions/<asset id>/<writer>-<n>.png

A directory per asset id, and a file trio per version named for its
writer and an increasing number. Settled ahead of the build so that
Clean Library's classifier can be written against a shape that is
known rather than guessed: it whitelists only recognised stems, so
anything it does not recognise is skipped and logged, never swept.
Without a decided name, the first Clean Library run after Versions
ships would have read every version file as an orphan.

`<writer>` is the artist's own **Library User** — the `library_user`
preference — never a harvested machine or account name.

`library_user` is ONE identity: the name versions are signed with and
the key everything per-user is filed under. The retired `version_author`
is ADOPTED on load, so existing `<name>-<n>` stems still match their
writer. What keeps two writers off one filename is not the name — it is
stepping past a stem already on disk before writing.

### `policy.json` — a per-library write policy, on disk only

One key today, `allow_overwrite`, default **true**. When false,
`update_asset_content` refuses to replace an existing asset's files, and
the Save dialog stops offering Overwrite. It is checked at the LIBRARY
layer, not beside one caller, because a UI-level check is a suggestion.

Two things about it that are easy to get wrong:

- **It is NOT a DatabaseConnector file.** No merge, no `.bak-*` tier, no
  schema version — `core/library_policy.py` reads and writes it
  directly. It is a policy, not a database.
- **Preferences has a control for it** (`_cbx_allow_overwrite`, set
  through `prefs_dialog.set_allow_overwrite`), and the value still
  travels with the library on disk rather than with the machine - so
  two machines pointed at one library agree about it. ROADMAP plans
  renaming it to `Versions` with the opposite polarity and a
  migration.

### Housekeeping semantics (settled 2026-07-31)

Behaviour the hardening campaign changed, stated here because these are
contracts other code and the docs lean on:

- **Clean Library never deletes.** Missing-file rows are reported and
  kept; unclaimed files move to a machine-local quarantine
  (`config_root()/history/<library>/quarantine/<date>/`), named in the
  summary, expiring permanently after 30 days - the window IS the
  guardrail. Dead scratches sweep the same way, age-gated an hour.
- **Favourites are per-user IN THE LIBRARY** (`favourites.json`,
  `<uid>|<key>` — 2026-08-13): every section's star goes through the
  one favourites door, so the same user sees the same stars on every
  machine and two users of one library each see their own. The record's
  `favorite` field is DEAD — schema 6 strips it — and
  `material_favorites` in settings.json is a migration source only,
  read and retired by `locations.migrate_asset_favourites`. A star
  toggle writes the store, never a database.
- **Snapshots**: one per file per half hour of active saving, plus a
  daily gzipped history entry outside the synced tree; identical
  content never spends a slot; a healthy file may replace a garbage
  `.bak-first`.
- **Shared metadata merges field-wise** (name/categories/tags/
  description/license/about/icon/node_color): different fields from two
  sessions both survive; same-field keeps the active editor's value and
  records the collision.
- **Every `DatabaseConnector.save()` leaves one log record** naming its
  outcome; the library path rides as a digest, never raw.

### What a library directory may contain

The complete list. Anything else is either a failed write or not
library data, and `tools/library-audit.py` reports it (`--strict` exits
non-zero, so it can gate).

| entry | what it is |
|---|---|
| `library.json` `cops.json` `code.json` `gradients.json` | the four databases, all four through `DatabaseConnector` since 2026-08-09 — same shape, rows under `assets` keyed by `id`. Enumerated ONCE in `database.SECTION_DATABASES` (filename, panel label, section noun, in panel order); `database.DATABASES` and Repair derive from it, and `tools/library-audit.py` keeps a deliberate copy because it must run where Houdini will not start |
| `users.json` | **who uses this library** — a `uuid4` UID per person with a `name` beside it. Everything a user owns is tagged with the UID, so a rename relinks one label and moves nothing. The name is an alias for the UID, never the key. A library with no users mints its first from a colour-name pool; a library that HAS users asks a new machine which of them it is, rather than silently minting a second identity for one person |
| `notes.json` `icons.json` `locations.json` `favourites.json` `prefs.json` | the keyed side tables (per-asset comment pages; chosen tile icons; the File section's registered locations — per-user since ROADMAP line 22 stage C, `<uid>|<path>`, each user's own sidebar; every section's starred rows, `<uid>|<path-or-asset-id>`; the library's shared settings — one record per preference key, everyone's answer, ROADMAP line 22). Not DatabaseConnector documents, but written here and snapshotted here like the rest. A location record is `{registered, name, color, show_all, recursive}` keyed by path — `registered` is a FIELD, so the sidebar list is derived rather than kept beside it, and a location carrying no decoration is still visible. Path-shaped keys are stored PORTABLE (2026-08-06): `$AMAZE/...` under the install tree, `~/...` under home, absolute only past both — `hostos.storage_path_key` converts at the store boundary, every legacy spelling is absorbed on load (first in wins, logged), and the locations API answers canonical absolutes so scans and sidebars never see the variable form |
| `policy.json` | per-library write policy |
| `<file>.json.bak-1/-2/-3/-first` | **the restore tier** — written by `snapshot_before_write`, read by Repair Library, recovered by `restore.put_back`. Every file above that is snapshotted has one, not only the four databases |
| `<file>.json.bak-before-restore-<stamp>` | the undo copy each restore mints, bounded at `restore.KEEP_UNDO_COPIES`; the copy Repair's own undo sentence points at |
| `<file>.json.unreadable` | a file that would not parse, preserved instead of overwritten |
| `.amaze_gradient_seed_v1` `.amaze_code_starter_v1` | seed markers: "curated content was offered here once" |
| `mat/<id>.mat` `mat/<id>.interface` | material payloads |
| `mat/<id>.builder.json` | builder sidecar: the container's own parameter interface and values, as DATA |
| `mat/<id>.stamp.json` | recovery stamp: the asset's whole record, write-only, read solely by a rebuild after `library.json` is lost |
| `mat/versions/<id>/<n>.*` + `versions.json` | the version store: each version's archived payload (the same kinds as the base, thumbnail included), and the ledger naming them and the active one. The BASE files are always the active version's - losing this folder costs history, never the material. Deleting the asset takes the folder with it: `asset_directories()` names it and `remove_asset` sweeps it, because once the id leaves every list nothing can decide the folder is safe to take |
| `img/<id>.png` | tile renders |
| `matX/<package>/…` | MaterialX packages and their textures |

**The `.bak-*` files are not clutter.** They are how a damaged library
gets back, every shipping library has them, and a library without them
has no way home from a bad write. A cleanup that removes them removes
the recovery, which is the opposite of tidy.

**Nothing temporary belongs here.** A surviving `.writing`,
`.capturing`, `.lock` or `.tmp` is always ours and always means a save
died partway — reported separately from a merely unknown file, because
an unknown file might be the user's and a leftover scratch never is.

## 7. The Renderer terms

- **Renderer** — a material's engine label: `Karma`, `Redshift`,
  `Octane`, `COP`. Drives the Tile subtitle and the Renderer filter.
  `Mantra` was one until 2026-08-14, when it was dropped: SideFX is
  retiring the renderer, and 1.0 had not shipped, so nothing needed
  carrying. A `materialbuilder` or `principledshader::2.0` now matches
  no renderer and is refused at save rather than labelled. Online imports are plain Karma materials (their origin lives
  in the About/License credit, not the renderer tag).
- **Karma-family** — Karma plus the legacy stored labels MaterialX and
  MtlX, treated identically for routing, thumbnails and capability, and
  normalized to "Karma" everywhere via `material.normalized_renderer()`.
  One predicate: `material.is_karma_renderer()`.
- **USD-builder** — a material that can live in a LOP/Solaris context
  (`rs_usd_material_builder`, `octane_solaris_material_builder`, and all
  Karma-family). MAT-only otherwise.

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
panel/panel.py            The Panel (shell, widgets, shared handlers,
                          shared release plumbing)
panel/sections.py         The Sections (node-types) + registry + the
                          per-section GRID_MENU tables + every verb a
                          DROP rule names (release bodies, click verbs,
                          creation rules - line 24, 2026-08-13)
panel/grid.py             The GRID area - the one right-click menu
                          builder over those tables
panel/sidebar.py          The SIDEBAR area - what a row means and what
                          may be dropped on it (the drag-hover cluster)
panel/empty_state.py      EMPTY STATE ENGINE - which blank an empty
                          grid is showing, and its words
panel/dragdrop_widgets.py Drag-and-drop into the network editor
core/thumbnails.py        THUMBNAIL ENGINE (cache, budget, loaders)
core/conversion.py        CONVERSION ENGINE (file -> QImage, verified)
core/keyed_store.py       KEYED STORE ENGINE (guarded JSON side-tables)
render/nodes.py           MATERIAL ENGINE (build_karma_material) + save/import
core/debug.py             DEBUG ENGINE
core/library.py           Library Model (Materials) + base for Cop/Code
core/material.py          Material record + is_karma_renderer()
core/category.py          Categories Model + Sidebar Proxy
core/multifilterproxy_model.py   Filter Proxy
core/matx_translate.py    Adapter: online .mtlx -> clean VOP
render/material_converter.py     Adapter: Redshift -> Karma
core/matx_sources.py      Online source adapters (GPUOpen/PolyHaven/...)
core/matx_import.py       Online import orchestration + Values Adapter
core/matx_library.py      Online Browser model
core/{gradient,cop,code}_library.py   the other sections' models
core/file_library.py      File Section models (kinds, sweep, OS icons)
core/users.py             WHO uses this library - a uuid4 UID per
                          person with a name beside it. Everything a
                          user owns is tagged with the UID, so a rename
                          relinks the label and moves nothing
core/notes.py             the notes store (notes.json, per-asset pages)
core/library_prefs.py     the SHARED settings store (prefs.json) - the
                          library-wide half of ROADMAP line 22; read
                          and written by prefs/persistence.py alone
panel/notes_panel.py      the Comments pane (right splitter dock)
core/{texture,geo}_library.py   per-kind engines: image cache/proxy, geo knowledge
render/thumbs.py          Thumbnail SCENE building (shaderball, flipbook)
prefs/prefs.py            Prefs - what a setting IS (the property pairs)
prefs/persistence.py      how it is STORED - save/load/merge/migrate,
                          mixed into Prefs, plus the portable paths
core/folders.py           FolderListModel (shared Folder-archetype base)
core/scene_captures.py       scene capture store + open-scene state
core/repair.py            REPAIR: what is wrong with this library and
                          what is safe to do - Clean Library's opposite
                          number, and the only module that opens a
                          recovery stamp
core/updater.py           is a newer Amaze released, and can this one
                          become it - asked only on request, never at
                          launch (shelf tool + the About tab button)
core/versions.py          the version store - the base files are always
                          the ACTIVE version's, each version also has an
                          archived copy, and versions.json is the ledger
core/quarantine.py        where a library-internal removal puts what it
                          takes: machine-local, dated, expiring. Pure
                          stdlib, because the Houdini-free restore tool
                          calls it too
helpers/restore.py        the only code that READS the .bak copies and
                          the only code that puts one back - one
                          implementation behind Repair and the
                          Houdini-free tools/restore.py
core/gallery_import.py    Houdini .gal gallery entries -> library assets
core/matx_icon.py         the PhysicallyBased icon, for value-only
                          online sources that ship no texture to render
core/bsdf_reader.py       reads the `tensor_file` container the measured
                          EPFL RGL BSDFs ship in
preview/                  THE PREVIEW ENGINE (below) - the scene a
                          material thumbnail is rendered in. Callers
                          use `amaze.preview`, never its insides
preview/shaderball_scene.py  the ball, the plane and their materials
preview/thumbnail_scene.py   the room around them: lights, camera,
                          output - Redshift, Octane
preview/karma_scene.py    Karma's, which is a USD stage: built once,
                          many materials rendered into it
helpers/hostos.py         OS-INTEGRATION ENGINE (all platform branches)
helpers/hostver.py        HOST-CAPABILITY ENGINE - every "does this
                          environment behave differently here?" question
helpers/                  theme, ui widgets, vex syntax, generic helpers
utils/rc_calls.py         the entry points Houdini itself calls (shelf
                          tools, OPmenu) - finds the open panel by its
                          pane-tab label, historical names included
branding.py               the app's DISPLAY name and tagline, once
dialogs/                  save / preferences / about / code / gradient dialogs
dialogs/user_dialog.py    WHICH user this machine is, asked once and
                          only when the library has people in it and
                          this machine is none of them

tests/test_support.py     fixture_panel() - the ONLY way a test builds a
                          panel: own settings, library, caches, network
                          blocked, own registered file location
tests/assets/library/     the fixture library (a copy per test)
tests/assets/files/       the fixture File-section location, GENERATED by
                          make_file_fixtures.py - one tiny file per KIND
tests/test_no_live_data.py  the gate: no test may reach the machine's own
                          files. Source ban + runtime path check.
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
