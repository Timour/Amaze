"""Names as a sentence joins them, or as USD accepts them; every layer can use it."""

import re


def and_list(words) -> str:
    """`a`, `a and b`, `a, b and c` - the user's punctuation, one owner for every message."""
    words = list(words)
    if len(words) <= 1:
        return "".join(words)
    return "%s and %s" % (", ".join(words[:-1]), words[-1])


def sanitize_usd_path(path: str) -> str:
    """`path` as a node or USD prim name: other characters become `_`, and a digit may not lead."""
    clean = re.sub("[^a-zA-Z0-9]", "_", path)
    if clean and clean[0].isdigit():
        clean = "_" + clean
    return clean
