"""Detect PS4/PS5 consoles running an FTP server on the LAN.

Reuses the shared :class:`ConsoleScanner` (Sony DDP broadcast + a TCP sweep)
but probes common console FTP ports too, so a found console can be turned
straight into an FTP site with the right port pre-filled.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QProgressBar, QPushButton, QVBoxLayout,
)

from ..shared.discovery import TCP_HINTS, ConsoleScanner

# Console FTP servers, in the order we prefer them (etaHEN 1337, GoldHEN 2121).
FTP_PORTS = (1337, 2121, 21)
# Ports to probe: FTP ports (for the connection) + identity hints (PS4/PS5).
PROBE_PORTS = tuple(dict.fromkeys(FTP_PORTS + tuple(TCP_HINTS)))


def ftp_port_for(console: dict) -> int | None:
    """Pick the best FTP port from a detected console's open ports."""
    open_ports = set(console.get("ports", []))
    for p in FTP_PORTS:
        if p in open_ports:
            return p
    return None


class FtpDetectDialog(QDialog):
    """Scan the LAN and let the user add detected consoles as FTP sites.

    After ``exec()``, :attr:`chosen` holds the list of selected console dicts
    (each augmented with an ``ftp_port`` key when one was detected).
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.chosen: list[dict] = []
        self._scanner: ConsoleScanner | None = None
        self.setWindowTitle("Detect PS4 / PS5 on the network")
        self.setMinimumSize(480, 360)

        lay = QVBoxLayout(self)
        self.info = QLabel("Scanning your network for PS4 / PS5 consoles…")
        lay.addWidget(self.info)

        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        lay.addWidget(self.bar)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.itemDoubleClicked.connect(lambda *_: self._accept_selection())
        lay.addWidget(self.list, stretch=1)

        row = QHBoxLayout()
        self.btn_rescan = QPushButton("Rescan")
        self.btn_rescan.clicked.connect(self.start_scan)
        self.btn_add = QPushButton("Add Selected as Site(s)")
        self.btn_add.setObjectName("Primary")
        self.btn_add.setEnabled(False)
        self.btn_add.clicked.connect(self._accept_selection)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        row.addWidget(self.btn_rescan)
        row.addStretch(1)
        row.addWidget(btn_cancel)
        row.addWidget(self.btn_add)
        lay.addLayout(row)

        self.start_scan()

    def start_scan(self) -> None:
        if self._scanner and self._scanner.isRunning():
            return
        self.list.clear()
        self.btn_add.setEnabled(False)
        self.btn_rescan.setEnabled(False)
        self.bar.setRange(0, 0)
        self.info.setText("Scanning your network for PS4 / PS5 consoles…")
        self._scanner = ConsoleScanner(tcp_ports=PROBE_PORTS, parent=self)
        self._scanner.found.connect(self._on_found)
        self._scanner.finished_scan.connect(self._on_done)
        self._scanner.start()

    def _on_found(self, console: dict) -> None:
        ctype = console.get("type", "Console")
        name = console.get("name") or "(unnamed)"
        ip = console.get("ip", "")
        port = ftp_port_for(console)
        console["ftp_port"] = port
        if port:
            label = f"{ctype}   {ip}:{port}   —   {name}   ·  FTP ready"
        else:
            label = f"{ctype}   {ip}   —   {name}   ·  no FTP port open"
        item = QListWidgetItem(label)
        item.setData(Qt.UserRole, console)
        # disable selection of consoles without an FTP server
        if not port:
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable & ~Qt.ItemIsEnabled)
        self.list.addItem(item)

    def _on_done(self, count: int) -> None:
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        self.btn_rescan.setEnabled(True)
        selectable = [self.list.item(i) for i in range(self.list.count())
                      if self.list.item(i).flags() & Qt.ItemIsSelectable]
        if count == 0:
            self.info.setText("No consoles found. Make sure the console is on "
                              "the same network and its FTP server is running, "
                              "then Rescan.")
        elif not selectable:
            self.info.setText(f"Found {count} device(s), but none had an FTP "
                              "port open (1337 / 2121 / 21). Start the FTP "
                              "server on the console, then Rescan.")
        else:
            self.info.setText(f"Found {len(selectable)} console(s) with FTP. "
                              "Select and click Add Selected as Site(s).")
            selectable[0].setSelected(True)
            self.btn_add.setEnabled(True)
        self.list.itemSelectionChanged.connect(
            lambda: self.btn_add.setEnabled(bool(self.list.selectedItems())))

    def _accept_selection(self) -> None:
        self.chosen = [it.data(Qt.UserRole) for it in self.list.selectedItems()]
        if self.chosen:
            self.accept()

    def reject(self) -> None:
        if self._scanner and self._scanner.isRunning():
            self._scanner.wait(50)
        super().reject()
