# Info pane: requirements

What the info pane must show about the selection: its facts, and an image file's picture. The
engine is `core/file_info.py`, `info_rows` and `_info_facts` in each section's model,
`info_subject` in `sections/base.py`, `core/image_preview.py` and `pane/info.py`. The
levels and the rules for tests are in the [README](README.md).

## Catastrophe

- IN-01 Catastrophe: Showing facts or a picture only reads: no file is written, moved or removed.

## Severe

- IN-10 Severe: Reading facts never holds up or crashes Houdini: it runs in the background, reads nothing while the pane is hidden, stops a Houdini tool after 10 seconds, opens a USD file without its payloads, and stops when the selection changes or Houdini quits.
- IN-11 Severe: Reading a picture never holds up or crashes Houdini: off the UI thread, only while the pane and its picture are shown, reading only the smallest MIP level wide enough and only colour and alpha, and stopped when the selection changes, the pane hides or Houdini quits.

## Wrong output

- IN-20 Wrong output: Facts read for an earlier selection are never shown for the current one.
- IN-21 Wrong output: A material's or node's Size is every file in its folder added up: record, network, picture, versions, textures and downloaded sources.
- IN-22 Wrong output: A material shows how many of its textures exist and the size in pixels of the largest one.
- IN-23 Wrong output: An asset shows its name, date, licence and id, and its version when that is not just its name; a fact with no value has no row.
- IN-24 Wrong output: A material shows its renderer, a node its context, a snippet its language and lines, a color its colors, values and interpolation.
- IN-25 Wrong output: A file shows its name without its ending, its dates, size, format and folder; a missing file only its name, format and folder.
- IN-26 Wrong output: A picture adds its size in pixels, colour space, bit depth, channels, compression and MIP maps.
- IN-27 Wrong output: A geometry file adds its counts, attributes, bounds and the Houdini that saved it; a USD file its prims, layers, default prim, up axis, units and frames.
- IN-28 Wrong output: Several selected items show how many they are and the size of all their files, a shared file counted once.
- IN-29 Wrong output: An image file the pane reads shows at the pane's width in screen pixels, upright, in its own shape, with alpha, one channel as grey, scene values through Houdini's display view.
- IN-30 Wrong output: The picture shown is always of the file selected now; a late one for another file is dropped.
- IN-31 Wrong output: No decoded picture is kept: hiding the picture or the pane drops it, and showing it again reads the file again.
- IN-32 Wrong output: Making the pane wider reads the picture again at the new width once the drag stops, unless the picture already is the whole file.
