# Asset editing: requirements

What editing assets in the grid and sidebar must do. The engine is `core/library.py`, `core/category.py`,
`core/sidebar_model.py`, `core/gradient_library.py`, `core/code_library.py` and the choices in
`core/tile_icons.py`, run from `sections/base.py`, the drop in `pane/sidebar.py` and Customize in
`pane/assets.py`. A delete applied whole or not at all is LS-02; merging with other sessions is LS-03
and LS-13; folders and the trash are LS-36 and LS-39; stars are LS-31. The levels and the rules for
tests are in the [README](README.md).

## Severe

- ED-10 Severe: An edit, star, icon or delete acts on exactly the tiles chosen, found by id, even when rows moved or went away since it was asked.

## Wrong output

- ED-20 Wrong output: A rename to a blank or unchanged name changes nothing.
- ED-21 Wrong output: Tags keep their order, with no blanks or repeats, and no tags is an empty list; Customize on one tile replaces its tags (empty clears them), on several it adds to each tile's own.
- ED-22 Wrong output: An asset has one category; a name with a comma stays whole; a field left mixed over a selection keeps each asset's own value.
- ED-23 Wrong output: Renaming a category changes only its name. Its assets, colour and place stay. Renaming it to a name already used in the section joins the two.
- ED-24 Wrong output: Removing a category takes it off every asset and drops its colour; the assets stay.
- ED-25 Wrong output: The sidebar keeps the order the user dragged or sorted, after a reload too; All stays first; Sort by Name sorts by the name shown; a move the library refuses is put back.
- ED-26 Wrong output: A category's colour is kept with the library and shows on every tile in it.
- ED-27 Wrong output: A tile's face is stored in its database only, never as a file and never over its picture, and is kept after a reload; a choice that cannot be read is no choice.
- ED-28 Wrong output: Customize writes one save for the whole selection; OK after Apply writes only what changed since Apply.
- ED-29 Wrong output: An edit the library refuses is not shown as done: the tile keeps its old value and the user is told.
- ED-30 Wrong output: The shipped snippets and palettes are added once per library, and only when the library takes them.
- ED-31 Wrong output: Add and Rename for categories, New Folder and Save Scene ask for a name in a small window. OK or Return uses the name typed, and an empty name is allowed. Cancel, Esc or closing the window does nothing.
- ED-32 Wrong output: Amaze never makes two categories with the same name in a section; names that differ only in capitals count as the same. Adding, saving and importing use the existing category of that name.
- ED-33 Wrong output: When a sync brings in two categories with the same name, or one category renamed two ways, Amaze asks once: change to one name, or keep both. Keep Both renames the second one, for example to Wood 2. Esc changes nothing, and Amaze asks again next time.
- ED-34 Wrong output: Interpolation sets every key of a palette's stored ramp to the curve picked, in one save; its colours and key positions stay. The menu checks the palette's own curve, none when the curves are mixed.
