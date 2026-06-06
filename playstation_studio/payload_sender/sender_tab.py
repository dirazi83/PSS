"""Payload Sender tab — pick .elf/.bin/.jar and send to a PS4/PS5 over TCP."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..shared.config import config
from ..shared.detect_dialog import detect_console
from ..shared.formatting import human_size
from ..shared.theme import Palette
from .sender import PORT_PRESETS, SUPPORTED_EXTS, PayloadSender

CFG = "payloads"


class PayloadSenderTab(QWidget):
    COLS = ["Payload", "Type", "Size"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.items: list[dict] = config.get(CFG, "items", []) or []
        self._sender: PayloadSender | None = None
        self.setAcceptDrops(True)

        body = QHBoxLayout(self)
        body.setContentsMargins(18, 14, 18, 10)
        body.setSpacing(16)
        body.addLayout(self._build_main_column(), stretch=1)
        body.addWidget(self._build_target_panel())
        self._reload_table()

    # ------------------------------------------------------------ main column
    def _build_main_column(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(12)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.btn_add = QPushButton("＋  Add Payload(s)")
        self.btn_add.setToolTip("Add .elf / .bin / .jar files.")
        self.btn_remove = QPushButton("－  Remove")
        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setObjectName("Ghost")
        self.btn_add.clicked.connect(self.on_add)
        self.btn_remove.clicked.connect(self.on_remove)
        self.btn_clear.clicked.connect(self.on_clear)
        bar.addWidget(self.btn_add)
        bar.addWidget(self.btn_remove)
        bar.addStretch(1)
        bar.addWidget(self.btn_clear)
        col.addLayout(bar)

        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.itemDoubleClicked.connect(lambda *_: self.on_send())
        col.addWidget(self.table, stretch=3)

        self.hint = QLabel("Drop .elf / .bin / .jar here, or use Add Payload(s).")
        self.hint.setAlignment(Qt.AlignCenter)
        self.hint.setStyleSheet(f"color:{Palette.text_faint}; font-size:13px;")
        col.addWidget(self.hint)

        title = QLabel("ACTIVITY LOG")
        title.setObjectName("SectionTitle")
        col.addWidget(title)
        self.log = QPlainTextEdit()
        self.log.setObjectName("Log")
        self.log.setReadOnly(True)
        self.log.setFixedHeight(120)
        col.addWidget(self.log)
        return col

    # ----------------------------------------------------------- target panel
    def _build_target_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("Panel")
        panel.setFixedWidth(320)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.setSpacing(12)

        title = QLabel("SEND TARGET")
        title.setObjectName("SectionTitle")
        lay.addWidget(title)

        lay.addWidget(self._field_label("Console IP address"))
        self.ip = QLineEdit(config.get(CFG, "ip", ""))
        self.ip.setPlaceholderText("e.g. 192.168.1.30")
        self.ip.editingFinished.connect(
            lambda: config.set(CFG, "ip", self.ip.text().strip()))
        ip_row = QHBoxLayout()
        ip_row.setSpacing(6)
        btn_detect = QPushButton("Auto-Detect")
        btn_detect.setToolTip("Scan the network for a PS4/PS5 and fill the IP.")
        btn_detect.clicked.connect(self.on_auto_detect)
        ip_row.addWidget(self.ip, stretch=1)
        ip_row.addWidget(btn_detect)
        lay.addLayout(ip_row)

        lay.addWidget(self._field_label("Port"))
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(int(config.get(CFG, "port", 9021)))
        self.port.valueChanged.connect(
            lambda v: config.set(CFG, "port", v))
        lay.addWidget(self.port)

        lay.addWidget(self._field_label("Quick preset"))
        self.preset = QComboBox()
        self.preset.addItem("Custom…", 0)
        for label, p in PORT_PRESETS:
            self.preset.addItem(label, p)
        self.preset.activated.connect(self._apply_preset)
        lay.addWidget(self.preset)

        lay.addSpacing(6)
        self.btn_send = QPushButton("▶  Send to Console")
        self.btn_send.setObjectName("Primary")
        self.btn_send.clicked.connect(self.on_send)
        lay.addWidget(self.btn_send)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        lay.addWidget(self.progress)

        self.status = QLabel("Idle")
        self.status.setStyleSheet(f"color:{Palette.text_dim}; font-size:12px;")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        lay.addStretch(1)
        note = QLabel("Tip: start the ELF loader / payload listener on your "
                      "console first, then send.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{Palette.text_faint}; font-size:11px;")
        lay.addWidget(note)
        return panel

    def _field_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color:{Palette.text_dim}; font-size:12px; font-weight:600;")
        return lbl

    def on_auto_detect(self) -> None:
        console = detect_console(self)
        if console:
            self.ip.setText(console["ip"])
            config.set(CFG, "ip", console["ip"])
            self._log(f"Auto-detected {console.get('type','Console')} at "
                      f"{console['ip']}"
                      + (f"  ({console['name']})" if console.get("name") else ""))

    def _apply_preset(self, index: int) -> None:
        port = self.preset.itemData(index)
        if port:
            self.port.setValue(int(port))

    # ================================================================ actions
    def on_add(self) -> None:
        exts = " ".join(f"*{e}" for e in SUPPORTED_EXTS)
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select payload(s)", "", f"Payloads ({exts});;All files (*)")
        added = 0
        for p in paths:
            if self._add_path(p):
                added += 1
        if added:
            self._persist()
            self._reload_table()
            self._log(f"Added {added} payload(s).")

    def _add_path(self, path: str) -> bool:
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            return False
        if os.path.splitext(path)[1].lower() not in SUPPORTED_EXTS:
            return False
        if any(os.path.abspath(i["path"]) == path for i in self.items):
            return False
        self.items.append({"name": os.path.basename(path), "path": path})
        return True

    def on_remove(self) -> None:
        row = self.table.currentRow()
        if 0 <= row < len(self.items):
            del self.items[row]
            self._persist()
            self._reload_table()

    def on_clear(self) -> None:
        self.items.clear()
        self._persist()
        self._reload_table()

    def _persist(self) -> None:
        config.set(CFG, "items", self.items)

    def _reload_table(self) -> None:
        self.table.setRowCount(0)
        for it in self.items:
            r = self.table.rowCount()
            self.table.insertRow(r)
            exists = os.path.isfile(it["path"])
            name = QTableWidgetItem(("  " if exists else "  ⚠ ") + it["name"])
            name.setToolTip(it["path"] if exists else f"missing: {it['path']}")
            ext = os.path.splitext(it["path"])[1].lstrip(".").upper() or "?"
            size = QTableWidgetItem(
                human_size(os.path.getsize(it["path"])) if exists else "—")
            size.setTextAlignment(Qt.AlignCenter)
            type_item = QTableWidgetItem(ext)
            type_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(r, 0, name)
            self.table.setItem(r, 1, type_item)
            self.table.setItem(r, 2, size)
        self.hint.setVisible(not self.items)
        if self.items:
            self.table.selectRow(0)

    def on_send(self) -> None:
        if self._sender is not None and self._sender.isRunning():
            return
        row = self.table.currentRow()
        if not (0 <= row < len(self.items)):
            QMessageBox.information(self, "No payload",
                                    "Select a payload to send.")
            return
        item = self.items[row]
        if not os.path.isfile(item["path"]):
            QMessageBox.warning(self, "Missing file",
                                f"This payload no longer exists:\n{item['path']}")
            return
        ip = self.ip.text().strip()
        port = self.port.value()
        if not ip:
            QMessageBox.information(self, "Target IP",
                                    "Enter your console's IP address.")
            return
        config.update(CFG, ip=ip, port=port)
        self.btn_send.setEnabled(False)
        self.progress.setValue(0)
        self.status.setText(f"Connecting to {ip}:{port}…")
        self._log(f"Sending {item['name']} → {ip}:{port}")
        self._sender = PayloadSender(item["path"], ip, port, self)
        self._sender.progress.connect(self._on_progress)
        self._sender.done.connect(self._on_done)
        self._sender.start()

    def _on_progress(self, sent: int, total: int) -> None:
        if total:
            self.progress.setValue(int(sent / total * 100))
            self.status.setText(f"{human_size(sent)} / {human_size(total)}")

    def _on_done(self, ok: bool, message: str) -> None:
        self.btn_send.setEnabled(True)
        self.progress.setValue(100 if ok else 0)
        self.status.setText("✓ Sent" if ok else "✗ Failed")
        self._log(("✓ " if ok else "✗ ") + message)

    # ---------------------------------------------------------------- misc
    def _log(self, text: str) -> None:
        self.log.appendPlainText(text)

    # ---------------------------------------------------------- drag & drop
    def dragEnterEvent(self, e: QDragEnterEvent) -> None:
        if e.mimeData().hasUrls() and any(
                os.path.splitext(u.toLocalFile())[1].lower() in SUPPORTED_EXTS
                for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent) -> None:
        added = sum(1 for u in e.mimeData().urls()
                    if self._add_path(u.toLocalFile()))
        if added:
            self._persist()
            self._reload_table()
            self._log(f"Added {added} payload(s) via drag & drop.")
