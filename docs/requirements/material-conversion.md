# Material conversion: requirements

What Convert to must do. The engine is `render/material_conversion/`,
`render/material_converter.py`, `render/redshift_converter.py`, and `convert` and
`convert_rows` in `actions/materials.py`; the pane only shows the message. The node menu's
Convert to is its own engine. The levels and the rules for tests are in the [README](README.md).

## Catastrophe

- MC-01 Catastrophe: Converting never changes the source material: its row, record, network, picture, textures, versions and comments stay as they were.
- MC-02 Catastrophe: A conversion that fails at any step, its save included, adds nothing to the library: no row, no folder, no file.

## Severe

- MC-10 Severe: The converted copy is saved as a new material with its own id and folder; it never saves over the source or another material.
- MC-11 Severe: Converting leaves the open scene as it was: what it builds is removed when it ends, and none of it is on Houdini's undo list.

## Wrong output

- MC-20 Wrong output: A material is converted only when both renderers' plugins are loaded and it is not already the target; otherwise nothing is built and the reason is given.
- MC-21 Wrong output: Every renderer converts to every other, through MaterialX.
- MC-22 Wrong output: The copy is saved as the target renderer's own builder, so it reads as that renderer and loads into /mat and into a material library in /stage.
- MC-23 Wrong output: The copy's surface output is wired; when it cannot be, the report says the material renders black.
- MC-24 Wrong output: The copy uses every texture file the source uses, from its own copies in its own folder.
- MC-25 Wrong output: The copy keeps the source's name, categories, tags and licence; it is not a favorite and has no comments.
- MC-26 Wrong output: Every input the conversion leaves out or only approximates is named in its report.
- MC-27 Wrong output: After Convert to, one message says how many selected materials were converted, with each one's report; one that fails does not stop the others.
