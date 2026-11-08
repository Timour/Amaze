"""Names as a sentence joins them, sizes as a message says them, names as USD accepts them."""

import re


def and_list(words) -> str:
    """`a`, `a and b`, `a, b and c` - the user's punctuation, one owner for every message."""
    words = list(words)
    if len(words) <= 1:
        return "".join(words)
    return "%s and %s" % (", ".join(words[:-1]), words[-1])


def byte_size(count: int) -> str:
    """`16 GB`, `1.5 MB`, `4 KB`, `900 bytes`: a size as a message says it, one decimal at most."""
    for unit, scale in (("GB", 1024 ** 3), ("MB", 1024 ** 2), ("KB", 1024)):
        if count >= scale:
            return "%s %s" % (("%.1f" % (count / scale)).rstrip("0").rstrip("."), unit)
    return "%d bytes" % count


def sanitize_usd_path(path: str) -> str:
    """`path` as a node or USD prim name: other characters become `_`, and a digit may not lead."""
    clean = re.sub("[^a-zA-Z0-9]", "_", path)
    if clean and clean[0].isdigit():
        clean = "_" + clean
    return clean
