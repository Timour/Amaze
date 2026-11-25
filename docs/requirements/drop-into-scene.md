# Drop into the scene: requirements

What releasing a tile over Houdini must do. The engine is `core/dragengine.py`, `pane/drop_placement.py`,
`core/lop_assign.py`, `render/cop_nodes.py`, the drag and its release in `pane/drag_session.py` and each
section's drop handlers. What an import builds is SL (SL-12, SL-27); a drop on a sidebar folder is a
file move (FM). The levels and the rules for tests are in the [README](README.md).

## Severe

- DD-01 Severe: One undo takes back a whole drop: every node it made, wire it spliced, parameter or material it set, and any material library made for it.
- DD-02 Severe: A drop that fails at any step, a locked network included, leaves no node it made, never stops Houdini, and says why.
- DD-03 Severe: A material Swap never deletes a material the scene still uses: a binding on any branch, layer or node keeps it.
- DD-04 Severe: One undo takes back a whole Swap Material: the import, any material library made for it, the new binding or Material parameter, and the old material it removed.

## Wrong output

- DD-20 Wrong output: Over a node that takes the tile, the tile goes to that node; over network space, a node is made in the network shown, at the outlined spot; over a network that cannot hold it, or over nothing, nothing is made and the miss is shown.
- DD-21 Wrong output: Released on a wire, the new nodes are inserted into it; near a free connector, they are wired to it; a new node is never wired to itself.
- DD-22 Wrong output: A file dropped on a node sets its first file parameter, written as Write Paths As says; a snippet sets its code parameter, a gradient its colour ramp; a node without one is a miss with the reason.
- DD-23 Wrong output: Geometry goes into a SOP network as a loader, into Solaris as a new SOP Create chained to the display node, elsewhere as a new geo named after the file; the new node is displayed, current and selected.
- DD-24 Wrong output: While a material is dragged over a Solaris viewport, the prim under the pointer is highlighted. Dropped on a prim, a menu opens at the drop point with Set as Material on that prim and on each parent, worded as Houdini words them. The row picked imports the material into the material library Houdini picks and assigns it; closing the menu imports nothing. On empty space nothing is made and the miss is shown.
- DD-25 Wrong output: While a material is dragged over an object viewport, the object under the pointer glows as in Houdini's own drag. Dropped on an object, it is imported into `/mat` and set as that object's material, with no menu. An object with no material parameter, or empty space, gets nothing and shows the miss. In a viewport showing any other network, the drop does nothing.
- DD-26 Wrong output: Placing dropped nodes never moves the user's own nodes.
- DD-27 Wrong output: Esc, a right or middle click, or the panel hidden ends a drag, and its release makes nothing.
- DD-29 Wrong output: Swap Material is offered only with one tile chosen and exactly one object or prim selected in the scene viewer. An object gets the material, imported into `/mat`, as its Material. A prim gets it in place of the material bound to it or to its nearest parent, and of every material bound below it. The old material is removed from the scene when nothing else uses it. A prim with no material imports nothing and says why.
