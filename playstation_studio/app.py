"""Application bootstrap: create the QApplication, build the shell, show it.

Prefers the Fluent left-navigation shell (PySide6-Fluent-Widgets). If that
package isn't importable, falls back to the classic Fusion + custom-QSS tabbed
shell so the app still runs.
"""

from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication

from .shared.paths import ensure_app_dirs
from .shared.theme import MacPalette, Palette, stylesheet


def _build_classic_shell(app: QApplication):
    """The original Fusion + custom-QSS tabbed shell (fallback)."""
    from .interface.shell import MainWindow
    app.setStyle("Fusion")
    if sys.platform == "darwin":
        # Modern macOS "Liquid Glass" theme + the real SF Pro system font.
        from PySide6.QtGui import QColor, QFontDatabase, QPalette
        sysfont = QFontDatabase.systemFont(QFontDatabase.GeneralFont)
        # Match the stylesheet, which sizes text in PIXELS. Using point size
        # here (≈17px on Retina) while the QSS paints 13px clips combo/input
        # text inside boxes laid out for the smaller metric.
        sysfont.setPixelSize(13)
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
    return MainWindow()


def main() -> int:
    # Create payloads/, host/ and temp/ working folders before anything else.
    ensure_app_dirs()

    app = QApplication(sys.argv)
    app.setApplicationName("PlayStation Studio")
    app.setApplicationDisplayName("PlayStation Studio")

    # Prefer the Fluent left-navigation shell; the theme must be applied before
    # the window is constructed (Fluent builds its chrome with the active theme).
    try:
        from .interface.fluent_shell import FluentMainWindow, init_fluent_theme
        init_fluent_theme()
        win = FluentMainWindow()
    except Exception as e:        # qfluentwidgets missing or failed to init
        logging.getLogger(__name__).info(
            "Fluent shell unavailable (%s); using the classic shell", e)
        win = _build_classic_shell(app)

    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
