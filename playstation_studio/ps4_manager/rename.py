"""Bulk ``.pkg`` renaming from a metadata template.

Template tokens: ``[TITLE] [TITLE_ID] [SIZE] [CATEGORY] [SYS_VER] [VER]``.
"""

from __future__ import annotations

import os
import re

from PySide6.QtCore import QThread, Signal

from .pkg_parser import get_pkg_info, iter_pkg_files

TOKENS = ("[TITLE]", "[TITLE_ID]", "[SIZE]", "[CATEGORY]", "[SYS_VER]", "[VER]")
# characters that are unsafe / ugly in filenames
_BAD = r'<>:"/\\|?*™'


def _sanitize(name: str) -> str:
    name = name.encode("ascii", "ignore").decode("utf-8")
    for ch in _BAD:
        name = name.replace(ch, "")
    return name.strip()


def render_name(template: str, info, *, no_spaces: bool = False) -> str:
    """Render *template* for a :class:`PkgInfo`, returning a filename stem."""
    values = {
        "[TITLE]": info.title, "[TITLE_ID]": info.title_id,
        "[SIZE]": info.size, "[CATEGORY]": info.category_label,
        "[SYS_VER]": info.sys_ver, "[VER]": info.ver,
    }
    out = template
    for token in re.findall(r"\[.*?\]", template):
        if token in values:
            out = out.replace(token, str(values[token]))
    out = _sanitize(out)
    if no_spaces:
        out = out.replace(" ", "-")
    return out


class BulkRenamer(QThread):
    """Walk a folder and rename every ``.pkg`` per the template."""

    log = Signal(str)
    finished_all = Signal(int)      # number renamed

    def __init__(self, root: str, template: str, no_spaces: bool = False,
                 parent=None) -> None:
        super().__init__(parent)
        self.root = root
        self.template = template
        self.no_spaces = no_spaces

    def run(self) -> None:
        if not os.path.isdir(self.root):
            self.log.emit(f"Path does not exist: {self.root}")
            self.finished_all.emit(0)
            return
        count = 0
        for pkg_path in iter_pkg_files(self.root):
            info = get_pkg_info(pkg_path, load_icon=False)
            if info is None:
                self.log.emit(f"skip (unreadable): {os.path.basename(pkg_path)}")
                continue
            stem = render_name(self.template, info, no_spaces=self.no_spaces)
            if not stem:
                continue
            dest = os.path.join(os.path.dirname(pkg_path), f"{stem}.pkg")
            if os.path.abspath(dest) == os.path.abspath(pkg_path):
                continue
            try:
                os.rename(pkg_path, dest)
                count += 1
                self.log.emit(f"→ {os.path.basename(dest)}")
            except OSError as e:
                self.log.emit(f"✗ {os.path.basename(pkg_path)}: {e}")
        self.finished_all.emit(count)
