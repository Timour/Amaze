"""VEX syntax colouring for the Code tile preview."""

import re

from PySide6 import QtGui

from amaze import amazetheme

_SYNTAX_COLORS = {kind: QtGui.QColor(fallback)    # colours by kind: Houdini's dark scheme ▸r/houdini-code-look
                  for kind, (_name, fallback) in amazetheme.CODE_SYNTAX.items()}
DEFAULT = _SYNTAX_COLORS["plain"]

KEYWORDS = {
    "if", "else", "for", "foreach", "while", "do", "return", "break",
    "continue", "function", "struct", "export", "const", "in",
    "import", "def", "class", "elif", "and", "or", "not",
    "None", "True", "False", "kernel", "__kernel", "__global",
}
TYPES = {
    "int", "float", "vector", "vector2", "vector4", "matrix", "matrix2",
    "matrix3", "string", "void", "array", "dict", "bsdf", "surface",
    "displacement", "light", "shadow", "fog", "material", "shader",
    "char", "double", "bool", "long", "unsigned", "global", "constant",
}

_TOKEN_RE = re.compile(
    r"""
    (?P<comment>//[^\n]*|\#[^\n]*|/\*.*?\*/) |
    (?P<string>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*') |
    (?P<attrib>[vfipsu2349]?@[A-Za-z_][A-Za-z0-9_]*) |
    (?P<number>\b\d+\.?\d*\b) |
    (?P<word>[A-Za-z_][A-Za-z0-9_]*) |
    (?P<other>\s+|.)
    """,
    re.VERBOSE | re.DOTALL,
)

_CALL_RE = re.compile(r"\s*\(")    # `\s` and `str.lstrip` strip the same characters


def _runs(line: str):
    """(start, length, kind, QColor) for ONE line; a word before `(` is a call."""
    for m in _TOKEN_RE.finditer(line):
        kind = m.lastgroup
        if kind == "word":
            text = m.group()
            kind = ("keyword" if text in KEYWORDS else "type" if text in TYPES
                    else "function" if _CALL_RE.match(line, m.end()) else "word")
        yield m.start(), m.end() - m.start(), kind, _SYNTAX_COLORS.get(kind, DEFAULT)


def spans(line: str):
    """(start, length, QColor) runs for ONE line; a word before `(` is a call. ▸p/vex-block-comments"""
    for start, length, _kind, color in _runs(line):
        yield start, length, color
