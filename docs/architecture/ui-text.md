# Amaze UI text — every word shown in the app

**The single source of truth for user-facing copy.** Every label, menu
entry, button, tab and title the user sees is listed here, **in the order
it appears in the UI**, with the dividers the UI has. To change UI text,
edit the wording, order, or dividers here first, then update the matching
code — the app and this doc must stay in sync.

**Conventions**
- Each `- text` line is one exact string shown in the UI.
- **Order matches the UI top-to-bottom** — reorder lines here to reorder
  the menu.
- `- ---- divider ----` marks a separator line in the UI. Move / add /
  delete these to change the dividers.
- `(hidden)` = exists in code but not shown (see *Hidden & legacy* at the
  end). `(conditional)` = shown only in some states. `(⚑ verify)` = I
  wasn't fully sure — check and prune.
- **Bold Caps** names refer to [`overview.md`](overview.md).

---

## Section Tab Strip

Tabs, left → right *(singular since 2026-07-31; stored keys are
`material` / `gradient` / `cop` / `code` / `file` and never renamed —
they are what enabled_sections and per-section state remember)*:

- Material
- Color
- Node
- Code
- File  *(the 2026-07-31 merge of Images, Geometry and HIP: one folder
  browser, every file shown, per-KIND behaviour — images convert,
  geometry renders, scenes capture from the viewport, everything else
  gets its OS icon and Copy Path)*

---

**The ONLINE strip replaces this one** while the online world is
showing (2026-08-01): one tab per source — GPUOpen, PolyHaven,
PhysicallyBased, RGL — with no File tab, and `enabled_sections` does
not apply, because these are not sections. The amber Online button is
the only signal that you are there; the Material tab used to relabel
itself "Online", which is now meaningless because this strip is not on
screen at all.

## Toolbar

- **List-mode columns**, left to right: *(thumbnail)* · **Name** ·
  **Type** · **Category** · **Favorite** · **Version** · **Comments** ·
  **Tags** · **License**. In the File section **Open** takes Version's
  place — Version is materials-only, Open is File-only, so the two are
  never in one row. Favorite, Open and Comments show a TICK for yes and
  nothing for no; Version shows the active version's name, or `none`.
  Tags and License exist only for sections that have them; the others
  get neither label nor divider.
- **One ink for the table** (2026-08-01): every column paints in the
  same light grey `#d8d6d4`, EXCEPT Category, which takes the colour
  the user gave that category. A table is read down its columns, and
  six colours across a row competes with the one colour that means
  something.
- **A row is as wide as its content** (2026-08-01), and the section
  scrolls sideways when the panel is narrower — the header travelling
  with it. No column is squeezed and none is ever dropped: the row used
  to be defined as the width of the panel, so widening the Comments
  pane silently deleted columns from the right.
- **Filter Box** label: `Search`  *(was `Filter` until 2026-08-01 —
  the box searches, so the label says so)*
- **Filter Box** placeholder: NONE — the box sits empty in every tab
  and in the online browser (2026-08-01). The label and the magnifier
  already name the control; the per-section texts were noise beside
  them. The `Section.search_hint` machinery stays, every hint set to
  the empty string, and a test fails if any section writes one again.
  The `:tag` prefix is taught by the box's tooltip instead.
