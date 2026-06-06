"""Auto-Detect dialog — scans the LAN and lets the user pick a console."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QProgressBar,
    QPushButton, QVBoxLayout,
)

from .discovery import ConsoleScanner


class AutoDetectDialog(QDialog):
    """Modal scan dialog. After exec(), ``selected`` holds the chosen console
    dict (``{ip, type, name, ...}``) or is ``None``."""

    def __init__(self, parent=None, prefer_type: str | None = None) -> None:
        super().__init__(parent)
        self.prefer_type = (prefer_type or "").upper()
        self.selected: dict | None = None
        self._scanner: ConsoleScanner | None = None
        self.setWindowTitle("Auto-Detect Console")
        self.setMinimumSize(420, 320)

        lay = QVBoxLayout(self)
        self.info = QLabel("Scanning your network for PS4 / PS5 consoles…")
        lay.addWidget(self.info)

        self.bar = QProgressBar()
        self.bar.setRange(0, 0)            # indeterminate while scanning
        lay.addWidget(self.bar)

        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda *_: self._accept_selection())
        lay.addWidget(self.list, stretch=1)

        row = QHBoxLayout()
        self.btn_rescan = QPushButton("Rescan")
        self.btn_rescan.clicked.connect(self.start_scan)
        self.btn_use = QPushButton("Use Selected")
        self.btn_use.setObjectName("Primary")
        self.btn_use.setEnabled(False)
        self.btn_use.clicked.connect(self._accept_selection)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        row.addWidget(self.btn_rescan)
        row.addStretch(1)
        row.addWidget(btn_cancel)
        row.addWidget(self.btn_use)
        lay.addLayout(row)

        self.start_scan()

    def start_scan(self) -> None:
        if self._scanner and self._scanner.isRunning():
            return
        self.list.clear()
        self.btn_use.setEnabled(False)
        self.btn_rescan.setEnabled(False)
        self.bar.setRange(0, 0)
        self.info.setText("Scanning your network for PS4 / PS5 consoles…")
        self._scanner = ConsoleScanner(parent=self)
        self._scanner.found.connect(self._on_found)
        self._scanner.finished_scan.connect(self._on_done)
        self._scanner.start()

    def _on_found(self, console: dict) -> None:
        ctype = console.get("type", "Console")
        name = console.get("name") or "(unnamed)"
        ip = console.get("ip", "")
        via = console.get("source", "")
        ports = console.get("ports")
        detail = f"  ·  via {via}"
        if ports:
            detail += f" {', '.join(map(str, ports))}"
        item = QListWidgetItem(f"{ctype}   {ip}   —   {name}{detail}")
        item.setData(Qt.UserRole, console)
        self.list.addItem(item)
        # auto-select a preferred-type match
        if self.prefer_type and ctype.startswith(self.prefer_type) \
                and not self.list.currentItem():
            self.list.setCurrentItem(item)

    def _on_done(self, count: int) -> None:
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        self.btn_rescan.setEnabled(True)
        if count == 0:
            self.info.setText("No consoles found. Make sure the console is on "
                              "the same network (and awake), then Rescan.")
        else:
            self.info.setText(f"Found {count} device(s). Pick one and click "
                              "Use Selected.")
            if not self.list.currentItem():
                self.list.setCurrentRow(0)
            self.btn_use.setEnabled(True)
        self.list.currentItemChanged.connect(
            lambda *_: self.btn_use.setEnabled(self.list.currentItem() is not None))

    def _accept_selection(self) -> None:
        item = self.list.currentItem()
        if item is not None:
            self.selected = item.data(Qt.UserRole)
            self.accept()

    def reject(self) -> None:
        if self._scanner and self._scanner.isRunning():
            self._scanner.wait(50)
        super().reject()


def detect_console(parent=None, prefer_type: str | None = None) -> dict | None:
    """Open the Auto-Detect dialog; return the chosen console dict or None."""
    dlg = AutoDetectDialog(parent, prefer_type)
    if dlg.exec():
        return dlg.selected
    return None
