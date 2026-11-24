# Saving and loading assets: requirements

What saving a scene node as a material or node asset, saving over one (Update Existing), and loading one
back must do. The engine is `render/nodes.py` (`NodeHandler`), `actions/materials.py`, `actions/nodes.py`
and `core/asset_record.py`, with `core/texstore.py` at save and load, `pane/saving.py` and the right-click
`Save to Amaze` in `utils/rc_calls.py`. Where files go and how they are written is
[library storage](library-storage.md); what a save over a material keeps as a version is
[versions](versions.md) (VS-10, VS-26). The levels and the rules for tests are in the [README](README.md).

## Catastrophe

- SL-01 Catastrophe: A new asset is saved whole or not at all: its row, network, record, textures and COP network arrive together, and a save that fails leaves no row, no file and no folder.
- SL-02 Catastrophe: Saving over an asset replaces its network, record and COP network together; a save that fails at any step leaves the old ones as they were.
- SL-03 Catastrophe: Saving over an asset is refused when another session changed its network since this one read it, and their files stay as they are.
- SL-04 Catastrophe: An asset's record that cannot be read is never written over by a save.

## Severe

- SL-10 Severe: Saving leaves the scene as it was: the saved nodes, their texture paths, the selection and the undo list.
- SL-11 Severe: Update Existing is offered only for the asset a node was saved as or imported from: an imported node carries that asset's id, and the nodes inside it carry none.
- SL-12 Severe: An import that fails leaves the scene as it was: nothing it made is left, a Material Library, network or COP network included, and nothing already there is changed.

## Wrong output

- SL-20 Wrong output: A saved material loads back with the same nodes, wires, values, expressions, keyframes and builder controls, with its surface output wired.
- SL-21 Wrong output: A saved node setup loads back with its nodes, notes, boxes and dots, wires through dots included; into a network of its own kind it lands loose in its saved layout, elsewhere in a new container.
- SL-22 Wrong output: A material that uses a COP network loads with that network beside it and its references pointing at it; saving it over without one removes the old one.
- SL-23 Wrong output: A loaded material's texture paths point into its own folder, written as Write Paths As says.
- SL-24 Wrong output: An import that cannot work says why before it makes anything: an id that leads outside the library, a missing or empty network file, or a node type whose plugin is not loaded.
- SL-26 Wrong output: A picture that fails to render costs only the picture: the asset is still saved and listed.
- SL-27 Wrong output: An import goes into the network open in the editor: a Material Library in Solaris, else a material network, one reused for every import.