- Menu buttons (icons, no text): **View** (3D box), **Renderer** (eye —
  it is a filter: what you can see).
  View tooltip: `Import a gallery file, or generate a material.`
  *(rewritten 2026-08-02: it still described the pre-reduction menu —
  "the library or the online browser, grid or list, and the category
  sidebar" — none of which lives there since 3a2c7c2.)*
  Renderer tooltip: `Filter materials by renderer.`
- Action button (icon, no text, no menu triangle): **Preferences**
  (gear) — opens the Preferences dialog directly. FAR RIGHT of the
  row since 2026-08-01, with Capture immediately to its left on the
  File tab.
- **Categories** chip (leading the row, in front of the gear) — shows
  and hides the category sidebar. Promoted out of the View menu
  2026-08-01: a control that toggles state is a button, and having
  both is how a toggle ends up disagreeing with the thing it toggles.
  Tooltip: `Show the category sidebar.`
- **Online** chip (immediately left of Comments) — enters and leaves
  the online world. AMBER while you are in it; the colour is the whole
  signal, the same treatment as the favourites star.
  Tooltip: `Browse materials online.`
- **Comments** chip (between Online and the grid toggle, every tab) —
  toggles the Comments pane, docked as the splitter's rightmost pane.
  The icon family's blue in every state.
  Tooltip: `Comments - a page of text and to-dos for the selected tile`.
- Favourites and Comments are DISABLED, at 50% opacity, while the
  online world is showing: an online record carries no favourite
  state, and a comment is written against a library asset.
- **Capture** button (camera icon, File tab only) — captures the open
  scene's viewport as its thumbnail; hidden on every other tab. The old Library menu
  dissolved into the dialog's Library tab; "Render All Thumbnails" was
  removed outright (select-all + Rerender Thumbnail covers it).

### View menu

Two entries, both ONE-SHOT actions. Everything that was a state
became the control that carries it (2026-08-01): a menu row beside its
own button is a second way to one thing, which is how a toggle ends up
disagreeing with what it toggles.

- Gallery Import (.gal)  *(pick a .gal file; its material presets become library materials)*
- Generate Material  *(builds one material in the current LOP material library or /mat, from the measured CC0 datasets — its node comment records which measurement it came from)*

*(Gone from this menu, and where each went: Show Categories and the
four online sources → toolbar button / online tab strip; Grid View and
List View → the grid-list chip that already existed beside them;
Material Library → the Online button, whose off state IS the local
library. No submenu either: two entries do not earn one.)*


## Versions dialog


SHELL is the design, the CONTROLS are Houdini's.

- Fixed 512 x 435. Header band `#22232b`, 132 tall; body `#2b2c35`.
- Header: the layered glyph at 33,36 (60 x 60, live vector, stroke
  `#ef8878`), then name/category 23px `#93b9e7`, **Versions** 32px
  bold `#dddcdd`, and the renderer 23px `#93b9e7`.
- Body column inset 35 both sides - 442 wide. The version dropdown,
  the `Name` label and the rename field sit in it, then cancel and
  Apply, 202 x 42 with a 38 gap, 35 below the field.
- The dropdown, the field and the buttons are STANDARD Houdini

  where a control goes, not what it should look like.

  `DesignedDialog.d()` converts them to the logical pixels Qt sizes
  with. Not `theme.ui_px`, which answers a different question.

### Renderer menu

- All
- Karma
- Mantra
- Redshift
- Octane

---

## Comments pane

- Header (`#22232b`): the note icon (150% size, vertically centred —
  the materiallibrary-node look), then the selection's
  `section/category` (the category in ITS OWN colour and bold when it
  carries one; File shows `file/location-label`) / **name** (bold) /
  `type`, then **+** ("Add a to-do at the cursor"), also centred.
- EVERY section takes notes, Color included (every gradient carries
  a uid from load - backfilled once - or from birth on save, like
  every section's assets carry their id).
- Nothing selected = the SAME window as a GHOST: the lines read
  literally `section/category` / `Object name` / `type`, the editor
  is disabled and the **+** is dead, tinted the page colour
  (`#2b2c34`). Never a different layout.
- The 12px under the header is DOCUMENT margin, not chrome: text
  starts 12px down unscrolled, and scrolled text passes through the
  zone up to the header border.
- The page (`#2b2c34`) is ONE FLOWING DOCUMENT: text above, between
  and below the to-dos, in the order written. A to-do is
  PAGE-COLOURED - no background of its own - set apart by 10px of
  padding above and below, with a Feather circle / check-circle
  painted at its left. **+** inserts one at the cursor; Enter inside
  stacks another; Enter on an empty one returns to text; clicking the
  circle checks it (label strikes through). One emptied of text is
  dropped at save.
- The DELETION path: Backspace at a to-do's start (or on an empty
  one) unwraps it back to text — the label survives as words the next
  Backspace eats. A Backspace/Delete that JOINS two lines across a
  to-do's edge keeps the frame: Qt hands a merged block the following
  block's state (probed), so both merge keys are intercepted and the
  survivor re-stamped.
- Body placeholder: `Write a comment...` (followed the 2026-08-01
  Notes -> Comments rename; this line had kept the old noun while the
  app moved on)
- ONE ICON FILE for the notes SURFACES: the toolbar chip and the
  pane header render `ui/icon_notes.svg` (update it there and both
  follow), and their yellow presentations re-tint to the theme's own
  star token — FIXED: the star-colour preference left Preferences
  with the unified badge family (2026-08-01, the tile star renders
  as drawn, so the preference had nothing left to colour). The TILE
  badge is separate family art (below) and takes no colour at all.
- Toolbar chip: between the eye (Renderer) and the grid toggle;
  unchecked wears the icon family's base tint, checked the star
  yellow.
- Tile badges — ONE DRAWN FAMILY (art redesigned 2026-08-01): each
  glyph on its own rounded square of BLACK at 75%, so it reads on any
  thumbnail, rendered AS DRAWN (never re-tinted — the palette lives
  in the ART, so a redesign is an asset swap, and this one was) at
  ONE size rule (the star's proportional rule) from `ui/badge_*.svg`.
  The DISC is what makes them a family; the glyphs keep their own
  colours — a green check, an amber star, white for the other two.
  The corners mean: top-left open scene (`badge_open`, check),
  top-right favourite (`badge_star`, star), lower-left versions
  (`badge_versions`, three dots), lower-right comment
  (`badge_comment`).
- The versions badge is the one BUTTON on a tile, and so the only one
  with two states: `badge_versions_hover` is the same mark on a
  lighter disc (50%), shown while the cursor is on it, with the
  tooltip `Click to select version`. Clicking opens the Versions
  dialog. The other three are indicators and never answer the
  pointer. (The grid's viewport had to be told to track the mouse —
  otherwise a viewport reports moves only while a button is held.)

---

## Grid right-click menus (per section)

### Material

*(The menu law, set 2026-07-31 on the contextual-menu base: Info, the
section's work, a divider, the tile's presentation — Update Preview,
Customize — Favorite, and Delete last of all. The same order in every
grid menu.)*

*(The selection law, same day: every menu opens for any selection. An
entry that acts on ONE item — Info, Apply, Apply as, Copy Color,
Edit, **File's** Load, Show Location, Capture Preview — greys out
while several items are selected; it never vanishes, so the menu
keeps its shape. An entry that acts on the whole selection — Update
Preview, Customize, Favorite, Delete, the geometry Import, **Node's**
Load — stays live and acts on everything, and Delete's confirmation
counts what it is about to remove. A test drives the Material menu
both ways and fails if Info stops greying out or Customize stops
working.)*

*(**The law covers NO selection too, since 2026-08-03.** Right-clicking
empty grid space opens the same menu with everything that needs a
selection greyed — the menu keeps its shape whether nothing, one thing
or many are selected. There were three answers to this before: Material
opened a full menu with every entry but Info LIVE over no selection at
all, Color, Node and File opened nothing, and Code opened New File.
**New File and the Online browser's Refresh are the only two entries in
the app that act on nothing**, so they are the only two that stay live
on an empty right-click. An entry conditional on the KIND of the
selected rows — File's Import, Load, Capture Preview and Update
Preview, and Material's Convert to Karma — is still absent rather than
greyed when no such row is selected: it does not exist for those rows,
which is a different statement from "not right now".)*

*(**Load is the right word in both places, and it behaves differently
in each — that is not a bug** (settled 2026-08-02): you load a scene,
and you load the content of nodes into the scene. Importing is not the
right language for nodes. Only one scene can be open, so File's Load
greys on a multi-selection; any number of networks can be built, so
Node's Load stays live and loads them all. Written down because the
law used to name Load once, unqualified, and the next reader would
have "fixed" the working half.)*

- Info  *(was "Edit Info")*
- Copy To →  *(submenu; was "Import" 2026-07-31 — it copies the saved
  material into the scene, and Import now belongs to the File section)*
  - /mat  *(was `MAT` until 2026-08-01 — the entries name the
    destination the way Houdini writes it)*
  - /stage  *(was `LOP`, then `/Solaris` until 2026-08-08 — the path,
    not the marketing name)*
- Convert to Karma  (conditional — a Redshift material is selected; the summary dialog lists what each conversion skipped or approximated)
- ---- divider ----
- Update Preview  *(was "Rerender Thumbnail", then "Render Thumbnail")*
- Customize  *(was "Edit Icon...")*
- Favorite
- Delete

> **Category left the grid menus 2026-07-31.** Dragging a tile onto a
> sidebar category does the same job with less ceremony, so the submenu
> was removed from every section rather than grown into the others. A
> test now fails if it comes back.

### File *(key: file — the menu is KIND-aware: the selection's kinds
decide the primary action; the shared tail is the same for every row.
Renamed across the board 2026-07-31: one word for one idea — Import
brings a file into the scene, Load opens a scene, Show Location
reveals it, Capture Preview photographs the viewport)*

- Import  *(image and geometry rows; was "Load" for images. An image
  imports onto one node's texture slot, so it greys out on a
  multi-selection; geometry imports the whole selection at once)*
- Load  *(scene rows; was "Open Scene")*
- Copy Path  *(every row, now above the divider with the other work;
  copies every selected path, one per line, written per Preferences ▸
  Write Paths As — the ONLY primary action for unknown files)*
- ---- divider ----
- Show Location  *(was "Open Location")*
- Capture Preview  *(scene rows, beside Show Location; was "Capture
  Thumbnail". Enabled only for the scene the viewport is CURRENTLY
  showing — the capture photographs the viewport, so capturing while a
  different scene is open would file the picture under the wrong name,
  silently and plausibly. This line used to say "the scene Amaze itself
  opened", a stricter clause the shelf tool never shared and that was
  dropped from the code well before this doc followed: a scene opened
  through File ▸ Open, a recent-files entry or a crash recovery is
  capturable. The toolbar Capture button's disabled tooltip carries the
  explanation — context menus have NO hover tooltips, by the 2026-08-01
  rule)*
- Update Preview  *(image and geometry rows only — a capture is
  hand-framed and an OS icon has nothing to render)*
- Customize
- Favorite

> Deliberately **no Delete** anywhere in File: these are the user's own
> files on disk, not entries Amaze owns (an os.remove here once deleted
> real production files).

### Color

- Apply  *(was "Apply Ramp" 2026-07-31; applies the gradient exactly
  as saved)*
- Apply as →  *(submenu, always shown — one entry per ramp
  interpolation: Constant, Linear, CatmullRom, MonotoneCubic, Bezier,
  BSpline, Hermite. Replaced the single conditional "Apply as Linear
  Ramp" 2026-07-31)*
- Copy Color →  *(submenu of swatches, each labelled with its hex code; copies the hex to the clipboard)*
- ---- divider ----
- Customize  *(new 2026-07-31 — Colors can carry a tile icon like every
  other section; with none, the swatch shows)*
- Favorite
- Delete

> **There is no curated-vs-user distinction here any more.** This list
> used to gate three of the entries on it — "Apply as Stepped Ramp
> *(curated)*", Linear "curated only", Delete "user only" — and the code
> gates none of them: every gradient is an ordinary user gradient, and
> the only condition left is whether a gradient's ramp bases are all
> Constant. A doc that promises a protection the code does not have is
> worse than one that omits it, because it is read as a safety
> guarantee. Corrected 2026-07-30. **Even that last condition is gone
> since 2026-07-31**: "Apply as" offers every interpolation, always.

> **Info left this menu 2026-08-01** and its Edit Gradient Info dialog
> went with it. The dialog's free-text Notes moved to the Comments pane —
> a one-time sweep on load appends any gradient's old note text to its
> Comments page, so no words are lost. Renaming lives in Customize's Name
> field now; a test fails if Info creeps back.

### Node *(key: cop)*

- Load  *(was "Import" until 2026-08-01 — the File section already
  says Load for "bring the saved thing into Houdini", and building a
  saved network is the same act. Import stayed behind in File, where
  it means a file coming INTO the scene)*
- ---- divider ----
- Update Preview
- Customize
- Favorite
- Delete

> **Info left this menu 2026-08-01**, one day after arriving — its
> read-only Node Info window and the archive-mining behind it were
> removed with it. A test fails if it creeps back.

### Code

- New File
- ---- divider ----
- Apply
- Edit
- ---- divider ----
- Customize
- Favorite
- Delete

> **View left the menu 2026-07-31.** Edit already shows the code, so
> two windows over one snippet was one too many; its read-only dialog
> went with it.

### Online Browser (the toolbar's Online button)

*(Its own world since 2026-08-01: the tab strip becomes the sources —
GPUOpen, PolyHaven, PhysicallyBased, RGL — with no File tab, and
leaving returns you to the section you left from. It was a view mode
over the Materials widgets before that, which is why the entry point
used to be a menu inside Materials.)*

- Import to Materials  *(downloads and saves it as a library material, thumbnail per preference; `(N)` suffix for a multi-selection; greys with nothing selected — it used to vanish)*
- Import to Scene  *(builds it in the current LOP material library, or /mat — a scene node like any hand-built material, nothing written to the library; same `(N)` suffix and same greying)*
- Refresh  *(acts on nothing selected, so it is always live)*

Double-click imports **to the scene** — the primary action in every
section is "put it where I am working", and for an online material that
is the scene, not the library.

---

## Sidebar right-click menus (per section)

### Material / Node / Code (categories)

- Add Category
- Rename
- Remove
- ---- divider ----
- Set Color
- Clear Color

### File (folders)

- Add Location
- Remove  *(forgets everything about the location: its label, colour,
  recursion and Show All Files setting, its favorites, its comments and
  its custom icons, plus its cached image/geometry thumbnails.
  Re-adding the folder gives you a clean slate. Changed 2026-08-03 —
  favorites, comments and icons used to be kept and come back with the
  path.)*
- Locate  *(favorites, the custom name and the recursion
  flag all follow the move)*
- Label →  *(submenu, replaced Rename 2026-07-31 — a location is not
  renamed, it is given a custom display name)*
  - Add  *(opens a dialog titled `Add Label`; the label replaces the
    path in the sidebar. Without one, the path itself shows, written
    per Write Paths As)*
  - Remove  *(clears the label so the path shows again; greyed while
    the location has no label)*
- ---- divider ----
- Show Subfolders  *(checkable, PER LOCATION — disabled on "All")*
- Show All Files  *(checkable, new 2026-08-01: PER LOCATION, it
  overrides the global "All show unknown files" preference for that
  location alone — one location can show its unknown files while the
  rest hide theirs, and the sidebar count follows. On the "All" row
  the checkbox IS the global preference, edited from here too)*
- ---- divider ----
- Set Color  *(new 2026-07-31 — a location carries a colour like a
  category does: the sidebar bar and the tile band. Stored in
  preferences, since a location is a pointer this machine holds)*
- Clear Color

### Color (gradient categories)

*(The base menu since 2026-07-31 — Rename and the colours joined, and
Remove lost the quoted name it alone carried.)*

- Add Category
- Rename  *(conditional — a real category, not "All")*
- Remove  *(conditional — a real category, not "All")*
- ---- divider ----
- Set Color
- Clear Color

---

## Dialogs

### Preferences

Title: `Amaze Preferences`. Five tabs; rows top to bottom per tab:

*(Groups are separated by bare 1px dividers - NO section title text,
matching Houdini's own parameter panes. All on/off rows use pill
TOGGLE SWITCHES, not tick checkboxes.)*

- **Library** tab
  - Library Path  *(read-only field + `...` browse)*
  - Clean Up Library
  - Reload Library
  - Open Library Folder
  - ---- divider ----
  - Material Versions  *(was "Shared Library / Allow Overwrite" until
    2026-08-01 — the old protection story ended when Versions shipped:
    a save-over archives a version first and destroys nothing, so the
    switch now says what it does. ON: saving over an existing material
    offers Save Version. OFF: saving always adds a new material. Still
    stored in the library itself (policy.json, key unchanged:
    `allow_overwrite` — keys are identifiers, never names), because a
    switch governing a SHARED thing travels with the thing. The
    save-over prompt's buttons: Save Version / Save New / Cancel, or
    Save New / Cancel when off)*
  - Version Author  *(text field, added 2026-08-08 — the name version
    FILES are signed with, `<name>-<n>.mat`, so two machines can never
    write the same file. The box always shows the real name: a fresh
    machine's colour name is minted the moment the dialog opens, and
    the field is free to overwrite; never the OS user or machine
    name)*
  - ---- divider ----
  - Cache Path  *(read-only field + `...` browse)*
  - Delete Local Cache
- **Render** tab
  - RenderSize
  - Samples (Redshift)
  - Samples (Karma)
  - RAM Cache (MB)
  - Geometry Shading
  - Geometry Background
  - Render Thumbs on Import
  - ---- divider ----
  - Conversion Threads  *(texture conversions at once)*
  - ---- divider ----
  - Download Resolution
  - Parallel Downloads
- **Show/Hide** tab  *(renderer switches, divider, section switches)*
  - Karma
  - Mantra
  - Redshift
  - Octane
  - ---- divider ----
  - Material
  - Color
  - Node
  - Code
  - File
- **Look** tab
  - Show Counts on Categories
  - Hide Empty Categories
  - All show unknown files  *(was "Show Unknown Files" until
    2026-08-01 — the File section's OS-icon rows. Tooltip: "Show
    files Amaze has no preview for, using their system icon. Each
    location can override this in its own right-click menu.")*
  - Write Paths As  *($HOME default / $JOB / $HIP / Absolute —
    Copy Path and the File location labels)*
  - Tile Icon Line
  - Scroll Speed (%)
- **About** tab
  - *(branding text: name, tagline, description, credits, license,
    online material sources with their licences, thanks — links open
    externally)*
  - ---- divider ----
  - Debug Mode
  - Open Log  *(opens the log file, or reveals it in the file browser
    when the OS has no application for .jsonl)*
  - Save Log...  *(copies the log to a chosen folder, named for this
    machine and Houdini version — two machines' logs can sit side by
    side; the copy contains file paths and asset names, and the
    tooltip says so)*
  - Clear Log

#### Test Library *(Preferences ▸ About, under Debug Mode, 2026-08-08)*

- Toggle: `Test Library`
  Tooltip: `Work against a throwaway library instead of the real
  one. Point it at any folder: Amaze uses the lib folder inside it,
  making it if it is missing. Your real Library Path and registered
  folders are left exactly as they are and come back when you switch
  this off.`
- Registered File locations stay ISOLATED in both directions: the test
  library gets its own (empty until you add some) and never seeds from
  the settings copy, and it never writes that copy back — the copy is
  the seed a later repair of the REAL library reads.
- Field: `Test Folder` *(read-only + browse, like the other paths)*
  Tooltip: `The folder holding the test lib folder.`
- While the toggle is ON the `Library Path` row is DISABLED and shows
  where the library actually points — the same treatment the
  accent-colour rows get under a theme. Its browse button writes the
  real field, so leaving it live is the one combination that could
  lose a library.
- The CACHE does not move with the library (2026-08-08). Thumbnails
  are keyed by file path on disk and say nothing about which library
  is open, so moving them regenerated thousands on every switch and
  protected nothing. The `Cache Path` rows stay live under Test
  Library, and `Delete Local Cache` remains the one deliberate wipe.
- Failure: `That folder could not be prepared:` + the reason, when the
  chosen folder cannot be seeded.
- No success dialog — the reloaded grid is the announcement.

### Save Dialog (Material / Node — "Save to Amaze")

- Title: `Save to Amaze`
- Name  *(Cop only; a Material is named after its node)*
- Category
- Tags

### Edit Info Dialog (Material)

- Title: `Material Info`
- Name
- Type  *(read-only)*
- Category
- Tags
- Favorite
- Update Info  *(the button that commits the edits above — it sits
  BETWEEN Favorite and Date, so the read-only facts below it are
  outside what it writes. Recorded 2026-08-01: it had never been in
  this catalog at all)*
- Date  *(read-only)*
- ID  *(read-only)*
- License  *(the license the material is released under; auto-filled for online imports)*
- About  *(multi-line credit/homage text — source, author, link; auto-filled for online imports, editable)*

### Versions Dialog (Material — opened from the tile's version badge)

- Title: `Versions of "<name>"`
- *(a dropdown of the versions, a field to rename the selected one)*
- Cancel · Apply

Browses, switches and names — never creates; a version is created
automatically on save. The badge shows only when a material has two
or more versions.

### Code Dialog

- Title: `Save to Amaze`  (⚑ verify)
- Name
- Language
- Category
- Tags
- Description

### Tile Icon Dialog (Edit Icon... on any tile)

- Title: `Tile Icon`
- *(the Name field — the one rename path every section shares:
  renames the asset on OK. NO label beside it, so the field spans the
  column's full width; its placeholder reads `Name`. Greys out on a
  multi-selection per the selection law; absent entirely in the File
  section, because a file's name is the file on disk)*
- Search field, placeholder `Search <N> icons`
- *(the icon grid, the colour presets)*
- Custom Color...  *(opens the Houdini colour picker; the dialog is
  non-modal so the picker can be reached)*
- Icon Color  *(dropdown: `Dark` / `Light`)*
- Remove  *(tooltip: "Show this tile's own thumbnail again")*

### Gradient Dialog ("Save Gradient to Amaze")

- Title: `Save Gradient to Amaze`
- Name
- Category

### Category Dialog (add/rename a category or a File location)

- Title: `Add Category` / `Add Gradient Category` / `Rename Category`
  / `Add Label`  *(the File sidebar's Label ▸ Add — replaced
  `Rename Location` 2026-07-31)*
- Name

## Viewport drop menus (Drag & Drop Engine)

Dragging a material tile onto a scene viewport (the Drag & Drop
Engine's self-managed release builds these; prim names come from the
pick):

### LOP viewport
- Swap <material>  *(first section; one entry per material bound on the
  dropped-on prim, plus "Swap All Materials" when several — swapping
  also removes the old material from the library if nothing references
  it anymore)*
- Set as Material on <prim>  *(one entry per ancestor: mesh, ../geo (kind), ...)*

### OBJ viewport
No menu — the material is assigned to the object under the cursor
directly.

---

## Node right-click (Houdini network editor — OPmenu)

On a node, right-clicked — ONE label for one function, whatever the
node type (unified 2026-07-31; was Save Code / Save Gradient / Save
Network / Save Selection to Amaze):

- Save to Amaze  *(materials; nodes with a code parm; nodes with a
  colour ramp; a selection inside a Copernicus network — the entry
  routes by node type, the label never changes)*

---

## Tile subtitle labels (the greyed line under a name)

The **Renderer** shown on each **Tile**:

- Redshift · Redshift:Standard · Redshift:PBR · Redshift:Toon ·
  Redshift:OSL  *(and other shader-type suffixes)*
- USD Redshift · USD Redshift:PBR
- Karma · USD Karma
- Octane · USD Octane
- COP
- Gradient  *(Color section)*
- File-format extension  *(File — e.g. `EXR`, `OBJ`, `Hiplc`; scene
  extensions read as a word, not an acronym)*

---

## Empty states (the grid with nothing in it)

Shape: **what is missing / what this section is FOR and the gesture / a
button that does it.** Three blanks are shared and written once; only
`nothing-yet` differs per section, and `%s` marks an interpolated
value. A button appears ONLY where the panel can act with nothing
selected — Material, Color and Node are saved from the network editor,
so their verb would only open `No material selected`.

### Shared — every section

- **Nothing matches "%s"**  *(the user's own search, elided at 24
  characters so a pasted paragraph cannot run away)*
  - No saved %s has that in its name, tags or category.  *(%s is the
    section's plural noun — materials, palettes, node assets, snippets,
    files)*
  - Button: **Clear Search**
- **Nothing in "%s"**  *(the selected category; blank for All)*
  - Your other categories still have %s in them.
  - Button: **Show All**
- **Can't read that folder**  *(File section only)*
  - %s did not answer. It may be a drive that is not mounted, or a
    share that is offline. Nothing has been removed from your library.
  - *(no button — nothing the panel can do about a folder that is not
    there)*

### Nothing yet — per section

- **Material** · *No materials saved yet*
  - Right-click a material in the network editor and choose Save to
    Amaze. It is kept here, ready to drag back into any scene.
- **Color** · *No palettes saved yet*
  - Right-click a node with a color ramp and choose Save to Amaze.
    Apply it to any ramp later, in any scene.
- **Node** · *No node assets saved yet*
  - Select nodes in a network, right-click and choose Save to Amaze.
    The whole network is kept, ready to build back in.
- **Code** · *No snippets yet*
  - Right-click a wrangle and choose Save to Amaze to keep its code —
    or start one here and paste into it.
  - Button: **New File**
- **File** · *No folders added yet*
  - Add a folder of images, models or scenes and they show up here,
    ready to drag onto any parameter. Nothing is copied or moved.
  - Button: **Add Folder**

---

## Houdini shelf (`toolbar/Amaze.shelf`)

Tool labels on the **Amaze** shelf:

- Amaze  *(opens the panel)*
- Capture  *(viewport thumbnail capture, for the File section's
  scene rows)*
- Repair  *(Repair Library — puts back a damaged database from its
  `.bak` snapshots and reattaches files that lost their entry)*

---

## Delete confirmations

Every section's Delete states what goes, in the user's words, and its
button says **Delete** (never "OK"), with Cancel as the default:

- **Material** — "Delete this material? Its saved files and thumbnails
  go for good. Materials already used in a scene are not affected." /
  "Delete N materials? …"
- **Node** — the same shape, "node asset(s)", "Networks already built
  in a scene are not affected."
- **Code** — "Delete this snippet? It goes for good. Code already
  applied to a node is not affected." / "Delete N snippets? …"
  *(and NO "Update Preview": a snippet's preview is painted from its
  own text under a content-addressed key, so it repaints itself on an
  edit and a re-render would produce the identical image — the same
  reason Color has none. Offered for one commit on 2026-08-03 and
  removed the same day after a live test read it as doing nothing.)*
- **Color** — "Delete "<name>"? The gradient goes for good. Ramps
  already applied to a node are not affected." / "Delete N gradients?
  They go for good. …" *(counts since 2026-07-31 — the menu now acts
  on the whole selection like every other section)*
- **File** — none: File has no Delete at all.

---

## The interaction matrix (drag release and double-click)

One behaviour, two aiming methods: a DRAG hands the payload to what
is under the cursor; a DOUBLE-CLICK aims at the selected node, else a
network that can hold the payload. Declared per section as a
`DropRule` in `panel/sections.py` (doors: on_node / outside / resolve
/ on_space, walked in that order by the gesture engine); this table
is the register of what those declarations say.

| Payload | On a node | On empty network space | Elsewhere |
| --- | --- | --- | --- |
| Material | into a material library node under the release | a copy created where materials can live, at the release point | miss |
| Node network | resolves its own destination (fill rule) | built where the context allows, at the release point | miss |
| Gradient | a node with a ramp takes it | a MaterialX ramp carrier is created where supported | miss |
| Code snippet | a node with a snippet parameter takes it | a wrangle is created where supported | miss |
| Image file | first file parameter takes the spelled path | a `mtlximage` carrying the path, where supported | miss |
| Geometry file | first file parameter takes the spelled path | imports, landing at the release point | miss |
| Scene (hip) file | first file parameter takes the spelled path | miss | outside the panel: loads the scene |
| Unknown file | first file parameter takes the spelled path | miss | miss |

A node's refusal is final — it never falls back into another door.
The sidebar outranks everything: a release over a category
recategorises the selection. A DRAG miss shows the red indicator and
the name tag flies home, one status line, never a dialog; a
DOUBLE-CLICK miss says the one sentence below.

### The audit matrix (verified 2026-08-08, code + live session + host source)

Three doors per section — drag release, double-click, menu verb — and
three promises per door, each checked against Houdini's own
behaviour (`$HH/scripts/scene/lop_dragdrop.py`, `nodegraph.py`, the
HOM manual):

**Where it lands.** Every landing door places at the gated release
position, centred under the pointer (the manual's own
`cursorPosition` pattern); a double-click aims at the visible
selection, else a network that can hold the payload; menu verbs act
on the grid selection. The one deliberate placement exception: a
material released on a material library goes inside it.

**What moves.** Nothing else — measured live per door: a code
double-click into a populated network and a Copy To into a populated
/mat both left every neighbour exactly where it was. Houdini's own
material drop re-arranges (`moveToGoodPosition`) and dives the
editor (`setCurrent(True, True)`); Amaze diverges deliberately on
both, and restores the artist's selection where the host leaves the
newborn selected. These divergences are the app's view-never-jumps
law, not omissions.

**What the undo stack gets.** One entry per gesture: every
scene-touching door and menu verb wraps in a single undo group;
conversion scratch and thumbnail scaffolds run under the undo
disabler; verbs that never touch scene nodes (Capture, New File,
scene load) correctly add nothing.

**Refusals.** Houdini saying no (a locked network) is absorbed
identically at all three doors: the drag shows the fly-back plus
Houdini's own sentence in the status bar; the double-click the same
sentence, same bar; a genuine defect still raises where it can be
seen. Matches the host's information, delivered without a dialog.

**Menu-verb contracts** (the third door, swept 2026-08-08): Load,
Copy To and the online Import to Scene carry the same
selection/current/view preservation the drag and click dispatchers
give every gesture; the File menu's Import always did.

---

## Common messages & confirmations

- `This content can not be loaded into this context.` — the ONE
  double-click refusal, every section (2026-08-07, the interaction
  matrix): a single selected target that cannot take the payload, a
  multi-selection, or a network with no carrier for it. The DRAG door
  never dialogs — a miss shows the red indicator and the tag flies
  home, with one status-bar line.
- `This library was saved by a newer Amaze. To keep it safe, this
  machine opens it read-only - update Amaze, then everything works
  as normal.` — the library FORMAT stamp (2026-08-08): shown once
  per session when a database carries a format number ahead of this
  build's. Reads work, every save refuses. The updater's offer joins
  this dialog when the in-Houdini updater ships.
- `Your library's list could not be read.` — the unreadable-index
  dialog (2026-08-08), replacing the raw traceback at panel open.
  Buttons: `Repair` (default) / `Open Without Library` (also the
  close action). Body promises: newest saved copy first, else a
  rebuild from what each asset itself remembers; category names
  survive, order and colours may not; the broken file is kept
  beside itself. Failure follow-ups both end on `The Repair tool on
  the Amaze shelf can tell you more.` No success dialog — the
  recovered grid is the announcement, plus one status-bar line.

- `Could not save the library - <why>` — shown when a library write
  is refused by the disk (2026-08-10). **`<why>` is read from the
  errno**, never guessed: the folder cannot be reached / the folder is
  read-only / the disk is full / another program is holding the file,
  and for an errno nobody has measured it reports what the disk said
  and claims no cause. It replaces one sentence that named *held by
  another program* for every failure — measured, that cause cannot
  occur on macOS at all, so a dropped synced folder sent the reader
  hunting a program that was not there. The body no longer promises
  the change *will be written with the next save*, because nothing
  retries: it says the change is still in Amaze, that saving anything
  else writes it too, and that it is NOT on disk yet and will not
  survive closing Houdini.
- `Your comment could not be saved.` / `The icon you picked could not
  be saved.` — each followed by what is unchanged, then
  `This happened because <why>` from the same errno reading. Only
  these two speak: a comment and an icon stay on screen looking
  saved, so nothing else would say otherwise. **A registered folder
  and a File favourite say NOTHING** when their write is refused —
  they are drawn from what was stored, so the folder never appears and
  the star never lights, and an alert would announce what the user just
  watched (see `denied_alert`, **Keyed Store Engine**).
- `Your tile icon could not be saved.` — the icon PICTURE, as opposed
  to the choice above. Also ends on `This happened because …` now: the
  two copies of this sentence both told the reader to check the folder
  was *reachable and not read-only*, which guesses two causes at once
  and points at the file when a read-only file does not stop the write
  at all.

- `Some materials could not be saved:` followed by one
  `"<name>": the save did not complete` line per material — the
  multi-save dialog. The per-material line is new (2026-08-08):
  a refused save used to be counted as a success, so a batch could
  report nothing while silently dropping a material. Two of the
  three refusal causes have already shown their own dialog naming
  the reason ($OCIO unset, the node not being a material builder),
  so this line only says WHICH material out of the batch never
  made it.

*(The rest not listed yet — the `hou.ui.displayMessage` /
`displayConfirmation` strings. Ask for the messages and every one
gets listed with its trigger.)*

---

## Cleanup history

**2026-07-21 Designer clean-up.** Removed 9 dead actions from
`ui/amaze.ui` (verified: the file still loads, every element the code
uses is present):

- **7 orphans** never wired into any menu or referenced in code (upstream
  egMatLib leftovers): Import from Files, Import from Folder, Import From
  Files (Mantra), Check Integrity, Force Update Views, Update All
  Materials, `_deleteMaterial`.
- **2 hidden legacy** that had been shown-then-hidden: **Import from
  MatLib V1** (the v1-library importer, removed with v1 support) and
  **Show Detail View** (toggled the old docked Details Panel, now the
  **Edit Info Dialog**). Their menu refs and the code that hid them were
  removed too.

The `.ui` is the Qt Designer source, maintained externally (never edited
from code); anything removed from it is removed *deliberately*, both the
definition and every reference, and load-tested before shipping.

## Hover tooltips — every one the app shows

**Extracted from the shipped code 2026-08-02** (47 of them), so this
list and the app cannot disagree without one of them being wrong. The
voice is settled and deliberate: short, one sentence where one will do,
teaching only what is not obvious from the label. A first draft that
obeyed every written rule still read as engineer-speak, and the fix was
not vocabulary but THOROUGHNESS — "Show only materials made for one
renderer. All shows everything. Which renderers appear here is chosen
in Preferences ▸ Show/Hide." became "Filter materials by renderer."
Match that register before adding one.

Rules that apply to all of them:

- Every multi-line tooltip goes through `ui_helpers.tooltip_text()`,
  which caps the box at **800 REAL screen pixels** and wraps. Qt renders
  a plain-text tooltip as ONE line however long, and Qt's widths are
  logical pixels which a Retina screen doubles — a source-scan test
  fails any bare multi-line `setToolTip`.
- **Menus stay bare.** Grid and sidebar right-click entries carry no
  tooltips: a menu row is already a sentence, and a hover over a hover
  is noise.
- No tooltip may name project history ("the merge", "since 1.0") — the
  reader has none.

### Toolbar

| control | tooltip |
|---|---|
| Categories chip | Show the category sidebar. |
| Online chip | Browse materials online. |
| Comments chip | Comments - a page of text and to-dos for the selected tile |
| Renderer menu (eye) | Filter materials by renderer. |
| View menu (box) | Import a gallery file, or generate a material. |
| Preferences (gear) | Open preferences. |
| Favourites star | Show favorites. |
| Grid/List toggle | Switch between the thumbnail grid and the detail list. |
| Size slider (grid) | Tile size. |
| Size slider (list) | Tile size - grid only. A list row is one text line, so it does not scale. |
| Search box | Search for objects, a leading colon searches tags instead: :metal finds everything tagged metal. |
| Capture (File tab) | Captures a preview from "scene view" pane |

*The slider's text is set per view mode by `_sync_slider_for_mode`, not
at construction — it is the one tooltip with two states.*

### Preferences ▸ Library

| row | tooltip |
|---|---|
| Library Path | The folder the library lives in. |
| Clean Up Library | Tidy up: missing files are reported, leftovers are set aside for 30 days. Everything still showing in the panel stays. |
| Reload Library | Read the library from disk again. |
| Open Library Folder | Open the library folder. |
| Material Versions | Whether saving over an existing material creates a new VERSION of it. Stored in the library itself, not in your preferences - so it applies to everyone who opens this library, on every machine. ON: saving over an existing material offers Save Version - the old version is kept, and the tile's badge switches between them any time. OFF: saving always adds a separate new material, and existing ones are never touched. |
| Cache Path | Where the preview copies live on this machine. |
| Delete Local Cache | Throw away the preview copies. They are remade as you browse, the library is untouched. |

### Preferences ▸ Render

| row | tooltip |
|---|---|
| RenderSize | Thumbnail resolution in pixels. Bigger is sharper and slower. |
| Samples (Redshift) | Render quality for Redshift thumbnails. |
| Samples (Karma) | Render quality for Karma thumbnails, 9 is Karma's default. |
| RAM Cache (MB) | Memory for keeping thumbnails ready. More scrolls smoother. |
| Geometry Shading | How geometry thumbnails are drawn: shaded, wireframe or both. |
| Geometry Background | The backdrop for geometry thumbnails. |
| Render Thumbs on Import | Render thumbnails as soon as materials are imported. Off = render later with Update Preview. |
| Conversion Threads | How many texture conversions (EXR/HDR to thumbnail) run at once. |
| Download Resolution | Texture resolution to download. A floor, not a hard match: the next highest available is used, or the highest below. |
| Parallel Downloads | Preview downloads at once. These wait on network latency rather than bandwidth, so more is markedly faster. |

### Preferences ▸ Show/Hide

| row | tooltip |
|---|---|
| renderer switches | Which renderers Amaze offers. Hide the ones you don't use. |
| section switches | Which sections the panel shows. A hidden section keeps everything, the tab just goes away. |

### Preferences ▸ Look

| row | tooltip |
|---|---|
| Show Counts on Categories | Show how many things each category holds. |
| Hide Empty Categories | Hide categories with nothing in them, they come back when something lands there. |
| Show Unknown Files | Show files Amaze has no preview for, using their system icon. Each location can override this in its own right-click menu. |
| Write Paths As | How Amaze writes paths - Copy Path and the File section's location labels. A variable applies when the path lives under it; otherwise the path stays absolute. |
| Tile Icon Line | Line weight of the tile icons, thin or regular. |
| Scroll Speed (%) | How fast the grid scrolls, 100 is normal. |

### Preferences ▸ About

| row | tooltip |
|---|---|
| Debug Mode | Write a structured session log for diagnosing problems. Off by default. |
| Open Log | Open the debug log. |
| Save Log... | Copy the debug log to a folder you choose, named for this machine and Houdini version - so two machines' logs can sit side by side when a problem happens on only one of them.<br><br>The copy contains your file paths, asset and material names. |
| Clear Log | Empty the log and start fresh. |

*Save Log is the one deliberately multi-paragraph tooltip — it warns
what the copy contains, and that warning is the last line by the
teach-before-you-warn rule.*

### Dialogs

| control | tooltip |
|---|---|
| Tile Icon ▸ name field | Rename this tile. The name is what the grid, the sidebar count and every search look at. |
| Tile Icon ▸ Custom Color... | Pick any color, with Houdini's color picker. |
| Tile Icon ▸ Remove | Show this tile's own thumbnail again |
| Versions ▸ picker and name field | Pick the active version in the list, rename it in the field. Versions are made automatically when you save. |
| Save dialog ▸ name field (node) | Name it, pick a category, and add tags to find it again later. |
| Save dialog ▸ name field (code) | Name it, pick a category, and add tags to find it again later. |
| Comments pane ▸ **+** | Add a to-do at the cursor |

### Still without one

The empty cells are the to-write list, and they are deliberate rather
than forgotten: the section tabs, the list-mode column headers, the
tile badges (open / favourite / versions / note), and the online tab
strip. A tile badge is the interesting case — it is painted by the
delegate, not a widget, so a hover there needs the view's own
`ToolTipRole` or hit-testing, which is a build rather than a string.

## Status of this doc

Order + dividers extracted from the code 2026-07-21. `(⚑ verify)` = not
fully certain it's live. Add anything missing and I'll find it.

Re-audited against the code 2026-07-31: added the missing Edit Icon...
entries (five grid menus), Set Color... / Clear Color (category
sidebars), Locate Folder... (folder sidebars), and the shelf section.

Re-written for the File merge later the same day: the tab strip went
singular, Images/Geometry/HIP folded into one kind-aware File section
(closing the recorded HIP Edit Icon gap), the folder sidebar gained
Rename / per-location Include Subfolders / sweep-on-remove, and the
Look tab gained Show Unknown Files and Write Paths As.

Selection-law batch, 2026-07-31: the law paragraph at the head of the
grid menus, the File renames (Import / Load / Show Location / Capture
Preview) and reorder, the File sidebar's Label ▸ submenu, and the
Colors delete that counts.

Same day, the follow-up renames: Material's Import ▸ became Copy To ▸,
Color's Apply Ramp became plain Apply, and Code's View left (Edit
already shows the code).

2026-08-01: Info left the Color and Node menus — Material alone keeps
it. Color's Edit Gradient Info dialog went with it and its free-text
Notes migrated into the Comments pane (a one-time sweep on load); Node's
read-only Info window and its archive mining were removed whole.

Later the same day: the toolbar label became Search and the box lost
every placeholder; Copy To ▸'s entries became /mat and /Solaris; and
the Tile Icon dialog gained the Name field — the one rename path every
section shares (File excepted: a file's name is the file on disk).

Also 2026-08-01: the File sidebar gained the per-location Show All
Files checkbox, and the Look tab's Show Unknown Files became "All show
unknown files" — the default the locations follow.
