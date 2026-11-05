"""HDevLight — HDevelop Light Editor  |  entry point."""

import sys
from pathlib import Path


def _light_palette():
    """Return an explicit light QPalette so the app is never affected by Windows dark mode."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QColor, QPalette
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window,          QColor(240, 240, 240))
    p.setColor(QPalette.ColorRole.WindowText,      Qt.GlobalColor.black)
    p.setColor(QPalette.ColorRole.Base,            Qt.GlobalColor.white)
    p.setColor(QPalette.ColorRole.AlternateBase,   QColor(233, 233, 233))
    p.setColor(QPalette.ColorRole.ToolTipBase,     Qt.GlobalColor.white)
    p.setColor(QPalette.ColorRole.ToolTipText,     Qt.GlobalColor.black)
    p.setColor(QPalette.ColorRole.Text,            Qt.GlobalColor.black)
    p.setColor(QPalette.ColorRole.Button,          QColor(240, 240, 240))
    p.setColor(QPalette.ColorRole.ButtonText,      Qt.GlobalColor.black)
    p.setColor(QPalette.ColorRole.BrightText,      Qt.GlobalColor.red)
    p.setColor(QPalette.ColorRole.Link,            QColor(0, 0, 255))
    p.setColor(QPalette.ColorRole.Highlight,       QColor(0, 120, 215))
    p.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.white)
    # Disabled state
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(120, 120, 120))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text,       QColor(120, 120, 120))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(120, 120, 120))
    return p


def main() -> None:
    try:
        from PyQt6.QtWidgets import QApplication
    except ImportError:
        print("PyQt6 is required.  Install it with:\n    pip install PyQt6")
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")          # consistent cross-platform look
    app.setPalette(_light_palette()) # always light, ignores system dark mode
    app.setApplicationName("HDevLight")
    app.setOrganizationName("Siga")

    from hdev_editor.window import MainWindow
    win = MainWindow()
    win.show()

    if len(sys.argv) > 1:
        p = Path(sys.argv[1])
        if p.is_file() and p.suffix.lower() in (".hdev", ".hdvp"):
            win.open_file(p)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
