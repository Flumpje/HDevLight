"""Data model for a .hdev file: parse, edit, save."""

import re
from pathlib import Path
from typing import Optional

from .hdev_core import parse, Procedure, Row, KEYWORDS


class HdevDocument:
    """Parsed .hdev file with editable procedure bodies."""

    def __init__(self, path: Path):
        self.path = path
        self._reload()

    def _reload(self):
        self._orig_xml = self.path.read_text(encoding="utf-8", errors="replace")
        self.procedures = parse(self.path)
        self._edits: dict[str, list[tuple[str, str]]] = {}
        self._orig_kinds: dict[str, list[str]] = {
            p.name: [r.kind for r in p.rows]
            for p in self.procedures
        }

    def procedure_text(self, proc_name: str) -> str:
        # Prefer in-memory edits so rebuilt tabs keep unsaved content
        if proc_name in self._edits:
            return "\n".join(line for _, line in self._edits[proc_name])
        for p in self.procedures:
            if p.name == proc_name:
                return "\n".join(r.text for r in p.rows)
        return ""

    def add_procedure(self, name: str) -> None:
        """Append a new empty procedure and update the in-memory model."""
        new_xml = (
            f'\n<procedure name="{name}">\n'
            '<interface>\n<io>\n</io>\n<oo>\n</oo>\n<ic>\n</ic>\n<oc>\n</oc>\n</interface>\n'
            '<body>\n<l></l>\n</body>\n'
            '<docu id="used">\n<short lang="en_US"></short>\n</docu>\n'
            '</procedure>\n'
        )
        self._orig_xml = self._orig_xml.replace('</hdevelop>', new_xml + '</hdevelop>')

        proc = Procedure(name, 0)
        proc.rows = [Row(0, "code", "")]
        self.procedures.append(proc)
        self._orig_kinds[name] = ["code"]

    def set_procedure_text(self, proc_name: str, text: str):
        lines = text.split("\n")
        orig_kinds = self._orig_kinds.get(proc_name, [])
        self._edits[proc_name] = [
            (orig_kinds[i] if i < len(orig_kinds) else "code", line)
            for i, line in enumerate(lines)
        ]

    def _rebuild_xml(self) -> str:
        xml = self._orig_xml
        for proc_name, edited_lines in self._edits.items():
            xml = _replace_body(xml, proc_name, edited_lines)
        return xml

    def save(self, path: Optional[Path] = None):
        save_path = path or self.path
        save_path.write_text(self._rebuild_xml(), encoding="utf-8")
        if path and path != self.path:
            self.path = path
        self._reload()


def _replace_body(xml: str, proc_name: str, lines: list[tuple[str, str]]) -> str:
    body_lines = []
    for kind, text in lines:
        esc = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        tag = "c" if kind == "comment" else "l"
        body_lines.append(f"<{tag}>{esc}</{tag}>")

    new_body = "\n".join(body_lines)

    pattern = re.compile(
        r'(<procedure\s+name="' + re.escape(proc_name) + r'"[^>]*>.*?<body>)'
        r"(.*?)"
        r"(</body>)",
        re.DOTALL,
    )

    def replacer(m: re.Match) -> str:
        sep = "\n" if new_body else ""
        return m.group(1) + "\n" + new_body + sep + m.group(3)

    return pattern.sub(replacer, xml)
