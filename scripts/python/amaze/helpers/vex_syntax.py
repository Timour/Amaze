"""Shared VEX/C-like syntax colouring - the ONE palette and tokenizer used by both the Code section's tile preview and the editor dialog, so the two always match. Every value below is a named constant, tune freely. ▸p/vex-block-comments"""

import re

from PySide6 import QtGui

BACKGROUND = QtGui.QColor("#000000")    # the palette, a best-effort match of Houdini's own wrangle VEXpression editor
DEFAULT = QtGui.QColor("#d4d4d4")
COMMENT = QtGui.QColor("#6a9955")
STRING = QtGui.QColor("#9cdb6a")   # green, brighter than comments
NUMBER = QtGui.QColor("#d7a35b")   # gold / orange
TYPE = QtGui.QColor("#8f9fff")     # vector / int / float - blue-violet
KEYWORD = QtGui.QColor("#c586d9")  # if / for / return - purple
FUNCTION = QtGui.QColor("#5e9cea") # point / addpoint / addprim - blue
ATTRIB = QtGui.QColor("#56c2b0")   # @P / v@center - teal

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


def spans(line: str):
    """Yield (start, length, QColor) runs for ONE line of code - a word immediately followed by `(` is coloured as a function call, which is how the wrangle editor tells them from plain identifiers. ▸p/vex-block-comments"""
    for m in _TOKEN_RE.finditer(line):
        kind = m.lastgroup
        color = DEFAULT
        if kind == "comment":
            color = COMMENT
        elif kind == "string":
            color = STRING
        elif kind == "attrib":
            color = ATTRIB
        elif kind == "number":
            color = NUMBER
        elif kind == "word":
            text = m.group()
            if text in KEYWORDS:
                color = KEYWORD
            elif text in TYPES:
                color = TYPE
            elif line[m.end():].lstrip().startswith("("):
                color = FUNCTION
            else:
                color = DEFAULT
        else:
            color = DEFAULT
        yield m.start(), len(m.group()), color


def open_comment_at(line: str):
    """Index of a `/*` on `line` that is still OPEN at its end, else None - a `/*` inside a string or an already-closed comment is not one. ▸p/vex-block-comments"""
    masked = set()
    for start, length, color in spans(line):
        if color in (STRING, COMMENT):
            masked.update(range(start, start + length))
    found = line.find("/*")
    while found != -1:
        if found not in masked:
            return found
        found = line.find("/*", found + 2)
    return None


class VexHighlighter(QtGui.QSyntaxHighlighter):
    """Applies the shared palette to a QPlainTextEdit - `spans` sees ONE line, so a `/*` block spanning lines is carried across on the block state. ▸p/vex-block-comments"""

    IN_BLOCK_COMMENT = 1

    def _paint(self, start: int, length: int, color) -> None:
        fmt = QtGui.QTextCharFormat()
        fmt.setForeground(color)
        self.setFormat(start, length, fmt)

    def highlightBlock(self, text: str) -> None:
        offset = 0
        if self.previousBlockState() == self.IN_BLOCK_COMMENT:
            closed = text.find("*/")
            if closed == -1:
                self._paint(0, len(text), COMMENT)
                self.setCurrentBlockState(self.IN_BLOCK_COMMENT)
                return
            offset = closed + 2
            self._paint(0, offset, COMMENT)
        self.setCurrentBlockState(0)

        rest = text[offset:]
        opened = open_comment_at(rest)
        if opened is not None:
            self._paint(offset + opened, len(rest) - opened, COMMENT)
            rest = rest[:opened]
            self.setCurrentBlockState(self.IN_BLOCK_COMMENT)
        for start, length, color in spans(rest):
            self._paint(offset + start, length, color)
