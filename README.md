<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/LightLogo.svg">
  <img src="docs/DarkLogo.svg" alt="logo" width="200">
</picture>

### An asset manager for Houdini

Amaze is an asset manager for SideFX Houdini. It stores materials, colour palettes, node groups and code snippets in a personal library on disk, and brings them back into the scene when needed.

Drag a material onto an object in the viewport to assign it. Save a group of nodes from any network — SOP, Copernicus, LOP and more — and import it back into a matching one. Drop code snippets into wrangles, apply palettes to ramp and colour parameters, and drag files from registered folders onto file parameters. Free online material libraries — PolyHaven, AMD GPUOpen and more — are built in.

[![Interface](docs/images/interface.png)](docs/images/interface.png)

**→ [Read the manual](MANUAL.md)** 
## Sections

Everything saved to the library appears as a tile in the grid — a picture and a name — sorted into sections, one tab per kind.

- **Material** — save materials and bring them back into any scene: drag one onto an object in the viewport to assign it, or import into `/mat` or a LOP material library. Redshift (classic + USD builders), Karma/MaterialX, Octane (classic + Solaris builders). Filter by category, tag, favourite or renderer.
- **Color** — save gradients and palettes and apply them directly to parameters: stepped or linear ramps to ramp parameters, single swatches to colour parameters. Ships with palettes inspired by the colour theories of Sanzo Wada, Paul Klee, Josef Albers and Johannes Itten.
- **Node** — save a group of nodes from any context (SOP, Copernicus, LOP, DOP, TOP, CHOP, object level) — a whole network, a selection, or a single node — and import it back into a matching context.
- **Code** — keep the VEX, OpenCL and Python snippets you rely on: double-click to apply to the selected node, or drop one into the network.
- **File** — register folders on disk and use their contents from the panel: drag images onto file parameters, import geometry in context, open scenes with a double-click.
- **Comments** — write text, add images and to-dos to any asset.
- **Category colors** — colour-code the library: assign a colour to a category and every tile in it carries that colour.

## Highlights

- **Online material libraries, built in** — browse free CC0/MIT materials from PolyHaven, AMD GPUOpen, PhysicallyBased and EPFL RGL, plus Amaze's own packages, behind the toolbar's Online button. Import into the library, or directly into the scene.
- **Drag and drop everywhere** — drop a material onto an object in the viewport: in OBJ it is assigned; in Solaris you pick the prim and it imports into that stage's `materiallibrary`. Drag a tile onto a sidebar category to refile it, and files onto parameter fields.
- **Versions** — re-saving a node that matches a library entry offers Save Version / Save New; previous states are kept as versions.
- **Redshift → Karma converter** — best-effort translation into Karma Material Builders, with a report of everything that could not be translated.
- **Updates from Preferences** — checks the GitHub release feed, verifies the download, and backs up the install it replaces.
- **Fast** — thumbnails load in the background and cache to disk.
- **Portable storage** — assets live on disk as plain Houdini node archives and a JSON index; they load with vanilla Houdini even without Amaze.

## Compatibility

Houdini 21.0 or newer — developed and tested on 21.0 and 22.0, macOS (Apple Silicon). Linux and Windows are expected to work but receive less testing.

## Installation

1. Copy (or clone) this repository to a folder of your choice, e.g. `/path/to/Amaze`.
2. Copy the `Amaze.json` template from the repository root into `$HOUDINI_USER_PREF_DIR/packages/` and point `AMAZE` at the folder from step 1:

```json
{
    "env": [
        { "AMAZE": "/path/to/Amaze" }
    ],
    "path": [ "$AMAZE" ]
}
```

3. Launch Houdini and add an **Amaze** pane tab.
4. Open Preferences (the gear) and choose a library folder — this is where saved assets are stored. Keep it outside the plugin folder.

Preferences are stored per user, outside this repository — updating with `git pull` never touches them.

## Status

Actively developed. To report a bug, update to the latest release first, then [open an issue](https://github.com/Timour/Amaze/issues).

## Acknowledgements

- **[Elmar Glaubauf](https://github.com/eglaubauf)** — Amaze uses the [egMatLib](https://github.com/eglaubauf/egMatLib) preview engine for material thumbnails. Thank you.
- Color palette sources: Sanzo Wada (public domain, via [dblodorn/sanzo-wada](https://github.com/dblodorn/sanzo-wada)), Paul Klee, Josef Albers, Johannes Itten (interpretive palettes from public-domain works).

## License

**GPLv3**, same as upstream — see [LICENSE](LICENSE). Free to use, modify, embed and redistribute under the license's terms.
