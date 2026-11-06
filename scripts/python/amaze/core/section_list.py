"""The sections in tab order, key and label, without Houdini. ▸p/dialog-sections-registry-weld"""

SECTIONS = (
    ("material", "Material"),
    ("gradient", "Color"),
    ("cop", "Node"),
    ("code", "Code"),
    ("file", "File"),
)


def keys() -> list:
    """The keys in tab order; stored in settings and library files, so none is ever renamed."""
    return [key for key, _label in SECTIONS]


def label(key: str) -> str:
    """The tab label for `key`; an unlisted key raises, since every section class is in the list."""
    return dict(SECTIONS)[key]
