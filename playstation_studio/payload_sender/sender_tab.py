"""Payload Sender tab — find PS4/PS5 payloads and send them, singly or in bulk.

Add files, drag & drop, or point Scan Folder at a directory to auto-detect every
payload (.elf/.bin/.jar/.self/.prx/.sprx plus any custom types). Then send the
selected payloads one by one, with a live status for each row.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..shared.config import config
from ..shared.detect_dialog import detect_console
from ..shared.formatting import human_size
from ..shared.paths import PAYLOADS_DIR
from ..shared.theme import Palette
from .sender import (
    PORT_PRESETS, PayloadSender, custom_exts, effective_exts, is_payload,
    scan_payloads,
)

CFG = "payloads"

_OK = "#4ade80"
_FAIL = "#f87171"
_BUSY = "#fbbf24"


class PayloadSenderTab(QWidget):
    COLS = ["Payload", "Type", "Size", "Status"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.items: list[dict] = config.get(CFG, "items", []) or []
        self._sender: PayloadSender | None = None
        self._queue: list[int] = []
        self._current_row: int = -1
        self._batch_total = 0
        self._batch_done = 0
        self._ip = ""
        self._port = 0
        self._status_by_path: dict[str, tuple[str, str]] = {}
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
        self.btn_add.setToolTip("Add individual payload files.")
        self.btn_scan = QPushButton("⊕  Scan Folder")
        self.btn_scan.setToolTip("Pick a folder and recursively find every "
                                 "payload file beneath it.")
        self.btn_remove = QPushButton("－  Remove")
        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setObjectName("Ghost")
        self.btn_add.clicked.connect(self.on_add)
        self.btn_scan.clicked.connect(self.on_scan)
        self.btn_remove.clicked.connect(self.on_remove)
        self.btn_clear.clicked.connect(self.on_clear)
        bar.addWidget(self.btn_add)
        bar.addWidget(self.btn_scan)
        bar.addWidget(self.btn_remove)
        bar.addStretch(1)
        self.count_pill = QLabel("0 payloads")
        self.count_pill.setObjectName("Pill")
        bar.addWidget(self.count_pill)
        bar.addWidget(self.btn_clear)
        col.addLayout(bar)

        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.itemDoubleClicked.connect(self._send_double_clicked)
        col.addWidget(self.table, stretch=3)

        self.hint = QLabel("Drop payloads or a folder here, use Add Payload(s), "
                           "or Scan Folder.")
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

        lay.addWidget(self._field_label("Custom file types (scan)"))
        self.exts = QLineEdit(config.get(CFG, "custom_exts", ""))
        self.exts.setPlaceholderText("e.g.  .out .mod  (space/comma separated)")
        self.exts.setToolTip("Extra extensions that Scan Folder / drag & drop "
                             "treat as payloads, on top of the built-in set:\n"
                             + "  ".join(effective_exts()))
        self.exts.editingFinished.connect(self._save_exts)
        lay.addWidget(self.exts)

        lay.addSpacing(6)
        self.btn_send_sel = QPushButton("▶  Send Selected")
        self.btn_send_sel.setObjectName("Primary")
        self.btn_send_sel.clicked.connect(self.on_send_selected)
        lay.addWidget(self.btn_send_sel)
        self.btn_send_all = QPushButton("Send All")
        self.btn_send_all.clicked.connect(self.on_send_all)
        lay.addWidget(self.btn_send_all)
        self.btn_cancel = QPushButton("Stop")
        self.btn_cancel.setObjectName("Danger")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.on_cancel)
        lay.addWidget(self.btn_cancel)

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

    def _save_exts(self) -> None:
        config.set(CFG, "custom_exts", self.exts.text().strip())
        self.exts.setToolTip("Extra extensions that Scan Folder / drag & drop "
                             "treat as payloads, on top of the built-in set:\n"
                             + "  ".join(effective_exts()))

    # ================================================================ actions
    def on_add(self) -> None:
        exts = " ".join(f"*{e}" for e in effective_exts())
        start = PAYLOADS_DIR if PAYLOADS_DIR.exists() else ""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select payload(s)", str(start),
            f"Payloads ({exts});;All files (*)")
        added = sum(1 for p in paths if self._add_path(p))
        if added:
            self._persist()
            self._reload_table()
            self._log(f"Added {added} payload(s).")

    def on_scan(self) -> None:
        start = str(PAYLOADS_DIR) if PAYLOADS_DIR.exists() else ""
        folder = QFileDialog.getExistingDirectory(
            self, "Select a folder to scan for payloads", start)
        if not folder:
            return
        found = scan_payloads(folder)
        added = sum(1 for p in found if self._add_path(p))
        self._persist()
        self._reload_table()
        dupes = len(found) - added
        msg = f"Scanned {folder}: found {len(found)} payload(s)"
        if dupes:
            msg += f", {added} new ({dupes} already listed)"
        self._log(msg + ".")
        if not found:
            QMessageBox.information(
                self, "No payloads found",
                "No payload files were found under:\n\n" + folder +
                "\n\nBuilt-in types: " + "  ".join(effective_exts()) +
                "\nAdd more via 'Custom file types' on the right.")

    def _add_path(self, path: str) -> bool:
        path = os.path.abspath(path)
        if not is_payload(path):
            return False
        if any(os.path.abspath(i["path"]) == path for i in self.items):
            return False
        self.items.append({"name": os.path.basename(path), "path": path})
        return True

    def on_remove(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()},
                      reverse=True)
        if not rows:
            return
        for r in rows:
            if 0 <= r < len(self.items):
                del self.items[r]
        self._persist()
        self._reload_table()

    def on_clear(self) -> None:
        self.items.clear()
        self._status_by_path.clear()
        self._persist()
        self._reload_table()

    def _persist(self) -> None:
        # store only durable fields (name + path)
        config.set(CFG, "items",
                   [{"name": i["name"], "path": i["path"]} for i in self.items])

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
            text, color = self._status_by_path.get(
                os.path.abspath(it["path"]),
                ("Ready" if exists else "Missing", Palette.text_faint))
            self.table.setItem(r, 3, self._status_cell(text, color))
        self.hint.setVisible(not self.items)
        n = len(self.items)
        self.count_pill.setText(f"{n} payload{'s' if n != 1 else ''}")
        if self.items:
            self.table.selectRow(0)

    @staticmethod
    def _status_cell(text: str, color: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignCenter)
        item.setForeground(QColor(color))
        return item

    def _set_row_status(self, row: int, text: str, color: str) -> None:
        if 0 <= row < len(self.items):
            self._status_by_path[os.path.abspath(self.items[row]["path"])] = \
                (text, color)
            self.table.setItem(row, 3, self._status_cell(text, color))

    # -------------------------------------------------------------- sending
    def _send_double_clicked(self, *_a) -> None:
        row = self.table.currentRow()
        if 0 <= row < len(self.items):
            self._start_batch([row])

    def on_send_selected(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows:
            QMessageBox.information(self, "No selection",
                                   "Select one or more payloads to send.")
            return
        self._start_batch(rows)

    def on_send_all(self) -> None:
        self._start_batch(list(range(len(self.items))))

    def _start_batch(self, rows: list[int]) -> None:
        if self._sender is not None and self._sender.isRunning():
            return
        rows = [r for r in rows
                if 0 <= r < len(self.items) and os.path.isfile(self.items[r]["path"])]
        if not rows:
            QMessageBox.information(self, "Nothing to send",
                                   "No existing payload files in the selection.")
            return
        ip = self.ip.text().strip()
        port = self.port.value()
        if not ip:
            QMessageBox.information(self, "Target IP",
                                   "Enter your console's IP address.")
            return
        config.update(CFG, ip=ip, port=port)
        self._ip, self._port = ip, port
        self._queue = rows
        self._batch_total = len(rows)
        self._batch_done = 0
        for r in rows:
            self._set_row_status(r, "Queued", _BUSY)
        self._set_sending(True)
        self._log("=" * 40 + f"\nSending {len(rows)} payload(s) → {ip}:{port}")
        self._send_next()

    def _send_next(self) -> None:
        if not self._queue:
            self._finish_batch()
            return
        row = self._queue.pop(0)
        self._current_row = row
        item = self.items[row]
        self._set_row_status(row, "Sending…", _BUSY)
        self.table.selectRow(row)
        self.progress.setValue(0)
        self.status.setText(f"Sending {item['name']} → {self._ip}:{self._port}  "
                            f"({self._batch_done + 1}/{self._batch_total})")
        self._log(f"→ {item['name']}")
        self._sender = PayloadSender(item["path"], self._ip, self._port, self)
        self._sender.progress.connect(self._on_progress)
        self._sender.done.connect(self._on_done)
        self._sender.start()

    def _on_progress(self, sent: int, total: int) -> None:
        if total:
            self.progress.setValue(int(sent / total * 100))

    def _on_done(self, ok: bool, message: str) -> None:
        self._set_row_status(self._current_row,
                             "✓ Sent" if ok else "✗ Failed",
                             _OK if ok else _FAIL)
        if ok:
            self._batch_done += 1
        self.progress.setValue(100 if ok else 0)
        self._log(("✓ " if ok else "✗ ") + message)
        self._sender = None
        self._send_next()

    def _finish_batch(self) -> None:
        self._set_sending(False)
        failed = self._batch_total - self._batch_done
        msg = f"Done — {self._batch_done}/{self._batch_total} sent"
        if failed:
            msg += f", {failed} failed"
        self.status.setText(msg)
        self._log(msg + "\n" + "=" * 40)

    def on_cancel(self) -> None:
        """Stop after the current file (in-flight send can't be interrupted)."""
        self._queue.clear()
        for r in range(len(self.items)):
            text, _c = self._status_by_path.get(
                os.path.abspath(self.items[r]["path"]), ("", ""))
            if text == "Queued":
                self._set_row_status(r, "Cancelled", Palette.text_faint)
        self.status.setText("Stopping after current file…")

    def _set_sending(self, sending: bool) -> None:
        for w in (self.btn_send_sel, self.btn_send_all, self.btn_add,
                  self.btn_scan, self.btn_remove, self.btn_clear):
            w.setEnabled(not sending)
        self.btn_cancel.setEnabled(sending)

    # ---------------------------------------------------------------- misc
    def _log(self, text: str) -> None:
        self.log.appendPlainText(text)

    # ---------------------------------------------------------- drag & drop
    def dragEnterEvent(self, e: QDragEnterEvent) -> None:
        urls = e.mimeData().urls() if e.mimeData().hasUrls() else []
        if any(os.path.isdir(u.toLocalFile()) or is_payload(u.toLocalFile())
               for u in urls):
            e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent) -> None:
        added = 0
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if os.path.isdir(p):
                added += sum(1 for f in scan_payloads(p) if self._add_path(f))
            elif self._add_path(p):
                added += 1
        if added:
            self._persist()
            self._reload_table()
            self._log(f"Added {added} payload(s) via drag & drop.")
