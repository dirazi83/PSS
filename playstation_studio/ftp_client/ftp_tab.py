"""FTP Client tab — dual-pane local/remote browser with a transfer queue."""

from __future__ import annotations

import os
import posixpath
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..shared.config import config
from ..shared.formatting import human_size
from ..shared.theme import Palette
from .ftp_engine import Entry, FtpOptions, FtpService, TransferJob
from .site_dialog import SiteManagerDialog
from .sites import Site, SiteManager

CFG = "ftp"


def list_local(path: str) -> list[Entry]:
    entries: list[Entry] = []
    try:
        names = os.listdir(path)
    except OSError:
        return entries
    for name in names:
        full = os.path.join(path, name)
        try:
            is_dir = os.path.isdir(full)
            st = os.stat(full)
            entries.append(Entry(
                name, is_dir, 0 if is_dir else st.st_size,
                time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))))
        except OSError:
            continue
    return sorted(entries, key=lambda e: (not e.is_dir, e.name.lower()))


class FtpClientTab(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.manager = SiteManager()
        self.service = FtpService(self)
        self.service.start()
        self._wire_service()

        self.local_cwd = config.get(CFG, "local_dir", "") or os.path.expanduser("~")
        self.remote_cwd = "/"
        self.local_entries: list[Entry] = []
        self.remote_entries: list[Entry] = []
        self.jobs: dict[int, TransferJob] = {}
        self.job_rows: dict[int, int] = {}
        self.bars: dict[int, QProgressBar] = {}
        self._job_seq = 0
        self._connected = False

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 12, 18, 10)
        root.setSpacing(10)
        root.addLayout(self._build_toolbar())

        split = QSplitter(Qt.Horizontal)
        split.addWidget(self._build_local_pane())
        split.addWidget(self._build_remote_pane())
        split.setSizes([1, 1])
        root.addWidget(split, stretch=3)

        root.addWidget(self._build_queue(), stretch=2)

        self.status = QLabel("Not connected")
        self.status.setObjectName("StatusBar")
        root.addWidget(self.status)

        self._reload_sites()
        self._refresh_local()

    # =============================================================== toolbar
    def _build_toolbar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.site_combo = QComboBox()
        self.site_combo.setMinimumWidth(180)
        self.btn_connect = QPushButton("Connect")
        self.btn_connect.setObjectName("Primary")
        self.btn_connect.clicked.connect(self.on_connect)
        self.btn_disconnect = QPushButton("Disconnect")
        self.btn_disconnect.setEnabled(False)
        self.btn_disconnect.clicked.connect(self.on_disconnect)
        self.btn_sites = QPushButton("Site Manager…")
        self.btn_sites.clicked.connect(self.on_site_manager)
        self.btn_upload = QPushButton("Upload →")
        self.btn_upload.clicked.connect(self.on_upload)
        self.btn_download = QPushButton("← Download")
        self.btn_download.clicked.connect(self.on_download)
        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.clicked.connect(self.on_refresh)
        for w in (QLabel("Site:"), self.site_combo, self.btn_connect,
                  self.btn_disconnect, self.btn_sites):
            bar.addWidget(w)
        bar.addStretch(1)
        for w in (self.btn_upload, self.btn_download, self.btn_refresh):
            bar.addWidget(w)
        return bar

    # ============================================================ file panes
    def _pane(self, title: str):
        frame = QFrame()
        frame.setObjectName("Panel")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)
        head = QLabel(title)
        head.setObjectName("SectionTitle")
        lay.addWidget(head)
        path_row = QHBoxLayout()
        up = QPushButton("↑ Up")
        up.setFixedWidth(56)
        path_edit = QLineEdit()
        path_row.addWidget(up)
        path_row.addWidget(path_edit, stretch=1)
        lay.addLayout(path_row)
        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(["Name", "Size", "Modified"])
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setShowGrid(False)
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        lay.addWidget(table, stretch=1)
        return frame, table, path_edit, up

    def _build_local_pane(self) -> QFrame:
        frame, self.local_table, self.local_path, up = self._pane("LOCAL  ·  this computer")
        up.clicked.connect(self.on_local_up)
        self.local_path.returnPressed.connect(
            lambda: self._set_local(self.local_path.text().strip()))
        self.local_table.itemDoubleClicked.connect(self._on_local_double)
        return frame

    def _build_remote_pane(self) -> QFrame:
        frame, self.remote_table, self.remote_path, up = self._pane("REMOTE  ·  FTP server")
        up.clicked.connect(self.on_remote_up)
        self.remote_path.returnPressed.connect(
            lambda: self.service.submit("list", path=self.remote_path.text().strip()))
        self.remote_table.itemDoubleClicked.connect(self._on_remote_double)
        return frame

    # ============================================================ queue
    def _build_queue(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Panel")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        head = QLabel("TRANSFER QUEUE")
        head.setObjectName("SectionTitle")
        lay.addWidget(head)
        self.queue = QTableWidget(0, 6)
        self.queue.setHorizontalHeaderLabels(
            ["File", "Direction", "Size", "Progress", "Speed", "Status"])
        self.queue.verticalHeader().setVisible(False)
        self.queue.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.queue.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.queue.setFixedHeight(150)
        lay.addWidget(self.queue)
        self.log = QPlainTextEdit()
        self.log.setObjectName("Log")
        self.log.setReadOnly(True)
        self.log.setFixedHeight(80)
        lay.addWidget(self.log)
        return frame

    # =============================================================== service
    def _wire_service(self) -> None:
        self.service.connected.connect(self._on_connected)
        self.service.disconnected.connect(self._on_disconnected)
        self.service.listed.connect(self._on_listed)
        self.service.progress.connect(self._on_progress)
        self.service.transfer_done.connect(self._on_transfer_done)
        self.service.log.connect(self._log)

    # ---- connection ----
    def _reload_sites(self) -> None:
        self.site_combo.clear()
        for s in self.manager.sites:
            self.site_combo.addItem(("★ " if s.favorite else "") + s.name, s.id)

    def _selected_site(self) -> Site | None:
        sid = self.site_combo.currentData()
        return self.manager.find(sid) if sid else None

    def on_site_manager(self) -> None:
        dlg = SiteManagerDialog(self.manager, self)
        connect_after = dlg.exec()
        self._reload_sites()
        if connect_after and dlg.selected_site:
            idx = self.site_combo.findData(dlg.selected_site.id)
            if idx >= 0:
                self.site_combo.setCurrentIndex(idx)
            self.on_connect()

    def on_connect(self) -> None:
        site = self._selected_site()
        if site is None:
            QMessageBox.information(self, "No site",
                                    "Add a site in the Site Manager first.")
            return
        if not site.host:
            QMessageBox.information(self, "No host",
                                    "This site has no host set.")
            return
        opt = FtpOptions(host=site.host, port=site.port, user=site.user,
                         password=site.password, anonymous=site.anonymous,
                         passive=site.passive)
        self._pending_site = site
        self.status.setText(f"Connecting to {site.host}:{site.port}…")
        self._log(f"Connecting to {site.host}:{site.port} …")
        self.service.submit("connect", options=opt)

    def on_disconnect(self) -> None:
        self.service.submit("disconnect")

    def _on_connected(self, ok: bool, message: str) -> None:
        self._connected = ok
        self.btn_connect.setEnabled(not ok)
        self.btn_disconnect.setEnabled(ok)
        site = getattr(self, "_pending_site", None)
        if ok and site:
            if site.local_dir and os.path.isdir(site.local_dir):
                self._set_local(site.local_dir)
            if site.remote_dir:
                self.service.submit("list", path=site.remote_dir)
            self.status.setText(f"Connected · {site.host}")

    def _on_disconnected(self) -> None:
        self._connected = False
        self.btn_connect.setEnabled(True)
        self.btn_disconnect.setEnabled(False)
        self.remote_table.setRowCount(0)
        self.remote_entries = []
        self.status.setText("Not connected")

    # ---- remote listing ----
    def _on_listed(self, path: str, entries, error: str) -> None:
        if error:
            self._log(f"List failed: {error}")
            return
        self.remote_cwd = path
        self.remote_entries = entries
        self.remote_path.setText(path)
        self._fill_table(self.remote_table, entries)

    def _on_remote_double(self, item: QTableWidgetItem) -> None:
        e = self.remote_entries[item.row()]
        if e.is_dir:
            new = posixpath.normpath(posixpath.join(self.remote_cwd, e.name))
            self.service.submit("list", path=new)

    def on_remote_up(self) -> None:
        if not self._connected:
            return
        parent = posixpath.dirname(self.remote_cwd.rstrip("/")) or "/"
        self.service.submit("list", path=parent)

    # ---- local listing ----
    def _set_local(self, path: str) -> None:
        if os.path.isdir(path):
            self.local_cwd = path
            config.set(CFG, "local_dir", path)
            self._refresh_local()

    def _refresh_local(self) -> None:
        self.local_entries = list_local(self.local_cwd)
        self.local_path.setText(self.local_cwd)
        self._fill_table(self.local_table, self.local_entries)

    def _on_local_double(self, item: QTableWidgetItem) -> None:
        e = self.local_entries[item.row()]
        if e.is_dir:
            self._set_local(os.path.join(self.local_cwd, e.name))

    def on_local_up(self) -> None:
        self._set_local(os.path.dirname(self.local_cwd.rstrip(os.sep)) or self.local_cwd)

    # ---- shared table fill ----
    @staticmethod
    def _fill_table(table: QTableWidget, entries: list[Entry]) -> None:
        table.setRowCount(0)
        for e in entries:
            r = table.rowCount()
            table.insertRow(r)
            icon = "📁 " if e.is_dir else "📄 "
            table.setItem(r, 0, QTableWidgetItem(icon + e.name))
            size = QTableWidgetItem("" if e.is_dir else human_size(e.size))
            size.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            table.setItem(r, 1, size)
            table.setItem(r, 2, QTableWidgetItem(e.modified))

    def on_refresh(self) -> None:
        self._refresh_local()
        if self._connected:
            self.service.submit("list", path=self.remote_cwd)

    # =============================================================== transfers
    def on_upload(self) -> None:
        if not self._connected:
            QMessageBox.information(self, "Not connected", "Connect first.")
            return
        rows = {i.row() for i in self.local_table.selectedItems()}
        files = [self.local_entries[r] for r in rows
                 if not self.local_entries[r].is_dir]
        if not files:
            QMessageBox.information(self, "Select files",
                                    "Pick file(s) in the LOCAL pane to upload.")
            return
        for e in files:
            local = os.path.join(self.local_cwd, e.name)
            remote = posixpath.join(self.remote_cwd, e.name)
            self._enqueue("upload", local, remote, e.size, e.name)

    def on_download(self) -> None:
        if not self._connected:
            QMessageBox.information(self, "Not connected", "Connect first.")
            return
        rows = {i.row() for i in self.remote_table.selectedItems()}
        files = [self.remote_entries[r] for r in rows
                 if not self.remote_entries[r].is_dir]
        if not files:
            QMessageBox.information(self, "Select files",
                                    "Pick file(s) in the REMOTE pane to download.")
            return
        for e in files:
            remote = posixpath.join(self.remote_cwd, e.name)
            local = os.path.join(self.local_cwd, e.name)
            self._enqueue("download", local, remote, e.size, e.name)

    def _enqueue(self, direction: str, local: str, remote: str,
                 size: int, name: str) -> None:
        self._job_seq += 1
        job = TransferJob(self._job_seq, direction, local, remote, size)
        self.jobs[job.job_id] = job
        r = self.queue.rowCount()
        self.queue.insertRow(r)
        self.job_rows[job.job_id] = r
        arrow = "▲ upload" if direction == "upload" else "▼ download"
        self.queue.setItem(r, 0, QTableWidgetItem(name))
        self.queue.setItem(r, 1, QTableWidgetItem(arrow))
        self.queue.setItem(r, 2, QTableWidgetItem(human_size(size) if size else "—"))
        bar = QProgressBar()
        bar.setValue(0)
        self.queue.setCellWidget(r, 3, bar)
        self.bars[job.job_id] = bar
        self.queue.setItem(r, 4, QTableWidgetItem("—"))
        self.queue.setItem(r, 5, QTableWidgetItem("Queued"))
        self.service.submit("transfer", job=job)

    def _on_progress(self, job_id: int, sent: int, total: int) -> None:
        job = self.jobs.get(job_id)
        if not job:
            return
        job.sent = sent
        if job_id in self.bars and total:
            self.bars[job_id].setValue(int(sent / total * 100))
        r = self.job_rows.get(job_id)
        if r is not None:
            elapsed = max(time.time() - job.started, 1e-6)
            speed = sent / elapsed
            self.queue.setItem(r, 4, QTableWidgetItem(f"{human_size(speed)}/s"))
            self.queue.setItem(r, 5, QTableWidgetItem("Transferring"))

    def _on_transfer_done(self, job_id: int, ok: bool, message: str) -> None:
        r = self.job_rows.get(job_id)
        job = self.jobs.get(job_id)
        if r is not None:
            self.queue.setItem(r, 5, QTableWidgetItem("✓ Done" if ok else "✗ Failed"))
            if ok and job_id in self.bars:
                self.bars[job_id].setValue(100)
        if job:
            if ok:
                self._log(f"✓ {job.direction}: {os.path.basename(job.local_path)}")
                if job.direction == "upload":
                    self.service.submit("list", path=self.remote_cwd)
                else:
                    self._refresh_local()
            else:
                self._log(f"✗ {job.direction} failed: {message}")

    # ---- misc ----
    def _log(self, text: str) -> None:
        self.log.appendPlainText(text)

    def shutdown(self) -> None:
        self.service.stop()
        self.service.wait(2000)
