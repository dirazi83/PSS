"""Application bootstrap: create the QApplication, apply the theme, show window."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .interface.shell import MainWindow
from .shared.paths import ensure_app_dirs
from .shared.theme import MacPalette, Palette, stylesheet


def main() -> int:
    # Create payloads/, host/ and temp/ working folders before anything else.
    ensure_app_dirs()

    app = QApplication(sys.argv)
    app.setApplicationName("PlayStation Studio")
    app.setApplicationDisplayName("PlayStation Studio")
    app.setStyle("Fusion")
    if sys.platform == "darwin":
        # Modern macOS "Liquid Glass" theme + the real SF Pro system font.
        from PySide6.QtGui import QColor, QFontDatabase, QPalette
        sysfont = QFontDatabase.systemFont(QFontDatabase.GeneralFont)
        sysfont.setPointSize(13)
        app.setFont(sysfont)
        # A dark base palette so the theme's translucent rgba() surfaces layer
        # over dark (the material look) instead of Fusion's default white base.
        dark = QColor("#1c1c1e")
        text = QColor("#f5f5f7")
        pal = QPalette()
        for role in (QPalette.Window, QPalette.Base, QPalette.Button):
            pal.setColor(role, dark)
        pal.setColor(QPalette.AlternateBase, QColor("#242429"))
        for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText,
                     QPalette.BrightText):
            pal.setColor(role, text)
        pal.setColor(QPalette.ToolTipBase, QColor("#2c2c2e"))
        pal.setColor(QPalette.ToolTipText, text)
        pal.setColor(QPalette.PlaceholderText, QColor(235, 235, 245, 110))
        pal.setColor(QPalette.Highlight, QColor("#0A84FF"))
        pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
        pal.setColor(QPalette.Disabled, QPalette.Text, QColor(235, 235, 245, 90))
        app.setPalette(pal)
        app.setStyleSheet(stylesheet(MacPalette))
    else:
        app.setStyleSheet(stylesheet(Palette))

    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
