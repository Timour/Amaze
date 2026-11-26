# Qt model contracts: requirements

What the grid and sidebar models must do so that Houdini does not crash. The engine is `core/grid_engine.py`,
`core/category.py`, `core/sidebar_model.py` and the row changes in `core/library.py`. They write nothing.
The levels and the rules for tests are in the [README](README.md).

## Severe

- QM-10 Severe: No action inserts, removes or moves a row inside a layout change: not a save that brings in another session's rows, an add, a delete, a convert, an import, a drop on a category, or a category rename, removal or sort.
- QM-11 Severe: A change that replaces every row (a switch, a reload, a sort) is one model reset, closed even when the change fails.
- QM-12 Severe: No view uses an index from a model that has since been reset or replaced.
- QM-13 Severe: A closed panel leaves nothing connected to the shared models, and nothing it scheduled runs after it is gone.
- QM-14 Severe: A sort never moves a row's data to another row, even when the grid's row lists are out of step.
- QM-15 Severe: The Amaze QML pane is built on Houdini's main thread, and closing it deletes the pane, its view, its state and its engine.
- QM-16 Wrong output: Qt's tree acts once on a click on a sidebar row: no view of the QML pane scrolls by dragging.
