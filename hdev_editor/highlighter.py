"""HALCON syntax highlighter — colors matched to standard HDevelop."""

from PyQt6.QtCore import QRegularExpression
from PyQt6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat

KEYWORDS = frozenset({
    # Control flow
    "if", "else", "elseif", "endif",
    "for", "to", "by", "downto", "endfor",
    "while", "endwhile", "repeat", "until",
    "try", "catch", "endtry",
    "switch", "case", "default", "endswitch",
    "break", "continue", "return", "exit", "stop",
    "then",
    # Variable / procedure declarations
    "global", "local", "def", "tuple",
    "procedure", "endprocedure",
    # Logical operators
    "and", "or", "not", "xor",
    # Bitwise operators
    "band", "bor", "bxor", "bnot", "lsh", "rsh",
    # Literals
    "true", "false",
})


def _fmt(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(int(QFont.Weight.Bold))
    if italic:
        f.setFontItalic(True)
    return f


class HalconHighlighter(QSyntaxHighlighter):
    """Must be instantiated AFTER QApplication exists; stores all Qt objects in __init__."""

    def __init__(self, document) -> None:
        super().__init__(document)

        # Regexes — built here so QApplication is guaranteed to exist
        self._call_re = QRegularExpression(r"\b[a-z][a-z0-9_]*(?=\s*\()")
        self._kw_re = QRegularExpression(
            r"\b(" + "|".join(sorted(KEYWORDS, key=len, reverse=True)) + r")\b"
        )
        self._str_re = QRegularExpression(r"'[^']*'")

        # Formats — HDevelop palette
        self._comment_fmt = _fmt("#007F00")            # green, plain
        self._call_fmt    = _fmt("#0000FF")            # blue for operators
        self._kw_fmt      = _fmt("#0000FF", bold=True) # blue bold for keywords
        self._str_fmt     = _fmt("#A31515")            # dark red for strings

    def highlightBlock(self, text: str) -> None:
        # Comment line: * is the first non-whitespace character
        if text.lstrip().startswith("*"):
            self.setFormat(0, len(text), self._comment_fmt)
            return

        # Calls first, then keywords overwrite them (so "if (" is blue-bold, not plain blue)
        self._apply(text, self._call_re, self._call_fmt)
        self._apply(text, self._kw_re,   self._kw_fmt)
        # Strings last — overwrite any highlighting inside the quotes
        self._apply(text, self._str_re,  self._str_fmt)

    def _apply(self, text: str, pattern: QRegularExpression, fmt: QTextCharFormat) -> None:
        it = pattern.globalMatch(text)
        while it.hasNext():
            m = it.next()
            self.setFormat(m.capturedStart(), m.capturedLength(), fmt)
