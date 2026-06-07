"""Application bootstrap: create the QApplication, apply the theme, show window."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .interface.shell import MainWindow
from .shared.paths import ensure_app_dirs
from .shared.theme import stylesheet


def main() -> int:
    # Create payloads/, host/ and temp/ working folders before anything else.
    ensure_app_dirs()

    app = QApplication(sys.argv)
    app.setApplicationName("PlayStation Studio")
    app.setApplicationDisplayName("PlayStation Studio")
    app.setStyle("Fusion")
    app.setStyleSheet(stylesheet())

    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
