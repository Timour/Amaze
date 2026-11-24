# Node menu: requirements

What the Amaze submenu of Houdini's node right-click menu must do: Convert to, Convert and Swap to,
and Save. The engine is `utils/rc_calls.py` and `OPmenu.xml`. The copy is built by material
conversion (MC); Save is the save of SL. The levels and the rules for tests are in the [README](README.md).

## Severe

- NM-01 Severe: A swap deletes the old node only after its copy is built whole with its surface wired; when the copy fails at any step, the old node stays as it was.
- NM-02 Severe: One undo after a convert or a swap puts the scene back as it was: every old node with its name, place and wires, and no copy left.
- NM-03 Severe: A broken install or a missing plugin never breaks the right-click menu: an item that cannot run is hidden, and running one never stops Houdini.

## Wrong output

- NM-20 Wrong output: Convert to and Swap to a renderer are offered only for a material with a route to it in this Houdini, never for the renderer it already is.
- NM-21 Wrong output: Convert builds the copy beside the source, named `<name>_<renderer>`, clear of other nodes, current and selected; the source is unchanged.
- NM-22 Wrong output: Swap puts the copy at the old node's exact name, path and position, so every reference by path reaches it.
- NM-23 Wrong output: A right-click on a selected node acts on the nodes selected in the network shown; on any other node, on that node alone.
- NM-24 Wrong output: Each command is one undo step, named after it.
- NM-25 Wrong output: A node that cannot be converted is skipped with its reason and the rest still convert; one dialog names each skipped node and each copy's report; a clean result is one status line.
- NM-26 Wrong output: Save opens the panel's save for the right-clicked node; with no Amaze panel open, nothing changes and the user is told to open one.
