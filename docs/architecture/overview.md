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
| **Section Tab Strip** | The Material/Color/Node/Code/File tab bar (singular since the 2026-07-31 merge; stored keys keep their historical names). | `ui_helpers.SectionTabBar` |
| **Sidebar** | Left list: categories (asset sections) or folders (file sections). Whether a dragged tile may be DROPPED on a row is the context's answer — `Section.takes_category_drops` and `accepts_category_drop` — not a list of section keys held by the panel (`CATEGORY_SECTIONS`, retired 2026-08-04). | the `cat_list` widget, `panel/sidebar.py` |
| **Grid** | The main thumbnail area. GRID scales 64-512 with a magnet at 128; LIST is a table fixed at its smallest size (the slider greys out) whose row is as wide as its COLUMNS need, scrolling sideways rather than squeezing or dropping any. LIST mode is a real `QTableView` over a real `QAbstractTableModel` (the migration completed 2026-08-04); the painted header strip, `ListColumnHeader`, `ListColumns` and the delegate's list-painting branch are all retired. **The grid selection speaks in ROWS** (2026-08-06): a SelectRows selection answers one index per CELL - ten per row, hidden thumb column included - so every reader collapses to one index per row at column 0 through `grid_columns.selected_rows`, and the current, double-click and drag indexes are normalised to column 0 the same way (`live_current_index`, the panel's double-click entry, the drag press). The table carries the same context-menu and double-click wiring as the list view. The column ORDER lives once, in `core/grid_columns.COLUMNS`, which every grid model answers per column. WIDTHS are fixed defaults the user can DRAG (`panel.COLUMN_DEFAULT_WIDTH`, derived from the real library), with the last column taking the slack — nothing is measured at runtime. Tile badges are grid-only: at list size a badge is 12px and its art rasterises to a dark smudge, so those four facts are columns there instead. | the `thumblist` and `thumbtable` widgets, `panel/grid.py`, `panel/delegates.py` |
| **Tile** | One item in the Grid (thumbnail + name + subtitle). Painted by the **Tile Delegate**. | `AssetItemDelegate` |
| **Tile Badges** | ONE drawn family (2026-08-01): each glyph on its own dark backdrop (`ui/badge_*.svg` — the palette lives in the ART, never in code), rendered AS DRAWN through one engine (`_badge_pixmap`) at one size rule (`_badge_side`). Corners: top-left open scene, top-right favourite, lower-left versions (click opens the Versions dialog), lower-right comment. | `delegates.py` `_paint_*_badge` |
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

> **Display names and KEYS differ, deliberately.** The labels went
> singular (2026-07-31) and Cop is labelled **Node** without renaming
> its key — the keys are load-bearing in saved preferences and in
> every asset record. Read a key as an identifier, never as a name.
> The pre-merge keys `texture`/`geometry`/`hip` are retired but still
> present in older machines' saved preferences; nothing may strip
> them (see the Show/Hide rebuild in prefs_dialog.py).

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

  > **Scene rows break one Folder rule deliberately.** The other kinds
  > RENDER a missing thumbnail from the file; a scene file cannot be
  > re-rendered without reconstructing the whole scene, which fails
  > whenever a dependency has moved. Their thumbnails are CAPTURED
  > from the viewport instead, so a row without a capture simply shows
  > a placeholder and opening a folder never starts a capture. The
  > store is also not mtime-invalidated: a hand-framed capture must
  > survive re-saving the scene.
- **Gradient Archetype** (`GradientSection`) — the palette library.
  Color. Fully read-write: gradients are added (including from a
  dropped ramp node), renamed, recategorised and deleted, and so are
  their categories.

  > **It was called "the read-only palette library" here until
  > 2026-07-30**, which was true only while the curated palettes were
  > the whole content. They are ordinary user gradients now — the same
  > staleness that had ui-text.md gating three Colors menu entries on a
  > curated-vs-user distinction the code no longer makes.
  >
  > **It used to be the odd one out and no longer is (2026-08-09).**
  > `gradients.json` was the one database not going through
  > `DatabaseConnector`, so every guard the others inherit had been
  > given to it by hand — and three were still missing as late as
  > 2026-07-30. It goes through the connector now: same schema chain,
  > same restore tier, same unreadable latch, same adopt-on-write,
  > same merge. The FILE adopted the one shape rather than the
  > connector learning a second — rows under `assets`, identity in
  > `id` — so all four databases work the same way.
  >
  > Two consequences worth knowing, both the connector's and both
  > shared with the other three: a concurrent edit MERGES rather than
  > being refused, and **absence is not a delete** — a row the caller
  > does not mention is kept, so a delete is said out loud through
  > `forget()`.

