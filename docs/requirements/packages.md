# Packages: requirements

What exporting and importing a `.amazepkg` package must do. The engine is `core/packages.py`, with
its callers in `pane/package_import.py`, `sections/base.py` and `sections/file.py`, and the parts it
uses: `core/texstore.py`, `core/asset_record.py`, and `core/library_conversion.py` for old packages.
Amaze's own packages are built by `tools/build-default-packages.py`. Add-ons share the container but
are their own engine, with their own [list](add-ons.md). The levels and the rules for tests are in
the [README](README.md).

## Catastrophe

- PK-01 Catastrophe: An import never writes over a file in the library: each asset gets a new folder, and each plain file a free name in `import/`.
- PK-02 Catastrophe: An import writes only into each new asset's folder and `import/`; a member or texture path that leaves them refuses that asset.
- PK-03 Catastrophe: Each asset arrives whole or not at all: its row and every file it brings in one change; cut off at any moment, by a full disk, a crash or a member that does not read back whole, it leaves no row, no folder and no stray file.
- PK-04 Catastrophe: A package that cannot be read whole changes nothing: a damaged zip, a missing or unreadable manifest, a misshapen entry, a missing member, a newer format, an add-on, or more than 16 GB unpacked is refused before the first write, with the reason.
- PK-05 Catastrophe: An export changes nothing in the library beyond saving changes already waiting, and is written whole or not at all: a failed one leaves no package, or the old one as it was, and no scratch file.

## Severe

- PK-10 Severe: An import is never saved over another asset: every asset gets a new id, old packages included, so a package imported twice, not restored, gives two copies.
- PK-11 Severe: An import never freezes Houdini: a store tile shows its download's progress, never waits behind a preview, and no member is read whole into memory.
- PK-12 Severe: Restore of Amaze's own packages is a factory reset: each older copy with the same `curated` mark goes to the trash and the package's copy takes its place with a new id; an asset without that mark is never touched.

## Wrong output

- PK-20 Wrong output: An export carries each asset's row, comments, network, COP network, builder, picture and every texture its record lists; the packed record lists exactly the textures packed.
- PK-21 Wrong output: An export that cannot find a texture its record lists names it to the user.
- PK-22 Wrong output: An imported asset has a new id, the category Import, no favorite, and every other field of its row, ones this Amaze does not know included; its folder is `<name>__<new id>`, and its network finds every texture in it.
- PK-23 Wrong output: An imported asset keeps its comments under its new id, with the pictures pasted into them.
- PK-24 Wrong output: A package from an older Amaze imports the same way: a 2.0 texture path is placed where LS-38 reads it, an old builder becomes the record's builder, and the picture its tile showed becomes its picture.
- PK-25 Wrong output: A plain file goes into `<library>/import/`, numbered when the name is taken, and the Import location shows in the File sidebar, keeping a name the user gave it.
- PK-26 Wrong output: An asset that fails is refused alone; the others still import.
- PK-27 Wrong output: After an import the user is told how many assets and files arrived, why each refused one was refused, and which comments could not be written.
- PK-28 Wrong output: An Amaze that cannot read a package's textures refuses it as too new; it never imports it in part.
- PK-29 Wrong output: Export Asset packs the selected tiles, Export Category the category or the whole section for All, and the File section each selected file whole with its kind.
- PK-30 Wrong output: Amaze's own packages carry only assets with their `curated` mark: a build names every asset without one and writes no package.
