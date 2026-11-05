"""Code editor widget — line-number gutter, syntax, autocomplete, zoom."""

import re

from PyQt6.QtCore import Qt, QRect, QSize, QStringListModel
from PyQt6.QtGui import (
    QColor, QFont, QFontMetrics, QKeyEvent, QPainter, QPalette,
    QTextCursor, QTextFormat,
)
from PyQt6.QtWidgets import (
    QApplication, QCompleter, QPlainTextEdit, QTextEdit, QToolTip, QWidget,
)

_GUTTER_BG = QColor("#F0F0F0")
_GUTTER_FG = QColor("#888888")
_CURRENT_LINE_BG = QColor("#FFFFD0")
_EDITOR_BG = QColor("#FFFFFF")
_EDITOR_FG = QColor("#000000")

_MIN_FONT_SIZE = 6
_MAX_FONT_SIZE = 48

# Module-level singletons — built once per session
_WORD_LIST: list[str] | None = None
_SIGNATURES = None  # lazy Signatures singleton

_OP_RE  = re.compile(r'\b([a-z][a-z0-9_]*)$')   # operator name before (
_VAR_RE = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:=')  # assignment target


def _get_signatures():
    global _SIGNATURES
    if _SIGNATURES is None:
        try:
            from .hdev_core import Signatures, halcon_root
            _SIGNATURES = Signatures(halcon_root())
        except Exception:
            pass
    return _SIGNATURES


def _build_word_list() -> list[str]:
    """Keywords + all HALCON operator names from the installed docs."""
    global _WORD_LIST
    if _WORD_LIST is not None:
        return _WORD_LIST
    from .highlighter import KEYWORDS as KW
    words: set[str] = set(KW)
    try:
        from .hdev_core import halcon_root
        root = halcon_root()
        if root:
            op_dir = root / 'doc/html/reference/operators'
            if op_dir.is_dir():
                # Just the file stems — no file reads needed
                words.update(p.stem for p in op_dir.glob('*.html'))
    except Exception:
        pass
    _WORD_LIST = sorted(words)
    return _WORD_LIST


# ---------------------------------------------------------------------------

class _LineNumberArea(QWidget):
    def __init__(self, editor: "CodeEditor") -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self._editor.line_number_width(), 0)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        self._editor.paint_line_numbers(event)


