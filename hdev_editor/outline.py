"""Procedure outline panel."""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget


class OutlinePanel(QWidget):
    procedure_clicked = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Procedure", "Lines", "Parameters"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.itemClicked.connect(self._on_click)
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
