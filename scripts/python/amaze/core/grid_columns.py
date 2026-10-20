"""The Grid's COLUMNS, the one order; the models answer them through `grid_engine`. ▸p/list-columns"""

from __future__ import annotations

COLUMNS = (    #: THE COLUMN ORDER, once: (key, header label); an empty label has no heading
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
    """The grid selection as ONE index per row, at column 0 - every reader comes through here."""
    if selection is None:
        return []
    return [index for index in selection.selectedIndexes()
            if index.column() == 0]
