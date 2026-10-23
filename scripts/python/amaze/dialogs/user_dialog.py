"""The User list's rows: each user A to Z, then the create row."""

from __future__ import annotations

CREATE = "\x00create"    # the create row's itemData: never a name and never a UID


def fill_users(combo, known: dict) -> None:
    """Every user by name, A to Z, each carrying its UID, then the create row last."""
    for user_id, name in sorted(known.items(),
                                key=lambda pair: pair[1].lower()):
        combo.addItem(name, user_id)
    combo.addItem("Create a new user...", CREATE)
