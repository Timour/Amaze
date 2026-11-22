"""The User list's rows: each user A to Z, then the create row."""

from __future__ import annotations

CREATE = "\x00create"    # the create row's value: never a name and never a UID
CREATE_TEXT = "Create a new user..."
DEFAULT_NAME = "Amaze User"    # the user a library with nobody in it starts with


def user_rows(known: dict) -> list:
    """(name, UID) for every user by name, A to Z, then the create row last."""
    rows = sorted(((name, user_id) for user_id, name in known.items()),
                  key=lambda pair: pair[0].lower())
    return rows + [(CREATE_TEXT, CREATE)]
