"""Procedure outline panel."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout, QMenu, QPushButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)


class OutlinePanel(QWidget):
    procedure_clicked = pyqtSignal(str)
    add_procedure_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Thin button strip at the top
        bar = QWidget()
        bar.setStyleSheet("QWidget { background: #F5F5F5; border-bottom: 1px solid #CCCCCC; }")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(4, 2, 4, 2)
        bl.addStretch()
        btn = QPushButton("+ New Procedure")
        btn.setStyleSheet("""
            QPushButton {
                background: #E87722; color: white; border: none;
                padding: 2px 8px; border-radius: 3px; font-weight: bold;
            }
            QPushButton:hover { background: #CF6718; }
            QPushButton:pressed { background: #B85A14; }
        """)
        btn.setToolTip("Add a new procedure to this file")
        btn.clicked.connect(self.add_procedure_requested)
        bl.addWidget(btn)
        layout.addWidget(bar)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Procedure", "Lines", "Parameters"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.itemClicked.connect(self._on_click)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self.tree)

    def set_procedures(self, procedures) -> None:
        self.tree.clear()
        for p in procedures:
            active = sum(
                1 for r in p.rows
                if r.kind == "code" and not r.text.strip().startswith("*")
            )
            parts = []
            if p.iface["io"]:
                parts.append("io: " + ", ".join(p.iface["io"]))
            if p.iface["oo"]:
                parts.append("oo: " + ", ".join(p.iface["oo"]))
            if p.iface["ic"]:
                parts.append("ic: " + ", ".join(p.iface["ic"]))
            if p.iface["oc"]:
                parts.append("oc: " + ", ".join(p.iface["oc"]))
            param_str = " | ".join(parts) if parts else "—"

            item = QTreeWidgetItem([p.name, str(active), param_str])
            self.tree.addTopLevelItem(item)

        self.tree.resizeColumnToContents(0)
        self.tree.resizeColumnToContents(1)

    def _on_click(self, item: QTreeWidgetItem, _col: int) -> None:
        self.procedure_clicked.emit(item.text(0))

    def _on_context_menu(self, pos) -> None:
        menu = QMenu(self)
        menu.addAction("New Procedure…", self.add_procedure_requested)
        menu.exec(self.tree.mapToGlobal(pos))
