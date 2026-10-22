"""Joining names the way a sentence does; it imports nothing, so every layer can use it."""


def and_list(words) -> str:
    """`a`, `a and b`, `a, b and c` - the user's punctuation, one owner for every message."""
    words = list(words)
    if len(words) <= 1:
        return "".join(words)
    return "%s and %s" % (", ".join(words[:-1]), words[-1])
