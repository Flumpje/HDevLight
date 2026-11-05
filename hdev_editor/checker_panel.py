"""Checker output panel."""

import re

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPalette, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

_COLORS = {
    "error": "#CC0000",
    "warn":  "#996600",
    "ok":    "#007F00",
    "note":  "#888888",
    "text":  "#000000",
}


def _fmt(color: str) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    return f


class CheckerPanel(QWidget):
    run_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        toolbar = QHBoxLayout()
        self.btn_run = QPushButton("▶  Run Check  (F5)")
        self.btn_run.setFixedWidth(160)
        self.btn_run.clicked.connect(self.run_requested)
        self.lbl_status = QLabel("")
        toolbar.addWidget(self.btn_run)
        toolbar.addWidget(self.lbl_status)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        font = QFont("Consolas", 9)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.output.setFont(font)

        palette = self.output.palette()
        palette.setColor(QPalette.ColorRole.Base, QColor("#FFFFFF"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#000000"))
        self.output.setPalette(palette)
        layout.addWidget(self.output)

    def show_output(self, text: str) -> None:
        self.output.clear()
        cursor = self.output.textCursor()

        fmts = {k: _fmt(v) for k, v in _COLORS.items()}

        for line in text.splitlines():
            stripped = line.strip()
            if any(k in stripped for k in ("XML ERROR", "[arity]", "[block]", "[init]")):
                fmt = fmts["error"]
            elif "note:" in stripped or stripped.startswith("note "):
                fmt = fmts["note"]
            elif "no structural problems" in stripped:
                fmt = fmts["ok"]
            elif re.search(r"\b0 problem\(s\)", stripped):
                fmt = fmts["ok"]
            elif re.search(r"\b[1-9]\d* problem\(s\)", stripped):
                fmt = fmts["warn"]
            else:
                fmt = fmts["text"]

            cursor.insertText(line + "\n", fmt)

        self.output.setTextCursor(cursor)
        self.output.moveCursor(QTextCursor.MoveOperation.Start)

        m = re.search(r"(\d+) problem\(s\)", text)
        if m:
            count = int(m.group(1))
            if count == 0:
                self.lbl_status.setText("✓  No problems")
                self.lbl_status.setStyleSheet(f"color: {_COLORS['ok']};")
            else:
                self.lbl_status.setText(f"⚠  {count} problem(s)")
                self.lbl_status.setStyleSheet(f"color: {_COLORS['warn']};")
        elif "XML ERROR" in text:
            self.lbl_status.setText("✗  XML error")
            self.lbl_status.setStyleSheet(f"color: {_COLORS['error']};")
        else:
            self.lbl_status.setText("")
            self.lbl_status.setStyleSheet("")
