# Drop into the scene: requirements

What releasing a tile over Houdini must do. The engine is `core/dragengine.py`, `pane/drop_placement.py`,
`core/lop_assign.py`, `render/cop_nodes.py`, the drag and its release in `pane/drag_session.py` and each
section's drop handlers. What an import builds is SL (SL-12, SL-27); a drop on a sidebar folder is a
file move (FM). The levels and the rules for tests are in the [README](README.md).

## Severe

- DD-01 Severe: One undo takes back a whole drop: every node made, wire spliced, parameter set, material bound, and any Material Library made for it.
- DD-02 Severe: A drop that fails at any step, a locked network included, leaves no node it made, never stops Houdini, and says why.
- DD-03 Severe: A material Swap never deletes a material the scene still uses: a binding on any branch, layer or node keeps it.

## Wrong output

- DD-20 Wrong output: Over a node that takes the tile, the tile goes to that node; over network space, a node is made in the network shown, at the outlined spot; over a network that cannot hold it, or over nothing, nothing is made and the miss is shown.
- DD-21 Wrong output: Released on a wire, the new nodes are inserted into it; near a free connector, they are wired to it; a new node is never wired to itself.
- DD-22 Wrong output: A file dropped on a node sets its first file parameter, written as Write Paths As says; a snippet sets its code parameter, a gradient its colour ramp; a node without one is a miss with the reason.
- DD-23 Wrong output: Geometry goes into a SOP network as a loader, into Solaris as a new SOP Create chained to the display node, elsewhere as a new geo named after the file; the new node is displayed, current and selected.
- DD-24 Wrong output: A material dropped on a prim in a Solaris viewport offers Swap for each material bound under it, then Set as Material on the prim and each parent; the pick imports into Houdini's own Material Library for that network and binds or swaps.
- DD-25 Wrong output: A material dropped on an object in an object viewport is imported into /mat and set as that object's material; an object with no material parameter gets nothing.
- DD-26 Wrong output: Placing dropped nodes never moves the user's own nodes.
- DD-27 Wrong output: Esc, a right or middle click, or the panel hidden ends a drag, and its release makes nothing.
- DD-28 Wrong output: A viewport drop lands on the prim or object under the cursor at every display scale.
