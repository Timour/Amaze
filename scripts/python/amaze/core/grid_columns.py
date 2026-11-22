"""The Grid's columns in their order; the models fill them through `grid_engine`. ▸p/list-columns"""

from __future__ import annotations

COLUMNS = (    #: the column order, defined only here: (key, header label); an empty label has no heading
    ("thumb", ""),
    ("name", "Name"),
    ("type", "Type"),
    ("category", "Category"),
    ("favorite", "Favorite"),
    ("version", "Version"),
    ("open", "Open"),
    ("comments", "Comments"),
    ("tags", "Tags"),
    ("license", "License"),
    ("date", "Date"),
    ("id", "ID"),
)

KEYS = tuple(key for key, _label in COLUMNS)
LABELS = tuple(label for _key, label in COLUMNS)


def selected_rows(selection) -> list:
    """The grid selection as ONE index per row, at column 0; every caller reads the selection here."""
    if selection is None:
        return []
    return [index for index in selection.selectedIndexes()
            if index.column() == 0]


def live_current_index(view):
    """A view's or selection model's current index, rebuilt from its model, or None. ▸r/model-contracts"""
    if view is None:
        return None
    model = view.model()
    if model is None:
        return None
    index = view.currentIndex()
    if not index.isValid():
        return None
    if index.model() is not model:   # it may come from a replaced model; never map it through the current proxy
        return None
    parent = index.parent()    # a tree row keeps its parent: the same row number elsewhere is another row
    try:
        rows = model.rowCount(parent)   # ROW ONLY: a list model's columnCount is private ▸r/model-contracts
    except TypeError:
        return None                  # another signature; "no selection" is the caller's safe fallback
    if index.row() >= rows:
        return None
    return model.index(index.row(), 0, parent)   # COLUMN 0, not the clicked cell ▸r/row-selection
