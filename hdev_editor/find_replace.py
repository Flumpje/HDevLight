"""Find / Replace dialog."""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextCursor, QTextDocument
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QVBoxLayout,
)


class FindReplaceDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Find / Replace")
        self.setWindowFlags(
            Qt.WindowType.Tool | Qt.WindowType.WindowCloseButtonHint
        )
        self.setMinimumWidth(430)
        self._editor = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        fr = QHBoxLayout()
        lf = QLabel("Find:")
        lf.setFixedWidth(60)
        fr.addWidget(lf)
        self._find_edit = QLineEdit()
        self._find_edit.returnPressed.connect(self.find_next)
        fr.addWidget(self._find_edit)
        layout.addLayout(fr)

        rr = QHBoxLayout()
        lr = QLabel("Replace:")
        lr.setFixedWidth(60)
        rr.addWidget(lr)
        self._replace_edit = QLineEdit()
        rr.addWidget(self._replace_edit)
        layout.addLayout(rr)

        opts = QHBoxLayout()
        self._case_cb = QCheckBox("Case sensitive")
        self._whole_cb = QCheckBox("Whole words")
        opts.addWidget(self._case_cb)
        opts.addWidget(self._whole_cb)
        opts.addStretch()
        layout.addLayout(opts)

        btns = QHBoxLayout()
        for label, slot in (
            ("Find Next",   self.find_next),
            ("Find Prev",   self.find_prev),
            ("Replace",     self.replace_one),
            ("Replace All", self.replace_all),
            ("Close",       self.hide),
        ):
            b = QPushButton(label)
            b.clicked.connect(slot)
            btns.addWidget(b)
        layout.addLayout(btns)

        self._status = QLabel("")
        layout.addWidget(self._status)

    # ------------------------------------------------------------------
    def set_editor(self, editor) -> None:
        self._editor = editor
        self._status.setText("")

    def set_search_text(self, text: str) -> None:
        self._find_edit.setText(text)
        self._find_edit.selectAll()

    # ------------------------------------------------------------------
    def _flags(self, backward: bool = False) -> QTextDocument.FindFlag:
        f = QTextDocument.FindFlag(0)
        if self._case_cb.isChecked():
            f |= QTextDocument.FindFlag.FindCaseSensitively
        if self._whole_cb.isChecked():
            f |= QTextDocument.FindFlag.FindWholeWords
        if backward:
            f |= QTextDocument.FindFlag.FindBackward
        return f

    def _do_find(self, backward: bool = False) -> bool:
        if not self._editor:
            return False
        text = self._find_edit.text()
        if not text:
            return False
        found = self._editor.find(text, self._flags(backward))
        if not found:
            cur = self._editor.textCursor()
            if backward:
                cur.movePosition(QTextCursor.MoveOperation.End)
            else:
                cur.movePosition(QTextCursor.MoveOperation.Start)
            self._editor.setTextCursor(cur)
            found = self._editor.find(text, self._flags(backward))
        self._status.setText("" if found else "Not found")
        return found

    def find_next(self) -> None:
        self._do_find(backward=False)

    def find_prev(self) -> None:
        self._do_find(backward=True)

    def replace_one(self) -> None:
        if not self._editor:
            return
        cur = self._editor.textCursor()
        if cur.hasSelection():
            find_text = self._find_edit.text()
            sel = cur.selectedText()
            match = (sel == find_text if self._case_cb.isChecked()
                     else sel.lower() == find_text.lower())
            if match:
                cur.insertText(self._replace_edit.text())
        self._do_find(backward=False)

    def replace_all(self) -> None:
        if not self._editor:
            return
        find_text = self._find_edit.text()
        if not find_text:
            return
        replace_text = self._replace_edit.text()
        flags = self._flags()

        doc = self._editor.document()
        search_cur = QTextCursor(doc)
        edit_cur = QTextCursor(doc)
        edit_cur.beginEditBlock()

        count = 0
        while True:
            found = doc.find(find_text, search_cur, flags)
            if found.isNull():
                break
            found.insertText(replace_text)
            search_cur = found
            count += 1

        edit_cur.endEditBlock()
        self._status.setText(
            f"Replaced {count} occurrence(s)" if count else "Not found"
        )
