# HDevLight

A lightweight desktop editor for MVTec HALCON HDevelop `.hdev` and `.hdvp` files, built with Python and PyQt6.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![PyQt6](https://img.shields.io/badge/PyQt6-6.4%2B-green)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey)

---

## Features

| Feature | Detail |
|---|---|
| **Syntax highlighting** | Keywords, operators, strings, comment lines — colours matched to HDevelop |
| **Procedures panel** | Lists all procedures with parameter summary; click to jump |
| **Checker** | Runs the built-in HALCON code checker (F5) with colour-coded output |
| **Find / Replace** | Ctrl+F — with case-sensitive, whole-word, find prev/next, replace all |
| **Activate / Deactivate lines** | F3 removes `*`, F4 adds `*` — same as HDevelop |
| **Go to Line** | Alt+G |
| **Autocomplete** | Shows keywords and cached HALCON operator names after 2+ characters |
| **Ctrl+scroll zoom** | Resizes editor font; gutter and tab stops update automatically |
| **Drag-and-drop** | Drop a `.hdev` or `.hdvp` file onto the window to open it |
| **Recent files** | File → Recent Files keeps the last 10 opened paths |
| **Light theme** | Forced light palette — ignores Windows dark mode |

---

## Requirements

```
PyQt6 >= 6.4.0
```

Install with:

```bash
pip install PyQt6
```

---

## Running

```bash
python main.py                          # open blank
python main.py path/to/program.hdev     # open file directly
```

---

## Building a standalone `.exe`

Requires [PyInstaller](https://pyinstaller.org):

```bat
build.bat
```

Output: `dist\HDevLight.exe` — single-file executable, no console window.

---

## Project structure

```
HDevLight/
├── main.py                  # Entry point, Fusion style + light palette
├── requirements.txt
├── SigaH.spec               # PyInstaller spec
├── build.bat                # Build script
└── hdev_editor/
    ├── window.py            # MainWindow — menus, toolbar, dock layout
    ├── editor.py            # CodeEditor — gutter, highlight, autocomplete
    ├── highlighter.py       # QSyntaxHighlighter — HALCON colour scheme
    ├── document.py          # HdevDocument — parse / edit / save .hdev XML
    ├── hdev_core.py         # HALCON checker + Signatures cache
    ├── checker_panel.py     # Checker output panel
    ├── outline.py           # Procedures outline panel
    └── find_replace.py      # Find / Replace dialog
```

---

## Keyboard shortcuts

| Key | Action |
|---|---|
| Ctrl+O | Open file |
| Ctrl+S | Save |
| Ctrl+Z / Ctrl+Y | Undo / Redo |
| F5 | Run checker |
| F3 | Activate selected lines (remove `*`) |
| F4 | Deactivate selected lines (add `*`) |
| Ctrl+F | Find / Replace |
| Alt+G | Go to line |
| Ctrl+scroll | Zoom editor font |

---

## Notes

- HALCON does **not** need to be installed to open and edit files. The checker and autocomplete use the HALCON signature cache when available.
- Settings (window geometry, recent files) are stored in the Windows registry under `HKCU\Software\Siga\HDevLight`.
