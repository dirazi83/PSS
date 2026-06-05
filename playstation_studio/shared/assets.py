"""Loaders for the bundled icon set (see assets/build_icons.py)."""

from __future__ import annotations

import os

from PySide6.QtGui import QIcon, QPixmap

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
ICON_DIR = os.path.join(ASSETS_DIR, "icons")
SVG_DIR = os.path.join(ASSETS_DIR, "svg")

_SIZES = [16, 24, 32, 48, 64, 128, 256, 512, 1024]


def make_icon(name: str) -> QIcon:
    """Multi-resolution QIcon for *name* (app/ps4/ps5/payload/ftp)."""
    icon = QIcon()
    for size in _SIZES:
        path = os.path.join(ICON_DIR, f"{name}_{size}.png")
        if os.path.isfile(path):
            icon.addFile(path)
    if icon.isNull():
        svg = os.path.join(SVG_DIR, f"{name}.svg")
        if os.path.isfile(svg):
            icon = QIcon(svg)
    return icon


def app_icon() -> QIcon:
    return make_icon("app")


def pixmap(name: str, prefer: int = 64) -> QPixmap:
    """Best-available PNG pixmap for *name*."""
    path = os.path.join(ICON_DIR, f"{name}_{prefer}.png")
    if not os.path.isfile(path):
        path = os.path.join(ICON_DIR, f"{name}_256.png")
    return QPixmap(path) if os.path.isfile(path) else QPixmap()