### The Section API (what every Section implements)

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
| `delete_prompt(count, name)` | what deleting costs, in this section's words — the wording lives in [`ui-text.md`](ui-text.md) |
| `sidebar_key(index)` | what a **Sidebar** row is keyed by — a category name in three sections, a registered folder PATH in File |
| `sidebar_colour(name)` / `set_sidebar_colour(name, colour)` | read and write that row's colour, in whichever store this context keeps it |
| `double_click(index)` | a **Tile** is double-clicked (the *primary action*) |
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
is a third thing again. Wording in [`ui-text.md`](ui-text.md).


> USD idea again — an opinion attached to a value rather than inferred
> from where it sits). Wherever several values travel together they go
> as a named tuple, never as a bare tuple read by position:
> `sections.AssetStack` (the four models), `sections.CommentSubject`
> (the six the Comments pane points at) and `sections.FileLocation` (a
> File row's registered location). Three more made the same point and
> are gone with the machinery they named — `ui_helpers.ListColumns`,
> `delegates.ListRow` and `ListRowStyle` retired with the QTableView
> migration, which is the better ending: the rule held right up to the
> code being deleted. Each replaced positional arguments or positional
> reads that several authors had to keep in step by hand —
> and in every case nothing would have RAISED when they drifted, the
> wrong value would simply have been used.

**The Grid Menu** (2026-08-03) is the same idea for right-click. Every
context declares `GRID_MENU` — a tuple of `MenuEntry` rows, one per
entry — and `panel/grid.py` is the ONLY code that turns one into a
QMenu. A row carries its label (from [`ui-text.md`](ui-text.md)), the
NAME of the Section method that performs it, the name of the fact that
decides whether it EXISTS (`shown`), what it needs to be LIVE
(`needs`), and optionally the name of a method building a submenu's
children. Names rather than callables, so the six tables read side by
side. The last four rows are `GRID_MENU_TAIL` — Update Preview,
Customize, Favorite, Delete — shared by every context and gated on
facts it already declares (`menu_offers_preview`, `deletes_rows`), so
adding a section adds no copy of them. Before this there were six
handlers in `panel.py`, 406 lines, giving three different answers to
"what does an empty selection show" and each carrying its own guard
against the same dispatch bug: a dismissed menu returns None and so
does an entry that was never built, so `action == action_convert_karma`
matched `None == None`. Dispatch is a dict keyed by QAction now, and
that whole family is unwritable.

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

### 4b. The **Conversion Engine**

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

> **AN ENGINE VERIFIES ITS OWN OUTPUT; AN ADAPTER IS NEVER TRUSTED.**
> The **Material Engine** has had this since it was built
> (`surface_terminal_wired`); the conversion path never did, so an exit
> code was read as an answer to a correctness question and 178 HDR
> tiles went black with nothing in the log. A uniform result is a
> SUSPICION, not a verdict — the engine tries the next adapter and
> keeps it, and delivers it if nothing does better, because a black
> texture is also a real picture.

### 4c. The **Keyed Store Engine**

One guarded JSON side-table, keyed by a stable identity, for every
store that keeps per-key choices beside the thing they belong to.

- **File:** `core/keyed_store.py` · **Entry point:**
  `open_store(spec, preferences) -> Store`
- **Adapter API:** a store is DATA — `register(filename, payload,
  keyspace, label, noun, …)` declares it; the adapter attaches its
  normaliser with `bind()`. **Registration is how a store comes into
  existence**, so `stores()` is the ONE enumeration Repair, the restore
  picker and `tools/library-audit.py` read.
- **Adapters:** the **Comments store** (`core/notes.py` → `notes.json`),
  the **Tile Icon store** (`core/tile_icons.py` → `icons.json`), and
  the **Location record** and **File favourites**
  (`core/locations.py` → `locations.json`, `favourites.json`).
  All four are files IN THE LIBRARY. The last two were views onto
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
  lifecycle, and the one answer that carries a REASON.

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

**The owner announces, the engine fans out.** A folder that moved is
one call — `relocate(prefs, old, new)` — naming the prefix and no
store; a location that is gone is `retire_prefix(prefs, path)`. The
caller never enumerates the stores, because a list held by a caller is
a list someone can write short, and both callers that held one already
had been. Whether a store SURVIVES a location removal is
`survives_forget` on its spec — a product decision said once (comments
and tile icons stay; the location record dies with the pointer).

> **`<file>.json.bak-first` now arrives on the FIRST write.**
> `snapshot_before_write` copies what is already on disk and rightly
> declines when there is nothing there, so a store written exactly once
> had no trace of any kind and absent-but-known could not fire.
> `hostos.seed_restore_floor` mints the write-once floor from the file
> just created. No new kind of file — the same name, one write earlier.

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

### 4f. The **Debug Engine**

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

---

## 5. Models & storage

| Term | What it is | In code |
|---|---|---|
| **Library** | The on-disk folder holding an asset section's data: `library.json` (index) + `mat/` (node archives) + `img/` (thumbnails) + `matX/` (downloaded MaterialX). Path in `settings.json`. | — |
| **Library Model** | The Qt model over a **Library**'s JSON. Materials/Cop/Code each have one (Cop/Code subclass it over their own JSON). | `core/library.py` → `MaterialLibrary`; `cop_library.py`; `code_library.py` |
| **Material** | One asset record (id, name, category, tags, favourite, renderer, tile icon, …). **One category per asset** — multi-category was removed 2026-07-27; tags are the many-to-many axis. | `core/material.py` |
| **Tile Icon** | A chosen Feather symbol on a colour, for assets with nothing to render. Stored on the asset (`icon`) for Asset sections, in `icons.json` keyed by path for Folder sections. Composed to `<id>_icon.png` BESIDE the render, never over it. | `core/tile_icons.py` |
| **Comment** | A page of text + to-dos per asset (the Comments pane, toggled from the toolbar). Renamed from Notes 2026-08-01 - the WORDS changed, every identifier did not: `NotesRole`, `notes.json`, `notes_panel.py` and the `show_notes` / `notes_panel_width` keys are contracts with data on disk and with other machines. Stored in `notes.json` beside the index, keyed `<section>:<id>` / `file:<path>`, wearing icons.json's guard set (unreadable latch, adopt-on-write, snapshot tier). Tiles with a note carry the lower-right badge via `NotesRole` (UserRole + 10, both model families). WHICH asset the pane points at is the context's own answer — `Section.comment_subject(index)`, one of the four area hooks — because only the context can map an index through its proxy and read its roles; the panel finds the live current index and delegates. `takes_comments` is the separate, selection-free half that the toolbar chip reads. EVERY section takes notes, Color included - gradients carry a full-uuid4 uid from load (one-pass backfill) or birth, keyed `gradient:<uid>`. | `core/notes.py`, `panel/notes_panel.py` |
| **Category Colour** | A colour on a category, painted under every tile in it and down its sidebar row. Stored beside the category names in the same JSON, so the grid reads it from the connector's shared data dict. | `core/category.py` → `Categories.set_color` |
| **Categories Model** | The Sidebar list for an Asset section. | `core/category.py` → `Categories` |
| **Sidebar Proxy** | Sorts categories and hides empty ones (renderer-aware). | `category.CategoriesSidebarProxy` |
| **Filter Proxy** | The Grid's search/renderer/favourite/tag filter (Asset sections). | `core/multifilterproxy_model.py` |
| **Asset Stack** | The four models an Asset section works through — Library Model, Filter Proxy, selection model, Categories Model — as `sections.AssetStack`, whose fields are `model` / `proxy` / `selection` / `categories`. A bare 4-tuple until 2026-08-03: it was unpacked in nine places and read by NUMBER in three more (`st[0]`, `st[3]`), which is where a reorder would have gone unnoticed. | `section.stack()` |
| **Folders Model / Files Model** | The Folder-archetype pair (registered dirs / files inside). Folders share ONE base — `core/folders.py` `FolderListModel` (counts, All row, add/remove/relocate); each section only names its prefs surface + extension predicate. | `core/folders.py`, `texture_library.py`, `geo_library.py`, `scene_captures.py` |
| **Online world** | A PARALLEL world, not a view mode over Materials (which is what it was until 2026-08-01). The toolbar's Online button enters it and turns amber — the colour is the whole signal — and the tab strip becomes the SOURCES in source order (GPUOpen, PolyHaven, PhysicallyBased, RGL) from `matx_sources.all_sources()`. No File tab, and `enabled_sections` does not apply, because these are not sections. ONE strip, two lists: `_build_section_tabs` already rebuilt on an `enabled_sections` change, so switching worlds reuses that path. A tab click picks a source. Leaving returns you to the section you left from. `_is_online()` is now just the mode — it used to be `online_mode AND current_section == "material"`. Favourites and Comments are disabled here: an online record has no favourite state, and a comment is written against a library asset. | `panel.py` `enter_online_world` / `leave_online_world`, `core/matx_sources.py` |

| **Filtering & sorting** | THREE proxies, one base: `core/grid_proxy.py`'s `GridProxyModel`, inherited by `MultiFilterProxyModel` (the asset sections and Online), `TextureFilterProxyModel` (File) and `GradientFilterProxyModel` (Color). They differ in what they FILTER ON; the base owns WHAT IS SHOWN AND IN WHAT ORDER. `setDynamicSortFilter(False)`, set for performance, turns off three things at once, and each came back as a caller remembering: the re-sort after a filter change (2026-08-01 — picking a category then going back to All came back unsorted), the re-sort after an INSERT (2026-08-03 — a newly saved asset landed at the bottom of 548), and the re-test of a row whose DATA changed (2026-08-03 — un-favouriting a tile with Favourites-only on left it in the grid, star off). The re-test is role-aware (`watched_roles`) and every pass is coalesced onto one per event-loop turn. | `core/grid_proxy.py`, `core/multifilterproxy_model.py` |
| **Scrolling** | Both axes go through one handler: per-PIXEL scroll mode and `dragdrop_widgets.wheelEvent`, which reads the dominant axis, converts a classic wheel's 120-unit notches, and applies the `scroll_speed` preference. Horizontal was on Qt's per-ITEM default until 2026-08-01 — one step is a whole row, which reads as wild acceleration — and it went unnoticed because nothing could scroll sideways until list rows grew wider than the panel. | `panel/dragdrop_widgets.py` |
| **Splitter panes** | THE construction (2026-08-01): sidebar \| grid \| comments, with exactly ONE flexible pane — the grid (stretch 1); both side panes hold (stretch 0), so every redistribution Qt performs lands on the grid. Each side pane OWNS its width: BOTH are `ui_helpers.HeldPane`, which asks for the remembered drag or the design width through `sizeHint`, and `_on_splitter_moved` records both into `sidebar_width` / `notes_panel_width`. Nothing on the panel computes a pane's width: measured 2026-08-03, the splitter has already honoured the hint before any post-show code runs, so the 50 lines that redistributed for the Comments pane were recomputing what was true. Never bookkeeping around Qt's relayout — that shipped once and lost. | `panel.py` `_build_splitter_and_sidebar`, `ui_helpers.HeldPane` |
| **Prefs** | Settings, one shared instance injected into every model. Stored where the OS keeps preferences (`~/Library/Preferences/Amaze` on macOS, `%APPDATA%/Amaze` on Windows, `$XDG_CONFIG_HOME/Amaze` on Linux) — never in the install. Split in two 2026-08-09: `prefs.py` answers what a setting IS (64 property pairs plus the location, favourite and section-filter accessors), and `prefs/persistence.py` carries it to and from disk — save, load, the field-wise merge between two panes of one session, the migration out of older installs, and the portable path encoding. `_Persistence` is mixed into `Prefs`, so every call site still says `prefs.save()` and the document's shape is untouched. | `prefs/prefs.py` → `Prefs`, from `settings.json` |
| **Database** | The JSON read/write layer, one connector per JSON filename. | `core/database.py` |

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
  one the same way ("they can get one the same way").

| Dialog | Section | In code |
|---|---|---|
| **Edit Info Dialog** | Materials | `edit_material_info` / `details_dialog` |
| **Code Dialog** | Code | `dialogs/code_dialog.py` (AssetDialog: pending) |
| **Save Dialog** | Materials / Cop | `dialogs/usd_dialog.py` (AssetDialog: pending) |
| **Gradient / Category Dialog** | Colors | `dialogs/gradient_dialog.py` ✓ AssetDialog |
| **Preferences** | — (app-wide) | `dialogs/prefs_dialog.py` (AssetDialog: pending) |
| **Icon Dialog** | any tile | `dialogs/icon_dialog.py` |
| **About** | — | a TAB inside `dialogs/prefs_dialog.py`, shared with Debug — there is no separate About dialog |

*Adoption is incremental* — GradientDialog/CategoryDialog use AssetDialog;
the others migrate one at a time (low-risk, not force-retrofitted).

---

## Drag & Drop Engine (core/dragengine.py + panel/dragdrop_widgets.py + core/lop_assign.py)

**`core/lop_assign.py`** is the USD half of a LOP viewport drop, split
out of the panel 2026-07-27: what is already bound under a prim,
rebinding it, naming an assign after the geometry it drives, and
removing a material nothing references any more. No Qt, no panel — it
reports reasons rather than showing dialogs, so it is testable
headlessly (`tests/test_lop_assign.py`). The panel keeps the menu,
because choosing the prim is UI.

One SELF-MANAGED gesture for every section (no native QDrag, no drop
hooks - both retired): the widgets run the press-move-release cycle on
the live event loop (a floating name tag follows the cursor), and the
engine owns everything spatial and temporal about it - throttled
per-move picking (`locateSceneGraphPrim` / `queryNodeAtPixel`),
selection-driven hover highlight with restore-on-end, release-target
resolution (`viewport_release_target`), the container/placement policy
(`first_materiallibrary(connected_to=)`, `find_assignmaterial`),
Houdini's stock LOP assignment helpers (`stock_lop()`), and the
editor-focus policy (`keep_editor_focus`: a viewport release never
moves the user's editors). The panel's release handlers bridge a
release to the import machinery and the LOP menu (swap-first). The
one native drag left is the texture file drag (real file mime).
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

`<writer>` is the artist's own `version_author` preference, never a
harvested machine or account name.

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
- **Favourites are per-user** (`material_favorites` in settings.json,
  asset ids). The record's `favorite` field is frozen history for older
  builds; this build neither reads nor writes it, and a toggle does not
  touch the library.
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
| `library.json` `cops.json` `code.json` `gradients.json` | the four databases, all four through `DatabaseConnector` since 2026-08-09 — same shape, rows under `assets` keyed by `id` |
| `notes.json` `icons.json` `locations.json` `favourites.json` | the four keyed side tables (per-asset comment pages; chosen tile icons; the File section's registered locations and its starred files). Not DatabaseConnector documents, but written here and snapshotted here like the rest. A location record is `{registered, name, color, show_all, recursive}` keyed by path — `registered` is a FIELD, so the sidebar list is derived rather than kept beside it, and a location carrying no decoration is still visible. Path-shaped keys are stored PORTABLE (2026-08-06): `$AMAZE/...` under the install tree, `~/...` under home, absolute only past both — `hostos.storage_path_key` converts at the store boundary, every legacy spelling is absorbed on load (first in wins, logged), and the locations API answers canonical absolutes so scans and sidebars never see the variable form |
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
  `Octane`, `Mantra`, `COP`. Drives the Tile subtitle and the Renderer
  filter. Online imports are plain Karma materials (their origin lives
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
panel/panel.py            The Panel (shell, widgets, shared handlers)
panel/sections.py         The Sections (node-types) + registry + the
                          per-section GRID_MENU tables
panel/grid.py             The GRID area - the one right-click menu
                          builder over those tables
panel/sidebar.py          The SIDEBAR area - what a row means and what
                          may be dropped on it (the drag-hover cluster)
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
core/notes.py             the notes store (notes.json, per-asset pages)
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
core/gallery_import.py    Houdini .gal gallery entries -> library assets
core/matx_icon.py         the PhysicallyBased icon, for value-only
                          online sources that ship no texture to render
core/bsdf_reader.py       reads the `tensor_file` container the measured
                          EPFL RGL BSDFs ship in
render/shaderball_scene.py   the shaderball scene a material preview
                          renders through
render/thumbnail_scene.py    the per-renderer thumbnail scene (Redshift,
                          Octane and the rest build theirs here)
helpers/hostos.py         OS-INTEGRATION ENGINE (all platform branches)
helpers/hostver.py        HOST-CAPABILITY ENGINE - every "does this
                          environment behave differently here?" question
helpers/                  theme, ui widgets, vex syntax, generic helpers
utils/rc_calls.py         the entry points Houdini itself calls (shelf
                          tools, OPmenu) - finds the open panel by its
                          pane-tab label, historical names included
branding.py               the app's DISPLAY name and tagline, once
dialogs/                  save / preferences / about / code / gradient dialogs

tests/test_support.py     fixture_panel() - the ONLY way a test builds a
                          panel: own settings, library, caches, network
                          blocked, own registered file location
tests/assets/library/     the fixture library (a copy per test)
tests/assets/files/       the fixture File-section location, GENERATED by
                          make_file_fixtures.py - one tiny file per KIND
tests/test_no_live_data.py  the gate: no test may reach the machine's own
                          files. Source ban + runtime path check.
```

> **A test never touches the machine's own data** (2026-08-02). Seven
> test classes used to construct the panel directly behind
> `ui_snapshot._protect_live_settings`, which disables `Prefs.save` and
> redirects the log — so the settings FILE was safe while the panel
> still opened the real library and, through it, the real File
> locations recorded in the user's own preferences. Those are personal
> photograph and texture archives, and `FileSection.activate()` scans
> every registered location and converts every image in it. Use
> `test_support.fixture_panel(testcase)`, or
> `fixture_panel(class_scope(cls))` for a class-scoped one; it asserts
> every path it would touch is inside the temp dir before it returns.

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
- To reword the app's copy: edit [`ui-text.md`](ui-text.md) — every
  user-facing string, grouped by where it appears.
