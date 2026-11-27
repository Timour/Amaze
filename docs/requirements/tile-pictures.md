# Tile pictures and captures: requirements

What giving an asset or a file its picture must do: rendering a material, a SOP or a COP network,
capturing the Scene View, and finding the picture a tile shows. The engine is `render/thumbs.py`,
`render/husk_job.py`, `preview/`, `core/scene_captures.py`, `core/captures.py`, the picture paths
in `core/tile_icons.py` and the loader in `core/thumbnails.py`. Where an asset's folder is, and how
a file is written whole, belong to the [library storage](library-storage.md) list (LS-01, LS-36).
Turning a user's picture file into a tile picture is its own [list](picture-conversion.md). The
levels and the rules for tests are in the [README](README.md).

## Catastrophe

- TP-01 Catastrophe: Every new picture, rendered, captured or brought in by an import, is put in place whole: a write cut off at any moment leaves the old picture or the whole new one.
- TP-02 Catastrophe: A render that is cancelled, stalls, fails or is stopped by quitting Houdini, and a capture that is refused or comes out one flat colour, leaves the old picture as it was.

## Severe

- TP-10 Severe: A picture goes only to the asset it was made for, as `<id>.png` in that asset's folder: an asset renamed during its render gets it in its new folder, a deleted one gets nothing and no folder is made for it, and an id that leads anywhere else writes nothing.
- TP-11 Severe: A render leaves the user's scene as it found it: no node left behind, nothing on the undo list, nothing imported into the user's own networks, the selection as it was, and a user's node with the same name untouched.
- TP-12 Severe: No render process outlives Houdini or its Cancel: one that ignores the stop is killed after 5 seconds, one silent for 10 minutes is stopped, and no job folder is left. A conversion is stopped as CV-10 says: Houdini never waits more than half a second for a converter that will not die, and a stuck one is set aside.
- TP-13 Severe: A capture is taken only when the user asks for one, never when a scene opens, and never while a renderer other than Houdini's own draws the viewport; then the user is asked to stop the render.
- TP-14 Severe: Reloading Amaze while pictures load never crashes Houdini: no loader thread is freed while it runs.

## Wrong output

- TP-20 Wrong output: Each material in a render gets its own picture, in its own renderer with that renderer's samples setting; a selection renders in one background render per renderer.
- TP-21 Wrong output: With no Scene Viewer open nothing is imported or rendered and the user is told once; a material whose renderer is not loaded is named in one message, and the rest still render.
- TP-22 Wrong output: A material, SOP or geometry picture is a square PNG at Thumbnails ▸ Size in Pixels; a COP picture is the network's own image as a PNG; a capture is a PNG in the viewport's shape, its long side at most 1024 pixels.
- TP-23 Wrong output: Saving a material, SOP or COP renders its picture when Render Thumbnails on Import is on, an online import's own picture is used instead of a render, and Render Image renders again whatever the setting; other networks get no picture and no error.
- TP-24 Wrong output: A file's capture is kept in the library as `files/<hash of its key>.png`, one file for the shelf tool and the tile on every computer, and it stays when the scene is saved again.
- TP-25 Wrong output: A scene is captured only while it is the scene open in Houdini and saved on disk; otherwise the user is told why and nothing is written.
- TP-26 Wrong output: A new picture shows on its own tile, in every open panel, without a restart; a picture that arrives late never replaces a newer one.
- TP-27 Wrong output: Two libraries never show each other's picture for the same asset id.
- TP-28 Wrong output: Scrolling the grid never waits on the disk: a tile's picture path is worked out without touching it, and the picture loads in the background.
- TP-29 Wrong output: A file's generated preview (geometry, image) is kept in the user's cache, never in the library; a file that cannot be read is not tried again until it changes or the user asks Render Image.
- TP-30 Wrong output: A colour's picture runs top to bottom, the first colour at the top, for every interpolation.
- TP-31 Wrong output: A geometry file's picture shows the whole geometry in the middle of the picture, filling it but for a narrow margin.
