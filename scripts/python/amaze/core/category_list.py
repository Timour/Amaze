"""A category list as data: how a name reads, which names are one category, and adding one."""

import uuid

ALL_NAMES = ("All", "_All")    # the All row, never a category


def display_name(stored) -> str:
    """How a STORED category name reads to the user: a leading underscore is not shown."""
    text = str(stored)
    return text[1:] if text.startswith("_") else text


def is_all(key) -> bool:
    """Whether `key` is the All row, `_All`, or a name that means it, `All`: never a category."""
    return key in ALL_NAMES


def folded(name) -> str:
    """A name as two are compared: as shown, capitals aside (`_WIP`, WIP and wip are one)."""
    return display_name(str(name).strip()).casefold()


def same_name(one, other) -> bool:
    """Whether two names are one category's."""
    return folded(one) == folded(other)


def same_named(names: dict) -> list:
    """The keys of `names`, {key: name} in list order, that share a name: one list for each name."""
    found = {}
    for key, name in names.items():
        found.setdefault(folded(name), []).append(key)
    return [keys for name, keys in found.items() if name and len(keys) > 1]


def free_name(names, name: str) -> str:
    """`name 2`, or with the first number after 2 that no name in `names` has."""
    taken, number = {folded(held) for held in names}, 2
    while folded("%s %d" % (name, number)) in taken:
        number += 1
    return "%s %d" % (name, number)


def new_key() -> str:
    """The id of a new category, made as an asset's is."""
    return uuid.uuid4().hex


def key_named(names: dict, name) -> str:
    """The key in `names`, {key: name} in list order, of the category named `name`; "" for none."""
    name = str(name or "").strip()
    if not name:
        return ""
    exact = [key for key, held in names.items() if str(held or "").strip() == name]
    alike = [key for key, held in names.items() if same_name(held or "", name)]
    return (exact + alike + [""])[0]


def _order(entry: dict) -> int:
    order = entry.get("order")
    return order if isinstance(order, int) and not isinstance(order, bool) else -1


def place(table: dict, name, key: str = "") -> str:
    """The key of category `name` in `table`; added, under `key` or a new one, when it has none."""
    name = str(name or "").strip()
    if key in table:
        return key
    if not name or is_all(name):
        return ""
    entries = {held: entry for held, entry in table.items() if isinstance(entry, dict)}
    listed = sorted(entries, key=lambda held: (_order(entries[held]), held))
    found = key_named({held: entries[held].get("name") for held in listed}, name)
    if found:
        return found
    key = key or new_key()
    last = max([_order(entry) for entry in entries.values()] + [-1])
    table[key] = {"name": name, "order": last + 1}
    return key
