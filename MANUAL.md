# Amaze — Manual

**Browse it, save it, drag it.**

Amaze is an asset library that lives in a Houdini pane tab: materials,
colour palettes, node setups, code snippets and the files on your
disk, all in one place. It is built around one idea — whatever you
are looking at, you should be able to **drag it where you need it**.

Installation is in the [README](README.md). If you only read one
section here, read [Drag and drop](#drag-and-drop): that is where most
of the app lives.

- [First run](#first-run)
- [The panel at a glance](#the-panel-at-a-glance)
- [Material](#material)
- [Online materials](#online-materials)
- [Generate Material](#generate-material)
- [Color](#color)
- [Node](#node)
- [Code](#code)
- [File](#file)
- [Tile icons](#tile-icons)
- [Category colors](#category-colors)
- [Comments](#comments)
- [Drag and drop](#drag-and-drop)
- [Preferences](#preferences)
- [Housekeeping and troubleshooting](#housekeeping-and-troubleshooting)
- [Credits and licence](#credits-and-licence)

---

## First run {#m/first-run}

Add the pane tab: **New Pane Tab Type ▸ Misc ▸ Amaze**.

Add the shelf tab too: right-click the shelf dock ▸ **Shelves ▸
Amaze**. Houdini records that choice per machine and per Houdini
build, so redo it after an upgrade — the tools are all still there,
only the tab needs re-adding.

On first launch Amaze asks for a **library folder** — where your saved
assets live. Keep it *outside* the plugin folder, so updating Amaze
never touches your assets; a cloud-synced folder works well. You can
move it later in Preferences ▸ Library.

Inside that folder Amaze keeps a JSON index and one Houdini node
archive per asset (`.mat` + `.interface`). These are plain Houdini
files: **if Amaze ever dies, your assets still open in vanilla
Houdini.**

There is also an **Amaze shelf** carrying three tools: **Amaze** opens
the panel, **Capture** takes a preview of the open scene, and
**Repair** is the recovery tool described under Housekeeping — that one
is on the shelf rather than in the panel because it has to work when
the panel does not.

---

## The panel at a glance

The **section tabs** run along the top — Material, Color, Node, Code,
File. Each section remembers its own category, view mode
and scroll position. Sections you never use can be hidden entirely
(Preferences ▸ Show/Hide).

The **toolbar** sits top-right:

| | | |
|:--:|---|---|
| <img src="scripts/python/amaze/ui/icon_search.svg" width="20"> | **Filter** | Free-text search over names and tags in the current section. |
| <img src="scripts/python/amaze/ui/grid.svg" width="20"> <img src="scripts/python/amaze/ui/list.svg" width="20"> | **Grid / List** | Two views of the same assets. |
| <img src="scripts/python/amaze/ui/star_on.svg" width="20"> | **Favorites** | Show only favorited assets. |
| | **Size slider** | Thumbnail size, 16–200 px. Scales list rows too. |
| <img src="scripts/python/amaze/ui/icon_renderer.svg" width="20"> | **View** | Your library, the online sources, categories, grid/list. |
| <img src="scripts/python/amaze/ui/icon_view.svg" width="20"> | **Renderer** | Filter materials: All, Karma, Redshift, Octane. |
| <img src="scripts/python/amaze/ui/icon_library.svg" width="20"> | **Preferences** | Opens Preferences (five tabs). |

**List mode** is a spreadsheet, and its columns fit themselves to the
longest name currently on screen:

| | Name | Type | Category | Tags | License |
|:--:|---|---|---|---|---|
| *thumb* | Bronze_Worn | <span style="color:#4af2a1">Redshift</span> | <span style="color:#d8d6d4">Metal</span> | <span style="color:#e28248">worn, warm</span> | <span style="color:#5cc9f5">CC0 1.0</span> |

Tags and License appear only for sections that have them (Material,
Node). On a narrow panel the right-hand columns step aside rather than
squeezing the rest.

The **sidebar** holds categories (Material, Node, Code), registered
folders (File) or palette groups (Color). Right-click to
add, rename, remove — or give a category a
[colour](#category-colors). It can show per-category counts and hide empty
categories — Preferences ▸ Look.

The sidebar keeps the order **you** give it. Press and hold a row for
about half a second and it picks up — drag it where you want, let go
to keep the new order, or press Esc to put it back. **All** always
stays at the top, and a new category appears at the bottom until you
move it. This works the same in every section, File's registered
folders included; category order travels with the library, folder
order stays with each machine.

Both side panes — the sidebar and the Comments pane — keep the width
you drag them to, across sessions; the grid takes up the slack.

A tile can carry up to four **badges**, one per corner, each a glyph
on a dark backdrop so it stays readable on any thumbnail:

| | | |
|:--:|---|---|
| <img src="scripts/python/amaze/ui/badge_open.svg" width="18"> | top-left | the scene you currently have open (File) |
| <img src="scripts/python/amaze/ui/badge_star.svg" width="18"> | top-right | favorited |
| <img src="scripts/python/amaze/ui/badge_versions.svg" width="18"> | lower-left | has more than one [version](#versions) — click it to browse them |
| <img src="scripts/python/amaze/ui/badge_comment.svg" width="18"> | lower-right | carries a [comment](#comments) |

---

## Material

Houdini-native material networks with rendered shaderball thumbnails:
Redshift (classic and USD builders), Karma/MaterialX, Octane (classic
and Solaris).

### Saving

Right-click a material node in the network editor ▸ **Save to
Amaze**. Name it, give it a category and tags. Amaze builds a scene
around the node, renders a shaderball and files it away.

Saving a node Amaze recognises — from the ID stamp a previous save left
on it, or a unique name match — offers **Save Version / Save New /
Cancel**, the way any file-save should. Multi-selections always save as
new.

> Thumbnails need `$OCIO` set, and Karma additionally needs an open
> Scene Viewer (it reads the display/view transform from one). Renders
> can be switched off entirely in Preferences ▸ Render.

### Versions

Saving over a material you already have keeps the old one. When the
re-save changed only parameters — same node structure, different
values — Amaze archives the material as a **version** and the new
state becomes the active one. The first version you make also keeps
the state you were versioning away from, so the original opinion is
never the one that gets lost.

Tiles with more than one version carry the
<img src="scripts/python/amaze/ui/badge_versions.svg" width="14">
badge in their lower-left corner. Click it to open **Versions of
"…"**: pick a version to make it active, or rename the selected one.
The dialog only browses, switches and names — versions are made by
saving, never here.

Versions live with the material (`mat/versions/<id>/` and
`versions.json` in the library), so they travel with it. The base
files are always the active version's; losing the versions folder
costs the history, never the material.

Turn the whole behaviour off in Preferences ▸ Library ▸ **Material
Versions** — then saving over an existing material always adds a new
one instead. The switch lives with the library, like the rest of the
shared settings — it governs something everyone using it relies on.

### Getting one back out

- **Double-click** — imports into the context you are working in.
- **Import to MAT** / **Import to LOP** — right-click, choose explicitly.
- **Drag it** — see [Drag and drop](#drag-and-drop). This is the good way.

### Organising

Right-click a tile: **Edit Info** (name, category — one per asset —
tags, favorite, plus License and About fields that carry credits), **Toggle Favorite**,
**Rerender Thumbnail**, **Move to ▸**, **Delete Entry**.

You can also *drag* assets onto a sidebar category to file them there —
the category glows as you hover.

### Convert to Karma

Select a Redshift material, right-click ▸ **Convert to Karma**. It
rebuilds the network as a proper Karma Material Builder and then tells
you exactly what it could not translate, rather than quietly producing
something that looks nearly right. Shaders with no Karma equivalent are
named in the report.

---

## Online materials

**View ▸ Import Materials** offers four free libraries. Pick one to
browse it; pick it again to return to your own library.

| Source | What it is | Licence |
|---|---|---|
| **PolyHaven** | Photoscanned PBR materials, with textures | CC0 |
| **GPUOpen** | AMD's MaterialX library — 454 materials, with textures | MIT Public Domain |
| **PhysicallyBased** | 86 measured reference values: real copper, real water, real skin. No textures | CC0 1.0 |
| **RGL (EPFL)** | 62 laboratory-measured materials from the Realistic Graphics Lab | CC0 1.0 |

The two measured sources have no textures, so their tiles are **drawn
from the measurement** — the colour on the tile is the colour that was
measured. Amaze ships their values, so the grid fills instantly and
still works with no connection; when you are online it lists whatever
the source publishes today, so new materials just show up.

Right-click a material (or a multi-selection):

- **Import to Library** — downloads it, builds a Karma material, saves
  it into your library with a thumbnail if renders are on.
- **Import to Scene** — builds it straight into the material library you
  are working in (or `/mat`) and writes nothing to your library. For
  when you just want the material in front of you.
- **Refresh** — re-reads the source now. You rarely need it: the
  browser already lists whatever the source currently publishes, so new
  materials simply appear.

**Double-click imports to the scene**, like double-click everywhere
else: the primary action puts the asset where you are working.

Every import records its source, author, link and licence in Edit Info.
None of these sources requires attribution — but a library full of
other people's work should be able to say whose it is.

### Gallery Import (.gal)

**View ▸ Import Materials ▸ Gallery Import (.gal)** reads a Houdini
gallery file — including the Material Palette's own — and turns every
material preset in it into a library material. Thumbnails are
deliberately *not* rendered during a bulk import (hundreds of renders
would take hours); render a selection afterwards when it suits you.

---

## Generate Material

**View ▸ Import Materials ▸ Generate Material** builds one plausible
material into the material library you are working in.

These are not invented numbers. Amaze ships 148 real measured materials
— the 86 PhysicallyBased reference constants and the 62 RGL
measurements — and generation starts from one of them, **in its own
physical class**:

- **Metals** keep their spectrum. A metal's colour *is* its
  reflectance, so copper stays copper: it drifts a few percent, or
  blends toward another measured metal the way an alloy sits between two
  elements, and takes its finish from a measured metal surface.
- **Glass and liquids** keep their measured IOR exactly. Water is 1.333
  or it is not water.
- **Skin, marble, milk** keep their measured scattering distance.
- **Opaque dielectrics** get a free hue — pigment is arbitrary, paint
  can be any colour — with roughness from the measurement.

Clearcoat, sheen and emission are things measurements never mention and
artists add, so their rates come from a corpus of 287 real authored
materials: about a third carry a clearcoat, almost none emit.

Every generated material writes its lineage into the **node comment** —
which measurement it came from and what was varied. Generated materials
are scene nodes, not library entries; keeping one is a deliberate *Save
to Amaze*, exactly like a material you built by hand.

---

## Color

Curated colour-theory palettes — Sanzo Wada's *A Dictionary of Color
Combinations*, Paul Klee, Josef Albers, Johannes Itten — plus gradients
you save yourself.

- **Apply as Stepped Ramp** / **Apply Ramp** — pushes the palette onto a
  selected node's ramp parameter. A selected node that has no ramp
  parameter does not block it: Amaze creates the ramp node instead,
  the same as double-clicking the tile.
- **Apply as Linear Ramp** — curated gradients only.
- **Copy Color ▸** — a submenu of the individual swatches, each labelled
  with its hex code; picking one copies the hex to the clipboard. (A
  node has many colour inputs — guessing which one you meant was worse
  than letting you paste.)
- Save your own: right-click a node with a colour ramp ▸ **Save Gradient
  to Amaze**.

---

## Node

Save node setups — a whole network, a selection, or a single node — and
load them back. Works in any context Amaze supports: SOP, Copernicus,
LOP, DOP, TOP, CHOP and object level. Each asset remembers which context
it came from, shown on its tile.

Right-click a network container (a `geo`, a `copnet`, a `lopnet`, a
subnet) ▸ **Save Network to Amaze** to keep its whole interior, or
right-click the nodes themselves ▸ **Save Selection to Amaze**. Select
several nodes first and the selection wins — the label tells you which
one you are about to get.

Double-click or drag a tile to bring the nodes back. They land in the
network you release over, or in a fresh container of the right type.

**An asset only goes home.** A SOP asset dropped on a Copernicus network
is refused with a message rather than half-created — those nodes cannot
exist there, and a partial network is worse than none.

Thumbnails follow the context: a Copernicus asset shows its own output
image, a SOP asset shows its geometry, and everything else shows the
node icon — a LOP setup has no picture to take, and that is normal, not
a failure.

---

## Code

A snippet library for VEX, OpenCL and Python, with syntax-highlighted
previews on the tiles and a curated **Starter Toolbox** to begin with.

- **New Snippet** — write one in the dialog.
- **View / Copy Code** — read it, copy it.
- **Apply to Selected Node** — pushes the snippet into the selected
  node's code parameter.
- **Edit Snippet**, **Toggle Favorite**, **Delete Entry**.
- Right-click any node with a code parameter ▸ **Save Code to
  Amaze**.

Double-click or drag a snippet onto a node to apply it.

---

## File

Register folders on disk and browse **everything** in them — one
section for your images, models, scenes and whatever else lives beside
them. Each file behaves as its kind:

- **Images** (PNG, JPG, EXR, HDR, TGA, RAT, …) get cached thumbnails.
  **Double-click** or **Load to Node** pushes the file onto a selected
  node's image parameter; drag one onto any parameter field like a
  file from Finder or Explorer. Formats Qt cannot read are converted in
  the background — the number of parallel conversions is in
  Preferences ▸ Render.
- **Geometry** (`.bgeo`, `.obj`, `.fbx`, `.abc`, `.usd`, …) gets
  viewport-rendered thumbnails, wire over shaded. **Double-click** or
  drag into a network to import in context; the import puts your
  current node and display flag back where they were. A recursive scan
  of a big library can queue many first-time renders — the pass is
  interruptible with Esc and resumes later.
- **Scenes** (`.hip`, `.hiplc`, `.hipnc`) **open on double-click**,
  with Houdini's own save prompt in charge of unsaved changes. Drag one
  out of the panel and release anywhere outside it to open it the same
  way. The scene currently open carries a tick on its tile. Scene
  thumbnails are **captures**: open the scene from Amaze, frame the
  viewport, then right-click ▸ **Capture Thumbnail from Viewport** (or
  the camera button in the toolbar). Nothing is ever captured or
  rendered automatically — a scene cooks when you say so.
- **Everything else** shows its system icon and has one action —
  **Copy Path**, which puts the path on the clipboard the way Houdini
  writes paths (see **Write Paths As** below). A motion-capture file's
  path pasted into a parameter is a real workflow; pretending Amaze
  could open the file is not. Hide these entirely with
  Preferences ▸ Look ▸ **Show Unknown Files** off.

Every row can be favorited, given a [tile icon](#tile-icons), revealed
in the file browser, or path-copied. There is deliberately **no
Delete** here: these are your files on disk, not library entries.

### Locations

Right-click the sidebar:

- **Add Folder** registers a location — a pointer, nothing is scanned
  or copied until you open it.
- **Remove Folder** unregisters it and forgets everything about it —
  its label, colour, Include Subfolders and Show All Files
  settings, its favorites, comments and tile icons, and its cached
  thumbnails. Re-adding the folder gives you a clean slate. Captures
  are the exception and are kept: you framed those by hand, and
  nothing can render them again.

  Removing a folder clears it for everyone who uses the library —
  registrations live with the library now, so it does not come back
  from the other computer. If Amaze was open on the other computer at
  that moment, close and reopen it there and the removal shows.
- **Locate Folder…** re-points a location that moved on disk;
  favorites, its name and its settings follow.
- **Rename Folder…** gives it your own label. The default name is the
  path itself; an empty rename goes back to that.
- **Include Subfolders** is **per location** — a deep asset tree can
  recurse while a flat downloads folder stays shallow. Off by default:
  a deep tree can queue a lot of first-time thumbnails.

### Write Paths As

Preferences ▸ Look ▸ **Write Paths As** controls how Amaze writes
paths — Copy Path and the location labels: **$HOME** (the default),
**$JOB**, **$HIP**, or **Absolute**. A variable applies when the
path lives under it; otherwise the path stays absolute.

---

## Tile icons

Not everything has a picture. A LOP setup, a DOP network, a snippet —
there is nothing to render, and a grid of identical fallback tiles tells
you nothing about what is in it.

Right-click any tile ▸ **Edit Icon…** and pick one of 287 Feather icons
on a background colour: four presets, or any colour you like via
**Custom Color**. The preview shows the actual tile, because the icon
and the colour only make sense together. **Icon Color** switches the
symbol between dark and light, for when the background needs it.
**Accept** sets it, **Remove** takes it away — closing the window
changes nothing.

- Works on **every section that has tiles** — Material, Node, Code and
  File, scenes included. Color keeps its own swatches.
- Applies to the **whole selection**, so twelve LOP setups can take one
  icon in one go.
- **Nothing is overwritten.** A tile with a rendered thumbnail keeps it;
  the icon sits beside it, and **Remove** brings the render back.
- Your choice travels with the library — it is stored on the asset
  (or, for File rows, in an `icons.json` beside the index).

The line weight is in Preferences ▸ Look.

---

## Category colors

Right-click a category in the sidebar ▸ **Set Color…**. Every tile in
that category paints the strip under its thumbnail — the one carrying
the name and type — in that colour, and the category's own sidebar row
gets a matching bar down its left edge.

It is a way to see structure at a glance: which of these are metals,
which are yours, which came from a scan. **Clear Color** puts the
normal dark strip back.

The name and type text flips between dark and light automatically, so
any colour stays readable. Renaming a category carries its colour
across; deleting one takes the colour with it.

Categories are one-per-asset, which is what makes this unambiguous —
use tags when something belongs in several places at once.

---

## Comments

The Comments chip in the toolbar (between the Renderer and grid
buttons) opens the **Comments pane**: a page docked beside the grid,
one page per asset. The chip stays the toolbar's blue whether the pane
is open or not — the state is carried by its background, not by the
glyph changing colour.

The page is one flowing document. Select a tile and write; click
**+** to drop a to-do at your cursor — a framed line you type into —
and keep writing above or below it. Enter inside a to-do adds
another; Enter on an empty one returns to plain text; clicking a
to-do's marker checks it off (struck through). Emptying a to-do's
text removes it. Everything saves as you type.

To take a to-do apart, backspace at the start of its line: the frame
becomes ordinary text and the next backspace eats the words. Deleting
across the line above or below a to-do simply joins the lines — the
frame keeps its marker.

Comments live **in the library** (`notes.json` beside the index, a
filename that kept its old spelling), so they
travel across machines and survive a folder being removed and
re-added. A tile that carries a comment shows the
<img src="scripts/python/amaze/ui/badge_comment.svg" width="14"> badge in
its lower-right corner.

Every section takes comments — materials, palettes, nodes, snippets and
File rows alike.

---

## Drag and drop

Amaze manages the whole drag gesture itself, so a drag behaves the same
everywhere and never leaves Houdini in a half-state.

**Materials**

- Onto an **OBJ viewport** object — assigns the material to it.
- Onto a **Solaris (LOP) viewport** object — a menu appears:
  - **Swap ‹material›** — replaces a material already bound to that
    prim. The old one is removed from the library node if nothing else
    references it.
  - **Set as Material on ‹prim›** — one entry per ancestor prim, so you
    can bind to the mesh or to the whole geo.
- Onto a **`materiallibrary` LOP** in the network editor — imports into
  it, wired and registered.
- Onto the **network editor** — imports the material there.

While you drag over a viewport, the prim under the cursor highlights
using Houdini's own scene-graph highlight. A drop that lands nowhere
useful shows a miss indicator
<img src="scripts/python/amaze/ui/icon_drop_miss.svg" width="14">
rather than silently doing nothing.

**Everything else**

- **Images and unknown files** onto a parameter field — like a file
  from the OS file browser.
- **Geometry** into a network or viewport — imports in context at the
  release point.
- **Scenes** released anywhere outside the panel — opens the scene,
  same as double-click.
- **Code** onto a node — fills its snippet parameter.
- **Any asset** onto a sidebar category — files it there.

---

## Preferences

The <img src="scripts/python/amaze/ui/icon_library.svg" width="16">
gear button. It is a floating window, not a modal — leave it open while
you work.

**Library** — library path, **Clean Up Library**, **Reload Library**,
**Open Library Folder**; cache path and **Delete Local Cache**.

> Settings that govern the library itself — the render settings and
> renderer choices, conversion and download throughput, and how paths
> are written — are stored **with the library** and shared by everyone
> who opens it: change the thumbnail samples on one computer and the
> other answers the same. What is yours on this machine — view mode,
> icon sizes, panel widths, which tabs show — is stored per person
> where the OS keeps preferences (`~/Library/Preferences/Amaze` on
> macOS, `%APPDATA%\Amaze` on Windows, `$XDG_CONFIG_HOME/Amaze` on
> Linux), not in the plugin folder, so updating or reinstalling Amaze
> never touches it. If the library is unreachable, Amaze keeps
> working on the last values it saw.

**Render** — thumbnail resolution, samples (Redshift and Karma
separately), RAM cache, geometry shading mode and
background, **Render Thumbs on Import**; then texture conversion
threads, and the download resolution and parallel downloads used by the
online sources.

**Show/Hide** — which renderers and which sections appear at all.

**Look** — counts on categories, hide empty categories, **Show
Unknown Files** (the File section's system-icon rows), **Write Paths
As** ($HOME / $JOB / $HIP / Absolute), **Tile Icon Line** (Thin or
Feather's own Regular), scroll speed.

**About** — credits and licences, and the debug controls: **Debug
Mode**, **Open Log**, **Clear Log**.

---

## Housekeeping and troubleshooting

**Clean Up Library** (Preferences ▸ Library) scans the whole estate in
one pass: entries whose files are missing, uncategorized assets to
rescue, category names to normalise, registered folders that no longer
exist, favorites pointing at missing files. One summary, and it never
renders anything.

**It moves, it does not delete.** An entry whose files are missing is
reported and kept - the entry holds tags, comments and favourites stored
nowhere else, and a file mid-sync looks exactly like a file that is
gone; you remove it yourself with Delete Entry if it really is dead.
Files no list claims move into Amaze's own holding folder on this
computer (outside your library, so it never syncs), are named in the
summary, and are kept for 30 days before they are removed for good.
Folders on a drive that simply is not mounted right now are left
alone.

**Repair** is the shelf tool beside Amaze's own, and it is the one to
reach for when Clean Up Library refuses, or when the panel will not
open at all. It reads your library, tells you in plain words what is
wrong, and offers only what is safe: rebuilding the list from the
recovery copy stored beside each asset, or putting back one of the
snapshots. **It never deletes anything** — the strongest thing it can
do is move files into a dated folder inside your library.

It lives on the shelf rather than in the panel on purpose. A running
panel writes the list as you work, so a repair made from inside it
would be overwritten by the panel seconds later, leaving you believing
you had recovered when you had not. From the shelf the panel is
closed, nothing holds your library, and nothing is about to save over
the result.

**Your library is safe by design.** Every write snapshots the index
first (rolling backups plus an immutable first-run copy), and a
concurrent write from a second Houdini session is merged rather than
overwritten.

**Overwrite can be switched off for a whole library.** The setting
lives in Preferences ▸ Library, and unlike everything else in
Preferences it travels with the LIBRARY rather than with your machine —
it is kept in a small `policy.json` beside your assets, so two
computers pointed at one library agree about it. With it off, saving
over an existing material is refused and the Save dialog stops offering
Overwrite at all. Worth setting on a shared library where the paragraph
below would otherwise apply.

That applies to the **list** of your assets. An individual asset's own
files are a different thing: choosing **Overwrite** when you save over
an existing material replaces them, and the last save wins. That is
what Overwrite means, and it is the one place the sentence above does
not cover — worth knowing if two people share one library.

**When something looks wrong**, turn on **Debug Mode** (Preferences ▸
About) and reproduce it. The log is structured JSON Lines recording
what the app actually did — the fastest route to a fix, and worth
attaching to a bug report.

**A material renders black?** Usually a texture that failed to
download, or a material library node whose material list no longer
covers the material. The log names both cases explicitly.

**Changed a Python file?** Houdini caches modules per session — quit and
relaunch. Reopening the panel is not enough.

---

## Credits and licence

Amaze is its own product, and it contains code from
[egMatLib](https://github.com/eglaubauf/egMatLib) by Elmar Glaubauf —
the foundation it grew from.

Tile icons are [Feather](https://feathericons.com) by Cole Bemis (MIT).

Online material sources: [Poly Haven](https://polyhaven.com/) (CC0),
[AMD GPUOpen](https://matlib.gpuopen.com/) (MIT Public Domain),
[Physically Based](https://physicallybased.info/) by Anton Palmqvist
(CC0 1.0), and [EPFL RGL](https://rgl.epfl.ch/materials) measured
materials (CC0 1.0). Colour palettes come from public-domain works.

Amaze is **GPLv3** — see [LICENSE](LICENSE).
