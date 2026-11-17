"""Text helpers for messages: joined lists of names, byte sizes, and names valid in USD."""

import re


def and_list(words) -> str:
    """`a`, `a and b`, `a, b and c` - the list punctuation every message uses, defined only here."""
    words = list(words)
    if len(words) <= 1:
        return "".join(words)
    return "%s and %s" % (", ".join(words[:-1]), words[-1])


def byte_size(count: int) -> str:
    """`16 GB`, `1.5 MB`, `4 KB`, `900 bytes`: a size as messages show it, one decimal at most."""
    for unit, scale in (("GB", 1024 ** 3), ("MB", 1024 ** 2), ("KB", 1024)):
        if count >= scale:
            return "%s %s" % (("%.1f" % (count / scale)).rstrip("0").rstrip("."), unit)
    return "%d bytes" % count


def sanitize_usd_path(path: str, digit_may_lead: bool = False) -> str:
    """`path` as a node or USD prim name: other characters become `_`; a digit leads only if allowed."""
    clean = re.sub("[^a-zA-Z0-9]", "_", path)
    if clean and clean[0].isdigit() and not digit_may_lead:
        clean = "_" + clean
    return clean