class CodeEditor(QPlainTextEdit):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._gutter = _LineNumberArea(self)

        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Base, _EDITOR_BG)
        palette.setColor(QPalette.ColorRole.Text, _EDITOR_FG)
        self.setPalette(palette)

        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        self.blockCountChanged.connect(self._update_gutter_width)
        self.updateRequest.connect(self._update_gutter)
        self.cursorPositionChanged.connect(self._highlight_current_line)
        self.cursorPositionChanged.connect(self._on_cursor_for_hint)

        self._update_gutter_width(0)
        self._highlight_current_line()

        self._completer: QCompleter | None = None
        self._completer_model: QStringListModel | None = None
        self._last_vars: set[str] = set()
        self._hint_line: int = -1

        self._init_completer()

    # ------------------------------------------------------------------
    # Public

    def setFont(self, font: QFont) -> None:
        super().setFont(font)
        tab_w = QFontMetrics(font).horizontalAdvance(" ") * 4
        self.setTabStopDistance(float(tab_w))
        self._update_gutter_width(0)

    def line_number_width(self) -> int:
        digits = max(1, len(str(self.blockCount())))
        return 8 + self.fontMetrics().horizontalAdvance("9") * digits

    # ------------------------------------------------------------------
    # Gutter

    def _update_gutter_width(self, _) -> None:
        self.setViewportMargins(self.line_number_width(), 0, 0, 0)

    def _update_gutter(self, rect: QRect, dy: int) -> None:
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_gutter_width(0)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._gutter.setGeometry(
            QRect(cr.left(), cr.top(), self.line_number_width(), cr.height())
        )

    def paint_line_numbers(self, event) -> None:
        painter = QPainter(self._gutter)
        painter.fillRect(event.rect(), _GUTTER_BG)
        painter.setFont(self.font())

        block = self.firstVisibleBlock()
        num = block.blockNumber()
        top = round(
            self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        )
        bottom = top + round(self.blockBoundingRect(block).height())
        h = self.fontMetrics().height()

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(_GUTTER_FG)
                painter.drawText(
                    0, top, self._gutter.width() - 4, h,
                    Qt.AlignmentFlag.AlignRight, str(num + 1),
                )
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            num += 1

    # ------------------------------------------------------------------
    # Current-line highlight

    def _highlight_current_line(self) -> None:
        selections = []
        if not self.isReadOnly():
            sel = QTextEdit.ExtraSelection()
            sel.format.setBackground(_CURRENT_LINE_BG)
            sel.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            sel.cursor = self.textCursor()
            sel.cursor.clearSelection()
            selections.append(sel)
        self.setExtraSelections(selections)

    # ------------------------------------------------------------------
    # Keyboard handling

    def keyPressEvent(self, event: QKeyEvent) -> None:
        # Let completer consume navigation keys when popup is visible
        if self._completer and self._completer.popup().isVisible():
            if event.key() in (
                Qt.Key.Key_Enter, Qt.Key.Key_Return,
                Qt.Key.Key_Escape, Qt.Key.Key_Tab, Qt.Key.Key_Backtab,
            ):
                event.ignore()
                return

        is_enter = event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)

        if is_enter:
            line = self.textCursor().block().text()
            indent = " " * (len(line) - len(line.lstrip()))
            super().keyPressEvent(event)
            self.textCursor().insertText(indent)
            if self._completer:
                self._completer.popup().hide()
            return

        super().keyPressEvent(event)

        ch = event.text()

        # Parameter hint on (
        if ch == '(':
            self._try_show_param_hint()

        # Update / hide completer
        if self._completer:
            ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            if ctrl or event.key() == Qt.Key.Key_Escape or not ch:
                self._completer.popup().hide()
                if event.key() == Qt.Key.Key_Escape:
                    QToolTip.hideText()
            else:
                self._update_completer()

    # ------------------------------------------------------------------
    # Autocomplete

    def _init_completer(self) -> None:
        words = _build_word_list()
        if not words:
            return
        self._completer_model = QStringListModel(words, self)
        self._completer = QCompleter(self._completer_model, self)
        self._completer.setWidget(self)
        self._completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.activated.connect(self._insert_completion)

    def _extract_variables(self) -> list[str]:
        """Scan this editor for variable names on the left of :=."""
        vars_: set[str] = set()
        for line in self.toPlainText().split('\n'):
            m = _VAR_RE.match(line)
            if m:
                vars_.add(m.group(1))
        return sorted(vars_)

    def _word_under_cursor(self) -> str:
        tc = self.textCursor()
        tc.select(QTextCursor.SelectionType.WordUnderCursor)
        return tc.selectedText()

    def _update_completer(self) -> None:
        if not self._completer or not self._completer_model:
            return

        tc = self.textCursor()
        line_text = tc.block().text()
        col = tc.columnNumber()

        # Don't complete inside comment lines
        if line_text.lstrip().startswith("*"):
            self._completer.popup().hide()
            return

        # Don't complete inside string literals
        if line_text[:col].count("'") % 2 == 1:
            self._completer.popup().hide()
            return

        prefix = self._word_under_cursor()
        if len(prefix) < 2 or not prefix[0].isalpha():
            self._completer.popup().hide()
            return

        # Merge static words + current document variables (only rebuild when changed)
        vars_ = set(self._extract_variables())
        if vars_ != self._last_vars:
            self._last_vars = vars_
            base = _build_word_list()
            merged = sorted(set(base) | vars_)
            self._completer_model.setStringList(merged)

        if prefix != self._completer.completionPrefix():
            self._completer.setCompletionPrefix(prefix)
            self._completer.popup().setCurrentIndex(
                self._completer.completionModel().index(0, 0)
            )

        if self._completer.completionCount() == 0:
            self._completer.popup().hide()
            return

        cr = self.cursorRect()
        popup = self._completer.popup()
        cr.setWidth(
            popup.sizeHintForColumn(0)
            + popup.verticalScrollBar().sizeHint().width()
            + 4
        )
        self._completer.complete(cr)

    def _insert_completion(self, completion: str) -> None:
        tc = self.textCursor()
        tc.select(QTextCursor.SelectionType.WordUnderCursor)
        tc.insertText(completion)
        self.setTextCursor(tc)

    # ------------------------------------------------------------------
    # Parameter hints

    def _try_show_param_hint(self) -> None:
        sigs = _get_signatures()
        if not sigs:
            return
        tc = self.textCursor()
        # Text before the ( on this line
        before = tc.block().text()[:tc.columnNumber() - 1].rstrip()
        m = _OP_RE.search(before)
        if not m:
            return
        name = m.group(1)
        groups = sigs.get(name)
        sigs.save()
        if not groups or all(not g for g in groups):
            return

        def _fmt(lst: list[str]) -> str:
            if not lst:
                return "—"
            if len(lst) > 6:
                return ", ".join(lst[:6]) + ", …"
            return ", ".join(lst)

        lines = [
            f"  in  iconic : {_fmt(groups[0])}",
            f"  out iconic : {_fmt(groups[1])}",
            f"  in  ctrl   : {_fmt(groups[2])}",
            f"  out ctrl   : {_fmt(groups[3])}",
        ]
        hint = f"{name}(\n" + "\n".join(lines) + "\n)"
        cr = self.cursorRect()
        pos = self.viewport().mapToGlobal(cr.bottomLeft())
        QToolTip.showText(pos, hint, self)
        self._hint_line = tc.blockNumber()

    def _on_cursor_for_hint(self) -> None:
        if self._hint_line >= 0:
            if self.textCursor().blockNumber() != self._hint_line:
                QToolTip.hideText()
                self._hint_line = -1

    # ------------------------------------------------------------------
    # Ctrl+scroll font zoom

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta != 0:
                self._change_font_size(1 if delta > 0 else -1)
            event.accept()
            return
        super().wheelEvent(event)

    def _change_font_size(self, delta: int) -> None:
        font = self.font()
        new_size = max(_MIN_FONT_SIZE, min(_MAX_FONT_SIZE, font.pointSize() + delta))
        if new_size != font.pointSize():
            font.setPointSize(new_size)
            self.setFont(font)

    # ------------------------------------------------------------------
    # Context menu

    def contextMenuEvent(self, event) -> None:  # type: ignore[override]
        menu = self.createStandardContextMenu()
        menu.addSeparator()
        menu.addAction("Activate Lines\tF3",
                       lambda: self.toggle_comment_lines(activate=True))
        menu.addAction("Deactivate Lines\tF4",
                       lambda: self.toggle_comment_lines(activate=False))
        menu.exec(event.globalPos())

    # ------------------------------------------------------------------
    # Activate / Deactivate lines

    def toggle_comment_lines(self, activate: bool) -> None:
        """Remove (*) leading star to activate lines, or add it to deactivate."""
        cursor = self.textCursor()
        start = cursor.selectionStart()
        end = cursor.selectionEnd()

        doc = self.document()
        b_start = doc.findBlock(start)
        b_end_pos = end if end == start else end - 1
        b_end = doc.findBlock(b_end_pos)

        cursor.beginEditBlock()
        block = b_start
        while block.isValid():
            tc = QTextCursor(block)
            text = block.text()
            if activate:
                if text.startswith("*"):
                    tc.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                    tc.deleteChar()
            else:
                if not text.startswith("*"):
                    tc.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                    tc.insertText("*")
            if block == b_end:
                break
            block = block.next()
        cursor.endEditBlock()
