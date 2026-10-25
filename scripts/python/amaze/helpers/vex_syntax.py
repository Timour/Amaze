"""Shared VEX/C-like syntax colouring - the ONE palette and tokenizer used by both the Code section's tile preview and the editor dialog, so the two always match. Every value below is a named constant, tune freely. ▸p/vex-block-comments"""

import re

from PySide6 import QtGui

from amaze import amazetheme

_INKS = {}


def use_inks(inks: dict) -> None:
    """Paint with `inks` by kind from now on; the panel hands in Houdini's. ▸r/houdini-code-look"""
    global DEFAULT, COMMENT, STRING, NUMBER, TYPE, KEYWORD, FUNCTION, ATTRIB
    _INKS.clear()
    _INKS.update(inks)
    DEFAULT, COMMENT, STRING, NUMBER = (inks[k] for k in ("plain", "comment", "string", "number"))
    TYPE, KEYWORD, FUNCTION, ATTRIB = (inks[k] for k in ("type", "keyword", "function", "attrib"))


use_inks({kind: QtGui.QColor(fallback)    # Houdini's dark scheme, until the panel says otherwise
          for kind, (_name, fallback) in amazetheme.CODE_SYNTAX.items()})

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
        yield m.start(), m.end() - m.start(), kind, _INKS.get(kind, DEFAULT)


def spans(line: str):
    """(start, length, QColor) runs for ONE line; a word before `(` is a call. ▸p/vex-block-comments"""
    for start, length, _kind, color in _runs(line):
        yield start, length, color


def open_comment_at(line: str):
    """Index of a `/*` still OPEN at the end of `line`, else None. ▸p/vex-block-comments"""
    return _open_comment(line, _runs(line))


def _open_comment(line: str, runs):
    """`open_comment_at` over the runs `_runs` already made for `line`: masked by KIND, not ink."""
    masked = set()
    for start, length, kind, _color in runs:
        if kind in ("string", "comment"):
            masked.update(range(start, start + length))
    found = line.find("/*")
    while found != -1:
        if found not in masked:
            return found
        found = line.find("/*", found + 2)
    return None


_FORMATS = {}    # one shared QTextCharFormat per colour, keyed on `rgba()`, built on its first paint


class VexHighlighter(QtGui.QSyntaxHighlighter):
    """Applies the shared palette to a QPlainTextEdit - `spans` sees ONE line, so a `/*` block spanning lines is carried across on the block state. ▸p/vex-block-comments"""

    IN_BLOCK_COMMENT = 1

    def _paint(self, start: int, length: int, color) -> None:
        key = color.rgba()
        fmt = _FORMATS.get(key)
        if fmt is None:
            fmt = QtGui.QTextCharFormat()
            fmt.setForeground(color)
            _FORMATS[key] = fmt
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
        runs = list(_runs(rest))
        opened = _open_comment(rest, runs)
        if opened is not None:
            self._paint(offset + opened, len(rest) - opened, COMMENT)
            runs = [run for run in runs if run[0] < opened]    # no run crosses an open `/*`
            self.setCurrentBlockState(self.IN_BLOCK_COMMENT)
        for start, length, _kind, color in runs:
            self._paint(offset + start, length, color)
