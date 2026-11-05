"""Main application window."""

import contextlib
import io
import tempfile
from pathlib import Path

from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QAction, QFont, QKeySequence
from PyQt6.QtWidgets import (
    QDockWidget, QFileDialog, QFrame, QInputDialog, QLabel,
    QMainWindow, QMessageBox, QStatusBar, QTabWidget, QWidget,
)

from .checker_panel import CheckerPanel
from .document import HdevDocument
from .editor import CodeEditor
from .find_replace import FindReplaceDialog
from .highlighter import HalconHighlighter
from .hdev_core import cmd_check as _hdev_check
from .outline import OutlinePanel

_EDITOR_FONT = QFont("Courier New", 10)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.document: HdevDocument | None = None
        self.editors: dict[str, CodeEditor] = {}
        self._find_replace_dlg: FindReplaceDialog | None = None

        _EDITOR_FONT.setStyleHint(QFont.StyleHint.Monospace)

        self._build_ui()
        self._build_menus()
        self._build_toolbar()
        self._restore_settings()

        self.setAcceptDrops(True)

    # ------------------------------------------------------------------
    # UI construction

    def _build_ui(self) -> None:
        self.setWindowTitle("HDevLight")
        self.resize(1280, 760)
        self.setWindowModified(False)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(False)
        self.tabs.setDocumentMode(True)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.setCentralWidget(self.tabs)

        self.outline = OutlinePanel()
        self.outline.procedure_clicked.connect(self._goto_procedure)
        self.outline.add_procedure_requested.connect(self._add_procedure)
        dock_left = QDockWidget("Procedures", self)
        dock_left.setWidget(self.outline)
        dock_left.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock_left)

        self.checker = CheckerPanel()
        self.checker.run_requested.connect(self._run_checker)
        self._checker_dock = QDockWidget("Checker", self)
        self._checker_dock.setWidget(self.checker)
        self._checker_dock.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._checker_dock)

        self.resizeDocks([dock_left], [220], Qt.Orientation.Horizontal)
        self.resizeDocks([self._checker_dock], [200], Qt.Orientation.Vertical)

        sb = QStatusBar()
        self.setStatusBar(sb)
        self._cursor_label = QLabel("Ln 1, Col 1")
        self._cursor_label.setFrameStyle(QFrame.Shape.StyledPanel.value)
        self._cursor_label.setMinimumWidth(100)
        sb.addPermanentWidget(self._cursor_label)

    def _build_menus(self) -> None:
        mb = self.menuBar()
        mb.setStyleSheet("""
            QMenuBar {
                background: #E87722;
                color: white;
                font-weight: bold;
                padding: 1px 2px;
            }
            QMenuBar::item {
                background: transparent;
                padding: 4px 10px;
                border-radius: 3px;
            }
            QMenuBar::item:selected {
                background: rgba(255,255,255,0.22);
            }
            QMenuBar::item:pressed {
                background: rgba(0,0,0,0.12);
            }
        """)

        # File
        fm = mb.addMenu("&File")
        self._add_action(fm, "&Open…", QKeySequence.StandardKey.Open, self.open_dialog)
        fm.addSeparator()
        self.act_save = self._add_action(
            fm, "&Save", QKeySequence.StandardKey.Save, self.save)
        self.act_save.setEnabled(False)
        self._add_action(fm, "Save &As…", QKeySequence.StandardKey.SaveAs, self.save_as)
        fm.addSeparator()
        self.recent_menu = fm.addMenu("Recent Files")
        fm.addSeparator()
        self._add_action(fm, "E&xit", QKeySequence.StandardKey.Quit, self.close)

        # Edit (delegates to active editor)
        em = mb.addMenu("&Edit")
        self._add_action(em, "&Undo",  QKeySequence.StandardKey.Undo,  self._undo)
        self._add_action(em, "&Redo",  QKeySequence.StandardKey.Redo,  self._redo)
        em.addSeparator()
        self._add_action(em, "Cu&t",   QKeySequence.StandardKey.Cut,   self._cut)
        self._add_action(em, "&Copy",  QKeySequence.StandardKey.Copy,  self._copy)
        self._add_action(em, "&Paste", QKeySequence.StandardKey.Paste, self._paste)
        em.addSeparator()
        self._add_action(em, "Select &All",
                         QKeySequence.StandardKey.SelectAll, self._select_all)
        em.addSeparator()
        self._add_action(em, "A&ctivate Lines",   "F3", self._activate_lines)
        self._add_action(em, "&Deactivate Lines", "F4", self._deactivate_lines)
        em.addSeparator()
        self._add_action(em, "&Find / Replace…", "Ctrl+F", self._show_find_replace)
        self._add_action(em, "&Go to Line…",     "Alt+G",  self._goto_line)

        # Tools
        tm = mb.addMenu("&Tools")
        act_check = self._add_action(tm, "&Run Checker", "F5", self._run_checker)
        act_check.setEnabled(True)

    def _build_toolbar(self) -> None:
        pass

    @staticmethod
    def _add_action(menu, label: str, shortcut, slot) -> QAction:
        a = QAction(label, menu.parent() if hasattr(menu, "parent") else None)
        if isinstance(shortcut, QKeySequence.StandardKey):
            a.setShortcut(QKeySequence(shortcut))
        else:
            a.setShortcut(shortcut)
        a.triggered.connect(slot)
        menu.addAction(a)
        return a

    # ------------------------------------------------------------------
    # Settings

    def _restore_settings(self) -> None:
        self._settings = QSettings("Siga", "HDevLight")
        geom = self._settings.value("geometry")
        if geom:
            self.restoreGeometry(geom)
        state = self._settings.value("windowState")
        if state:
            self.restoreState(state)
        self._refresh_recent_menu()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._confirm_unsaved():
            self._settings.setValue("geometry", self.saveGeometry())
            self._settings.setValue("windowState", self.saveState())
            event.accept()
        else:
            event.ignore()

    # ------------------------------------------------------------------
    # Drag-and-drop

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if any(u.toLocalFile().lower().endswith((".hdev", ".hdvp")) for u in urls):
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event) -> None:  # type: ignore[override]
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.suffix.lower() in (".hdev", ".hdvp") and path.is_file():
                if not self._confirm_unsaved():
                    return
                self.open_file(path)
                return
        event.ignore()

    # ------------------------------------------------------------------
    # File operations

    def _confirm_unsaved(self) -> bool:
        if not (self.document and self._any_modified()):
            return True
        reply = QMessageBox.question(
            self, "Unsaved Changes", "Save changes before closing?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Save:
            return self.save()
        return reply != QMessageBox.StandardButton.Cancel

    def open_dialog(self) -> None:
        if not self._confirm_unsaved():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open HDevelop File", "",
            "HDevelop Files (*.hdev *.hdvp);;All Files (*)",
        )
        if path:
            self.open_file(Path(path))

    def open_file(self, path: Path) -> None:
        try:
            doc = HdevDocument(path)
        except Exception as exc:
            QMessageBox.critical(self, "Open Error", str(exc))
            return
        self.document = doc
        self._populate_tabs()
        self.outline.set_procedures(doc.procedures)
        self.setWindowTitle(f"HDevLight — {path.name}[*]")
        self.setWindowModified(False)
        self.act_save.setEnabled(True)
        self._add_recent(str(path))
        self.statusBar().showMessage(f"Opened  {path}")

    def _populate_tabs(self) -> None:
        self.tabs.clear()
        self.editors.clear()
        for proc in self.document.procedures:
            editor = CodeEditor()
            editor.setFont(_EDITOR_FONT)
            editor._hl = HalconHighlighter(editor.document())  # keep ref or GC kills it
            editor.setPlainText(self.document.procedure_text(proc.name))
            editor.document().setModified(False)
            proc_name = proc.name  # capture for lambda
            editor.document().modificationChanged.connect(
                lambda mod, pn=proc_name: self._on_modified(pn, mod)
            )
            editor.cursorPositionChanged.connect(self._update_cursor_position)
            self.editors[proc.name] = editor
            self.tabs.addTab(editor, proc.name)
        self._update_cursor_position()

    def _on_modified(self, proc_name: str, modified: bool) -> None:
        keys = list(self.editors.keys())
        if proc_name in keys:
            idx = keys.index(proc_name)
            self.tabs.setTabText(idx, proc_name + (" *" if modified else ""))
        self.setWindowModified(self._any_modified())

    def _any_modified(self) -> bool:
        return any(e.document().isModified() for e in self.editors.values())

    def save(self) -> bool:
        if not self.document:
            return True
        self._flush_edits()
        try:
            self.document.save()
        except Exception as exc:
            QMessageBox.critical(self, "Save Error", str(exc))
            return False
        for editor in self.editors.values():
            editor.document().setModified(False)
        self.setWindowModified(False)
        self.statusBar().showMessage("Saved")
        return True

    def save_as(self) -> None:
        if not self.document:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save As", str(self.document.path),
            "HDevelop Files (*.hdev *.hdvp);;All Files (*)",
        )
        if not path:
            return
        self._flush_edits()
        try:
            self.document.save(Path(path))
        except Exception as exc:
            QMessageBox.critical(self, "Save Error", str(exc))
            return
        self.setWindowTitle(f"HDevLight — {Path(path).name}[*]")
        self.setWindowModified(False)
        for editor in self.editors.values():
            editor.document().setModified(False)
        self._add_recent(path)
        self.statusBar().showMessage(f"Saved as  {path}")

    def _flush_edits(self) -> None:
        for proc_name, editor in self.editors.items():
            if editor.document().isModified():
                self.document.set_procedure_text(proc_name, editor.toPlainText())

    # ------------------------------------------------------------------
    # Checker

    def _run_checker(self) -> None:
        if not self.document:
            self.checker.show_output("No file open.")
            self._checker_dock.show()
            self._checker_dock.raise_()
            return

        self._flush_edits()

        with tempfile.NamedTemporaryFile(
            suffix=".hdev", delete=False, mode="w", encoding="utf-8"
        ) as tf:
            temp_path = Path(tf.name)
            tf.write(self.document._rebuild_xml())

        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                try:
                    import argparse as _ap
                    args = _ap.Namespace(file=str(temp_path), quiet=False)
                    _hdev_check(args)
                except SystemExit:
                    pass
            output = buf.getvalue()
        except Exception as exc:
            output = f"Error running checker: {exc}"
        finally:
            try:
                temp_path.unlink()
            except Exception:
                pass

        output = output.replace(str(temp_path), str(self.document.path))
        self.checker.show_output(output)
        self._checker_dock.show()
        self._checker_dock.raise_()

    # ------------------------------------------------------------------
    # Navigation

    def _goto_procedure(self, proc_name: str) -> None:
        keys = list(self.editors.keys())
        if proc_name in keys:
            self.tabs.setCurrentIndex(keys.index(proc_name))

    def _add_procedure(self) -> None:
        if not self.document:
            QMessageBox.warning(self, "No File", "Open a file first.")
            return
        name, ok = QInputDialog.getText(self, "New Procedure", "Procedure name:")
        if not ok:
            return
        name = name.strip()
        if not name:
            return
        if name in self.editors:
            QMessageBox.warning(self, "Duplicate", f"'{name}' already exists.")
            return
        if not name.isidentifier():
            QMessageBox.warning(
                self, "Invalid Name",
                "Name must start with a letter and contain only letters, digits and underscores."
            )
            return

        self.document.add_procedure(name)

        editor = CodeEditor()
        editor.setFont(_EDITOR_FONT)
        editor._hl = HalconHighlighter(editor.document())
        editor.setPlainText("")
        editor.document().modificationChanged.connect(
            lambda mod, pn=name: self._on_modified(pn, mod)
        )
        editor.cursorPositionChanged.connect(self._update_cursor_position)
        self.editors[name] = editor
        self.tabs.addTab(editor, name)
        editor.document().setModified(True)

        self.outline.set_procedures(self.document.procedures)
        self._goto_procedure(name)
        self.act_save.setEnabled(True)

    def _on_tab_changed(self, _index: int) -> None:
        self._update_cursor_position()
        if self._find_replace_dlg and self._find_replace_dlg.isVisible():
            editor = self._current_editor()
            if editor:
                self._find_replace_dlg.set_editor(editor)

    def _update_cursor_position(self) -> None:
        editor = self._current_editor()
        if editor:
            cur = editor.textCursor()
            self._cursor_label.setText(
                f"Ln {cur.blockNumber() + 1}, Col {cur.columnNumber() + 1}"
            )
        else:
            self._cursor_label.setText("")

    # ------------------------------------------------------------------
    # Edit actions

    def _activate_lines(self) -> None:
        if e := self._current_editor():
            e.toggle_comment_lines(activate=True)

    def _deactivate_lines(self) -> None:
        if e := self._current_editor():
            e.toggle_comment_lines(activate=False)

    def _goto_line(self) -> None:
        editor = self._current_editor()
        if not editor:
            return
        max_line = editor.document().blockCount()
        line, ok = QInputDialog.getInt(
            self, "Go to Line", f"Line number (1 – {max_line}):",
            value=editor.textCursor().blockNumber() + 1,
            min=1, max=max_line,
        )
        if ok:
            block = editor.document().findBlockByNumber(line - 1)
            cur = editor.textCursor()
            cur.setPosition(block.position())
            editor.setTextCursor(cur)
            editor.centerCursor()
            editor.setFocus()

    def _show_find_replace(self) -> None:
        if self._find_replace_dlg is None:
            self._find_replace_dlg = FindReplaceDialog(self)
        editor = self._current_editor()
        if editor:
            self._find_replace_dlg.set_editor(editor)
            sel = editor.textCursor().selectedText()
            if sel and "\n" not in sel:
                self._find_replace_dlg.set_search_text(sel)
        self._find_replace_dlg.show()
        self._find_replace_dlg.raise_()
        self._find_replace_dlg.activateWindow()

    # ------------------------------------------------------------------
    # Edit delegates

    def _current_editor(self) -> CodeEditor | None:
        w = self.tabs.currentWidget()
        return w if isinstance(w, CodeEditor) else None

    def _undo(self):
        if e := self._current_editor():
            e.undo()

    def _redo(self):
        if e := self._current_editor():
            e.redo()

    def _cut(self):
        if e := self._current_editor():
            e.cut()

    def _copy(self):
        if e := self._current_editor():
            e.copy()

    def _paste(self):
        if e := self._current_editor():
            e.paste()

    def _select_all(self):
        if e := self._current_editor():
            e.selectAll()

    # ------------------------------------------------------------------
    # Recent files

    def _add_recent(self, path: str) -> None:
        recents: list = self._settings.value("recentFiles", []) or []
        if path in recents:
            recents.remove(path)
        recents.insert(0, path)
        self._settings.setValue("recentFiles", recents[:10])
        self._refresh_recent_menu()

    def _refresh_recent_menu(self) -> None:
        self.recent_menu.clear()
        recents: list = self._settings.value("recentFiles", []) or []
        for path in recents:
            a = QAction(Path(path).name, self)
            a.setToolTip(path)
            a.triggered.connect(lambda _checked, p=path: self.open_file(Path(p)))
            self.recent_menu.addAction(a)
        if not recents:
            self.recent_menu.addAction("(empty)").setEnabled(False)
