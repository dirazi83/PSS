"""FTP Client tab — dual-pane browser, full file management, transfer manager.

Features: back/forward/up navigation, path bar, multi-select, right-click
context menus, upload/download of files *and* folders, mkdir/rename/delete,
a transfer queue with cancel/retry/clear/pause, plus an Advanced mode that
unlocks a raw FTP command bar, chmod permissions, hidden files and recursive
delete.
"""

from __future__ import annotations

import os
import posixpath
import shutil
import time

from PySide6.QtCore import QMimeData, Qt, QUrl, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFrame, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QSplitter, QStyle, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..shared.config import config
from ..shared.formatting import human_size
from ..shared.theme import Palette
from .ftp_engine import Entry, FtpOptions, FtpService, TransferJob
from .site_dialog import SiteManagerDialog
from .sites import Site, SiteManager

CFG = "ftp"


def list_local(path: str, show_hidden: bool = True) -> list[Entry]:
    entries: list[Entry] = []
    try:
        names = os.listdir(path)
    except OSError:
        return entries
    for name in names:
        if not show_hidden and name.startswith("."):
            continue
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


def dir_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


class FileTable(QTableWidget):
    """File list that can be a drag *source* (emits file:// URLs of the selected
    rows) and/or a drop *target* (accepts dropped file URLs).

    This is what makes "drag local files onto the remote pane to upload" work,
    for drags coming from the local pane *or* straight from the OS file manager.
    """

    filesDropped = Signal(list)        # list[str] of local paths dropped here

    def __init__(self, parent=None) -> None:
        super().__init__(0, 3, parent)
        self._path_provider = None     # callable(row) -> local abs path | None
        self._accept_drops = False

    def enable_drag(self, provider) -> None:
        self._path_provider = provider
        self.setDragEnabled(True)

    def enable_drop(self) -> None:
        self._accept_drops = True
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)

    # ---- drag source ----
    def startDrag(self, _actions) -> None:
        if not self._path_provider:
            return
        rows = sorted({i.row() for i in self.selectionModel().selectedRows()})
        urls = []
        for r in rows:
            p = self._path_provider(r)
            if p:
                urls.append(QUrl.fromLocalFile(p))
        if not urls:
            return
        mime = QMimeData()
        mime.setUrls(urls)
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.CopyAction)

    # ---- drop target ----
    def dragEnterEvent(self, e) -> None:
        if self._accept_drops and e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e) -> None:
        if self._accept_drops and e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e) -> None:
        if self._accept_drops and e.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in e.mimeData().urls() if u.toLocalFile()]
            if paths:
                self.filesDropped.emit(paths)
                e.acceptProposedAction()
                return
        super().dropEvent(e)


class FtpClientTab(QWidget):
    QUEUE_COLS = ["File", "Direction", "Size", "Progress", "Speed", "ETA", "Status"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.manager = SiteManager()
        self.service = FtpService(self)
        self.service.start()
        self._wire_service()

        self.advanced = bool(config.get(CFG, "advanced", False))
        self.local_cwd = config.get(CFG, "local_dir", "") or os.path.expanduser("~")
        self.remote_cwd = "/"
        self.local_entries: list[Entry] = []
        self.remote_entries: list[Entry] = []
        self.local_back: list[str] = []
        self.local_fwd: list[str] = []
        self.remote_back: list[str] = []
        self.remote_fwd: list[str] = []
        self._local_sort: tuple[int, bool] = (0, True)    # (column, ascending)
        self._remote_sort: tuple[int, bool] = (0, True)
        self._dir_icon = self.style().standardIcon(QStyle.SP_DirIcon)
        self._file_icon = self.style().standardIcon(QStyle.SP_FileIcon)
        self.queue_jobs: list[TransferJob] = []
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
        self._apply_advanced()
        self._update_nav_buttons()

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
        self.cb_advanced = QCheckBox("Advanced")
        self.cb_advanced.setToolTip("Unlock power tools: raw FTP command, "
                                    "permissions (chmod), hidden files and "
                                    "recursive delete.")
        self.cb_advanced.setChecked(self.advanced)
        self.cb_advanced.toggled.connect(self.on_toggle_advanced)
        for w in (QLabel("Site:"), self.site_combo, self.btn_connect,
                  self.btn_disconnect, self.btn_sites):
            bar.addWidget(w)
        bar.addStretch(1)
        for w in (self.cb_advanced, self.btn_upload, self.btn_download,
                  self.btn_refresh):
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

        nav = QHBoxLayout()
        nav.setSpacing(4)
        back = QPushButton("◀")
        fwd = QPushButton("▶")
        up = QPushButton("↑")
        refresh = QPushButton("⟳")
        for b in (back, fwd, up, refresh):
            b.setFixedWidth(34)
        path_edit = QLineEdit()
        nav.addWidget(back)
        nav.addWidget(fwd)
        nav.addWidget(up)
        nav.addWidget(path_edit, stretch=1)
        nav.addWidget(refresh)
        lay.addLayout(nav)

        table = FileTable()
        table.setHorizontalHeaderLabels(["Name", "Size", "Modified"])
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setShowGrid(False)
        table.setAlternatingRowColors(True)
        table.setContextMenuPolicy(Qt.CustomContextMenu)
        # click a header to sort; click again to reverse
        table.horizontalHeader().setSectionsClickable(True)
        table.horizontalHeader().setSortIndicatorShown(True)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        lay.addWidget(table, stretch=1)
        return frame, table, path_edit, back, fwd, up, refresh

    def _build_local_pane(self) -> QFrame:
        (frame, self.local_table, self.local_path, back, fwd, up,
         refresh) = self._pane("LOCAL  ·  this computer")
        back.clicked.connect(self._local_back)
        fwd.clicked.connect(self._local_forward)
        up.clicked.connect(self.on_local_up)
        refresh.clicked.connect(self._refresh_local)
        self.local_back_btn, self.local_fwd_btn = back, fwd
        self.local_path.returnPressed.connect(
            lambda: self._local_go(self.local_path.text().strip()))
        self.local_table.itemDoubleClicked.connect(self._on_local_double)
        self.local_table.customContextMenuRequested.connect(self._local_menu)
        self.local_table.horizontalHeader().sectionClicked.connect(self._sort_local)
        # local pane is a drag source: drag selected files onto the remote pane
        self.local_table.enable_drag(
            lambda r: os.path.join(self.local_cwd, self.local_entries[r].name)
            if 0 <= r < len(self.local_entries) else None)
        return frame

    def _build_remote_pane(self) -> QFrame:
        (frame, self.remote_table, self.remote_path, back, fwd, up,
         refresh) = self._pane("REMOTE  ·  FTP server")
        back.clicked.connect(self._remote_back_nav)
        fwd.clicked.connect(self._remote_forward_nav)
        up.clicked.connect(self.on_remote_up)
        refresh.clicked.connect(
            lambda: self._connected and self.service.submit("list", path=self.remote_cwd))
        self.remote_back_btn, self.remote_fwd_btn = back, fwd
        self.remote_path.returnPressed.connect(
            lambda: self._remote_go(self.remote_path.text().strip()))
        self.remote_table.itemDoubleClicked.connect(self._on_remote_double)
        self.remote_table.customContextMenuRequested.connect(self._remote_menu)
        self.remote_table.horizontalHeader().sectionClicked.connect(self._sort_remote)
        # remote pane is a drop target: drop OS files or local-pane items to upload
        self.remote_table.enable_drop()
        self.remote_table.filesDropped.connect(self._on_remote_drop)

        # advanced: raw FTP command bar (hidden unless Advanced is on)
        self.raw_row = QWidget()
        raw_lay = QHBoxLayout(self.raw_row)
        raw_lay.setContentsMargins(0, 0, 0, 0)
        raw_lay.setSpacing(6)
        self.raw_input = QLineEdit()
        self.raw_input.setPlaceholderText("Raw FTP command, e.g.  SITE CHMOD 777 /data")
        self.raw_input.returnPressed.connect(self.on_raw_command)
        raw_send = QPushButton("Send")
        raw_send.clicked.connect(self.on_raw_command)
        raw_lay.addWidget(QLabel("FTP ›"))
        raw_lay.addWidget(self.raw_input, stretch=1)
        raw_lay.addWidget(raw_send)
        frame.layout().addWidget(self.raw_row)
        return frame

    # ============================================================ queue
    def _build_queue(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Panel")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        head_row = QHBoxLayout()
        head = QLabel("TRANSFER QUEUE")
        head.setObjectName("SectionTitle")
        head_row.addWidget(head)
        head_row.addStretch(1)
        self.btn_pause = QPushButton("Pause")
        self.btn_pause.clicked.connect(self.on_pause_toggle)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.on_cancel_selected)
        btn_retry = QPushButton("Retry")
        btn_retry.clicked.connect(self.on_retry_selected)
        btn_clear = QPushButton("Clear finished")
        btn_clear.clicked.connect(self.on_clear_finished)
        for b in (self.btn_pause, btn_cancel, btn_retry, btn_clear):
            head_row.addWidget(b)
        lay.addLayout(head_row)

        self.queue = QTableWidget(0, len(self.QUEUE_COLS))
        self.queue.setHorizontalHeaderLabels(self.QUEUE_COLS)
        self.queue.verticalHeader().setVisible(False)
        self.queue.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.queue.setSelectionBehavior(QAbstractItemView.SelectRows)
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
        self.service.op_done.connect(self._on_op_done)
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
            QMessageBox.information(self, "No host", "This site has no host set.")
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
        self.remote_back.clear()
        self.remote_fwd.clear()
        site = getattr(self, "_pending_site", None)
        if ok and site:
            if site.local_dir and os.path.isdir(site.local_dir):
                self._local_go(site.local_dir, record=False)
            if site.remote_dir:
                self.service.submit("list", path=site.remote_dir)
            self.status.setText(f"Connected · {site.host}")
        self._update_nav_buttons()

    def _on_disconnected(self) -> None:
        self._connected = False
        self.btn_connect.setEnabled(True)
        self.btn_disconnect.setEnabled(False)
        self.remote_table.setRowCount(0)
        self.remote_entries = []
        self.status.setText("Not connected")
        self._update_nav_buttons()

    # ---- remote navigation ----
    def _remote_go(self, path: str, record: bool = True) -> None:
        if not self._connected:
            return
        path = path or "/"
        if record and path != self.remote_cwd:
            self.remote_back.append(self.remote_cwd)
            self.remote_fwd.clear()
        self.service.submit("list", path=path)

    def _remote_back_nav(self) -> None:
        if self.remote_back:
            self.remote_fwd.append(self.remote_cwd)
            self._remote_go(self.remote_back.pop(), record=False)

    def _remote_forward_nav(self) -> None:
        if self.remote_fwd:
            self.remote_back.append(self.remote_cwd)
            self._remote_go(self.remote_fwd.pop(), record=False)

    def on_remote_up(self) -> None:
        if not self._connected:
            return
        self._remote_go(posixpath.dirname(self.remote_cwd.rstrip("/")) or "/")

    def _on_listed(self, path: str, entries, error: str) -> None:
        if error:
            self._log(f"List failed: {error}")
            QMessageBox.warning(self, "Listing failed", error)
            return
        self.remote_cwd = path
        if not self.advanced:
            entries = [e for e in entries if not e.name.startswith(".")]
        self.remote_entries = self._apply_sort(entries, self._remote_sort)
        self.remote_path.setText(path)
        self._fill_table(self.remote_table, self.remote_entries)
        self._update_nav_buttons()

    def _on_remote_double(self, item: QTableWidgetItem) -> None:
        e = self.remote_entries[item.row()]
        if e.is_dir:
            self._remote_go(posixpath.normpath(posixpath.join(self.remote_cwd, e.name)))

    # ---- local navigation ----
    def _local_go(self, path: str, record: bool = True) -> None:
        if not os.path.isdir(path):
            return
        if record and os.path.abspath(path) != os.path.abspath(self.local_cwd):
            self.local_back.append(self.local_cwd)
            self.local_fwd.clear()
        self.local_cwd = path
        config.set(CFG, "local_dir", path)
        self._refresh_local()
        self._update_nav_buttons()

    def _local_back(self) -> None:
        if self.local_back:
            self.local_fwd.append(self.local_cwd)
            self._local_go(self.local_back.pop(), record=False)

    def _local_forward(self) -> None:
        if self.local_fwd:
            self.local_back.append(self.local_cwd)
            self._local_go(self.local_fwd.pop(), record=False)

    def on_local_up(self) -> None:
        self._local_go(os.path.dirname(self.local_cwd.rstrip(os.sep)) or self.local_cwd)

    def _refresh_local(self) -> None:
        entries = list_local(self.local_cwd, show_hidden=self.advanced)
        self.local_entries = self._apply_sort(entries, self._local_sort)
        self.local_path.setText(self.local_cwd)
        self._fill_table(self.local_table, self.local_entries)

    def _on_local_double(self, item: QTableWidgetItem) -> None:
        e = self.local_entries[item.row()]
        if e.is_dir:
            self._local_go(os.path.join(self.local_cwd, e.name))

    def _update_nav_buttons(self) -> None:
        self.local_back_btn.setEnabled(bool(self.local_back))
        self.local_fwd_btn.setEnabled(bool(self.local_fwd))
        self.remote_back_btn.setEnabled(self._connected and bool(self.remote_back))
        self.remote_fwd_btn.setEnabled(self._connected and bool(self.remote_fwd))

    # ---- shared table fill ----
    def _fill_table(self, table: QTableWidget, entries: list[Entry]) -> None:
        table.setRowCount(0)
        for e in entries:
            r = table.rowCount()
            table.insertRow(r)
            # Name cell text is JUST the name (icon via setIcon) so keyboard
            # type-ahead — jump to a file by typing its first letters — works.
            name = QTableWidgetItem(e.name)
            name.setIcon(self._dir_icon if e.is_dir else self._file_icon)
            table.setItem(r, 0, name)
            size = QTableWidgetItem("" if e.is_dir else human_size(e.size))
            size.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            table.setItem(r, 1, size)
            table.setItem(r, 2, QTableWidgetItem(e.modified))

    # ---- column sorting (folders first, then the chosen key) ----
    @staticmethod
    def _apply_sort(entries: list[Entry], sort: tuple[int, bool]) -> list[Entry]:
        col, asc = sort
        if col == 1:
            key = lambda e: e.size
        elif col == 2:
            key = lambda e: e.modified
        else:
            key = lambda e: e.name.lower()
        # keep directories grouped above files, then sort within each group
        dirs = sorted((e for e in entries if e.is_dir), key=key, reverse=not asc)
        files = sorted((e for e in entries if not e.is_dir), key=key, reverse=not asc)
        return dirs + files

    def _toggle_sort(self, cur: tuple[int, bool], col: int) -> tuple[int, bool]:
        return (col, not cur[1]) if cur[0] == col else (col, True)

    def _sort_local(self, col: int) -> None:
        self._local_sort = self._toggle_sort(self._local_sort, col)
        self.local_entries = self._apply_sort(self.local_entries, self._local_sort)
        self.local_table.horizontalHeader().setSortIndicator(
            col, Qt.AscendingOrder if self._local_sort[1] else Qt.DescendingOrder)
        self._fill_table(self.local_table, self.local_entries)

    def _sort_remote(self, col: int) -> None:
        self._remote_sort = self._toggle_sort(self._remote_sort, col)
        self.remote_entries = self._apply_sort(self.remote_entries, self._remote_sort)
        self.remote_table.horizontalHeader().setSortIndicator(
            col, Qt.AscendingOrder if self._remote_sort[1] else Qt.DescendingOrder)
        self._fill_table(self.remote_table, self.remote_entries)

    def on_refresh(self) -> None:
        self._refresh_local()
        if self._connected:
            self.service.submit("list", path=self.remote_cwd)

    # ---- selection helpers ----
    @staticmethod
    def _selected_rows(table: QTableWidget) -> list[int]:
        return sorted({i.row() for i in table.selectionModel().selectedRows()})

    def _selected_local(self) -> list[Entry]:
        return [self.local_entries[r] for r in self._selected_rows(self.local_table)
                if 0 <= r < len(self.local_entries)]

    def _selected_remote(self) -> list[Entry]:
        return [self.remote_entries[r] for r in self._selected_rows(self.remote_table)
                if 0 <= r < len(self.remote_entries)]

    # =============================================================== context menus
    def _local_menu(self, pos) -> None:
        row = self.local_table.indexAt(pos).row()
        if row >= 0 and row not in self._selected_rows(self.local_table):
            self.local_table.selectRow(row)
        sel = self._selected_local()
        menu = QMenu(self)
        act_up = menu.addAction("Upload →")
        act_up.setEnabled(self._connected and bool(sel))
        menu.addSeparator()
        menu.addAction("New Folder…", self.on_local_mkdir)
        act_ren = menu.addAction("Rename…", self.on_local_rename)
        act_ren.setEnabled(len(sel) == 1)
        act_del = menu.addAction("Delete", self.on_local_delete)
        act_del.setEnabled(bool(sel))
        menu.addSeparator()
        menu.addAction("Refresh", self._refresh_local)
        chosen = menu.exec(self.local_table.viewport().mapToGlobal(pos))
        if chosen is act_up:
            self.on_upload()

    def _remote_menu(self, pos) -> None:
        if not self._connected:
            return
        row = self.remote_table.indexAt(pos).row()
        if row >= 0 and row not in self._selected_rows(self.remote_table):
            self.remote_table.selectRow(row)
        sel = self._selected_remote()
        menu = QMenu(self)
        act_dl = menu.addAction("← Download")
        act_dl.setEnabled(bool(sel))
        menu.addSeparator()
        menu.addAction("New Folder…", self.on_remote_mkdir)
        act_ren = menu.addAction("Rename…", self.on_remote_rename)
        act_ren.setEnabled(len(sel) == 1)
        act_del = menu.addAction("Delete", self.on_remote_delete)
        act_del.setEnabled(bool(sel))
        if self.advanced:
            menu.addSeparator()
            act_chmod = menu.addAction("Permissions (chmod)…", self.on_remote_chmod)
            act_chmod.setEnabled(len(sel) == 1)
            menu.addAction("Copy remote path", self.on_copy_remote_path)
        menu.addSeparator()
        menu.addAction("Refresh", lambda: self.service.submit("list", path=self.remote_cwd))
        chosen = menu.exec(self.remote_table.viewport().mapToGlobal(pos))
        if chosen is act_dl:
            self.on_download()

    # =============================================================== file ops
    def on_local_mkdir(self) -> None:
        name, ok = QInputDialog.getText(self, "New Folder", "Folder name:")
        if ok and name.strip():
            try:
                os.makedirs(os.path.join(self.local_cwd, name.strip()))
                self._refresh_local()
            except OSError as exc:
                QMessageBox.warning(self, "Create folder failed", str(exc))

    def on_local_rename(self) -> None:
        sel = self._selected_local()
        if len(sel) != 1:
            return
        old = sel[0].name
        new, ok = QInputDialog.getText(self, "Rename", "New name:", text=old)
        if ok and new.strip() and new.strip() != old:
            try:
                os.rename(os.path.join(self.local_cwd, old),
                          os.path.join(self.local_cwd, new.strip()))
                self._refresh_local()
            except OSError as exc:
                QMessageBox.warning(self, "Rename failed", str(exc))

    def on_local_delete(self) -> None:
        sel = self._selected_local()
        if not sel or not self._confirm_delete(sel, "local"):
            return
        for e in sel:
            full = os.path.join(self.local_cwd, e.name)
            try:
                if e.is_dir:
                    shutil.rmtree(full)
                else:
                    os.remove(full)
            except OSError as exc:
                QMessageBox.warning(self, "Delete failed", str(exc))
        self._refresh_local()

    def on_remote_mkdir(self) -> None:
        name, ok = QInputDialog.getText(self, "New Folder", "Folder name:")
        if ok and name.strip():
            self.service.submit("mkdir",
                                 path=posixpath.join(self.remote_cwd, name.strip()))

    def on_remote_rename(self) -> None:
        sel = self._selected_remote()
        if len(sel) != 1:
            return
        old = sel[0].name
        new, ok = QInputDialog.getText(self, "Rename", "New name:", text=old)
        if ok and new.strip() and new.strip() != old:
            self.service.submit(
                "rename",
                src=posixpath.join(self.remote_cwd, old),
                dst=posixpath.join(self.remote_cwd, new.strip()),
                parent=self.remote_cwd)

    def on_remote_delete(self) -> None:
        sel = self._selected_remote()
        if not sel or not self._confirm_delete(sel, "remote"):
            return
        for e in sel:
            self.service.submit(
                "delete", path=posixpath.join(self.remote_cwd, e.name),
                is_dir=e.is_dir, recursive=self.advanced, parent=self.remote_cwd)

    def on_remote_chmod(self) -> None:
        sel = self._selected_remote()
        if len(sel) != 1:
            return
        mode, ok = QInputDialog.getText(self, "Permissions",
                                        f"Octal mode for {sel[0].name}:", text="777")
        if ok and mode.strip():
            self.service.submit(
                "chmod", path=posixpath.join(self.remote_cwd, sel[0].name),
                mode=mode.strip(), parent=self.remote_cwd)

    def on_copy_remote_path(self) -> None:
        sel = self._selected_remote()
        if sel:
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(
                posixpath.join(self.remote_cwd, sel[0].name))
            self._log(f"Copied path: {posixpath.join(self.remote_cwd, sel[0].name)}")

    def on_raw_command(self) -> None:
        cmd = self.raw_input.text().strip()
        if not cmd:
            return
        if not self._connected:
            QMessageBox.information(self, "Not connected", "Connect first.")
            return
        self.service.submit("raw", command=cmd)
        self.raw_input.clear()

    def _confirm_delete(self, sel: list[Entry], where: str) -> bool:
        dirs = [e for e in sel if e.is_dir]
        names = ", ".join(e.name for e in sel[:5]) + (
            f" …(+{len(sel) - 5})" if len(sel) > 5 else "")
        warn = ""
        if dirs and where == "remote" and not self.advanced:
            warn = ("\n\nNote: folders are only removed if empty in safe mode. "
                    "Enable Advanced for recursive delete.")
        elif dirs and self.advanced:
            warn = "\n\n⚠ Folders and ALL their contents will be deleted."
        return QMessageBox.question(
            self, "Confirm delete",
            f"Delete {len(sel)} {where} item(s)?\n\n{names}{warn}",
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel
        ) == QMessageBox.Yes

    def _on_op_done(self, kind: str, ok: bool, message: str) -> None:
        if not ok:
            QMessageBox.warning(self, f"{kind} failed", message)
        elif kind == "raw":
            self._log(message)

    # =============================================================== transfers
    def on_upload(self) -> None:
        if not self._connected:
            QMessageBox.information(self, "Not connected", "Connect first.")
            return
        sel = self._selected_local()
        if not sel:
            QMessageBox.information(self, "Select items",
                                    "Pick file(s)/folder(s) in the LOCAL pane.")
            return
        for e in sel:
            local = os.path.join(self.local_cwd, e.name)
            remote = posixpath.join(self.remote_cwd, e.name)
            size = dir_size(local) if e.is_dir else e.size
            self._enqueue("upload", local, remote, size, e.name, e.is_dir)

    def on_download(self) -> None:
        if not self._connected:
            QMessageBox.information(self, "Not connected", "Connect first.")
            return
        sel = self._selected_remote()
        if not sel:
            QMessageBox.information(self, "Select items",
                                    "Pick file(s)/folder(s) in the REMOTE pane.")
            return
        for e in sel:
            remote = posixpath.join(self.remote_cwd, e.name)
            local = os.path.join(self.local_cwd, e.name)
            self._enqueue("download", local, remote, e.size, e.name, e.is_dir)

    def _on_remote_drop(self, paths: list[str]) -> None:
        """Files dropped onto the remote pane (from the OS or the local pane)
        are uploaded to the current remote directory."""
        if not self._connected:
            QMessageBox.information(self, "Not connected",
                                    "Connect to a server before uploading.")
            return
        added = 0
        for p in paths:
            if not os.path.exists(p):
                continue
            name = os.path.basename(p.rstrip(os.sep))
            is_dir = os.path.isdir(p)
            remote = posixpath.join(self.remote_cwd, name)
            size = dir_size(p) if is_dir else os.path.getsize(p)
            self._enqueue("upload", p, remote, size, name, is_dir)
            added += 1
        if added:
            self._log(f"Uploading {added} dropped item(s) → {self.remote_cwd}")

    def _enqueue(self, direction: str, local: str, remote: str,
                 size: int, name: str, is_dir: bool) -> None:
        self._job_seq += 1
        job = TransferJob(self._job_seq, direction, local, remote, size,
                          is_dir=is_dir)
        self.jobs[job.job_id] = job
        self.queue_jobs.append(job)
        self._render_queue()
        self.service.submit("transfer", job=job)

    def _render_queue(self) -> None:
        self.queue.setRowCount(0)
        self.job_rows.clear()
        self.bars.clear()
        for job in self.queue_jobs:
            r = self.queue.rowCount()
            self.queue.insertRow(r)
            self.job_rows[job.job_id] = r
            folder = "📁 " if job.is_dir else ""
            arrow = "▲ upload" if job.direction == "upload" else "▼ download"
            self.queue.setItem(r, 0, QTableWidgetItem(folder + os.path.basename(
                job.local_path if job.direction == "upload" else job.remote_path)))
            self.queue.setItem(r, 1, QTableWidgetItem(arrow))
            self.queue.setItem(r, 2, QTableWidgetItem(
                human_size(job.size) if job.size else "—"))
            bar = QProgressBar()
            bar.setValue(int(job.sent / job.size * 100) if job.size else 0)
            self.queue.setCellWidget(r, 3, bar)
            self.bars[job.job_id] = bar
            self.queue.setItem(r, 4, QTableWidgetItem("—"))
            self.queue.setItem(r, 5, QTableWidgetItem("—"))
            self.queue.setItem(r, 6, self._status_cell(job.status))

    @staticmethod
    def _status_cell(text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        return item

    def _on_progress(self, job_id: int, sent: int, total: int) -> None:
        job = self.jobs.get(job_id)
        if not job:
            return
        job.sent = sent
        job.status = "Transferring"
        if job_id in self.bars and total:
            self.bars[job_id].setValue(int(sent / total * 100))
        r = self.job_rows.get(job_id)
        if r is not None:
            elapsed = max(time.time() - job.started, 1e-6)
            speed = sent / elapsed
            self.queue.setItem(r, 2, QTableWidgetItem(
                human_size(total) if total else "—"))
            self.queue.setItem(r, 4, QTableWidgetItem(f"{human_size(speed)}/s"))
            remaining = max(total - sent, 0)
            eta = remaining / speed if speed > 1 else 0
            self.queue.setItem(r, 5, QTableWidgetItem(
                self._fmt_eta(eta) if eta else "—"))
            self.queue.setItem(r, 6, self._status_cell("Transferring"))

    @staticmethod
    def _fmt_eta(seconds: float) -> str:
        seconds = int(seconds)
        if seconds < 60:
            return f"{seconds}s"
        if seconds < 3600:
            return f"{seconds // 60}m {seconds % 60}s"
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"

    def _on_transfer_done(self, job_id: int, ok: bool, message: str) -> None:
        job = self.jobs.get(job_id)
        r = self.job_rows.get(job_id)
        cancelled = message == "cancelled"
        status = "✓ Done" if ok else ("■ Cancelled" if cancelled else "✗ Failed")
        if job:
            job.status = status
        if r is not None:
            self.queue.setItem(r, 6, self._status_cell(status))
            if ok and job_id in self.bars:
                self.bars[job_id].setValue(100)
        if job:
            label = os.path.basename(job.local_path)
            if ok:
                self._log(f"✓ {job.direction}: {label}")
                if job.direction == "upload":
                    self.service.submit("list", path=self.remote_cwd)
                else:
                    self._refresh_local()
            elif cancelled:
                self._log(f"■ cancelled: {label}")
            else:
                self._log(f"✗ {job.direction} failed: {message}")

    # ---- queue controls ----
    def on_cancel_selected(self) -> None:
        rows = self._selected_rows(self.queue)
        targets = [self.queue_jobs[r] for r in rows if 0 <= r < len(self.queue_jobs)]
        if not targets:                          # nothing selected → cancel all active
            targets = [j for j in self.queue_jobs
                       if j.status in ("Queued", "Transferring")]
        for job in targets:
            if job.status in ("Queued", "Transferring"):
                self.service.cancel(job.job_id)
                job.status = "■ Cancelled"
                r = self.job_rows.get(job.job_id)
                if r is not None:
                    self.queue.setItem(r, 6, self._status_cell("■ Cancelled"))

    def on_retry_selected(self) -> None:
        rows = self._selected_rows(self.queue)
        targets = [self.queue_jobs[r] for r in rows if 0 <= r < len(self.queue_jobs)]
        if not targets:
            targets = [j for j in self.queue_jobs
                       if j.status.startswith(("✗", "■"))]
        for old in targets:
            if not old.status.startswith(("✗", "■")):
                continue
            self._job_seq += 1
            new = TransferJob(self._job_seq, old.direction, old.local_path,
                              old.remote_path, old.size, is_dir=old.is_dir)
            self.jobs[new.job_id] = new
            idx = self.queue_jobs.index(old)
            self.queue_jobs[idx] = new
            del self.jobs[old.job_id]
            self.service.submit("transfer", job=new)
        self._render_queue()

    def on_clear_finished(self) -> None:
        self.queue_jobs = [j for j in self.queue_jobs
                           if not j.status.startswith(("✓", "✗", "■"))]
        self.jobs = {j.job_id: j for j in self.queue_jobs}
        self._render_queue()

    def on_pause_toggle(self) -> None:
        if self.service.paused:
            self.service.resume()
            self.btn_pause.setText("Pause")
            self._log("Transfers resumed.")
        else:
            self.service.pause()
            self.btn_pause.setText("Resume")
            self._log("Transfers paused (current file finishes first).")

    # =============================================================== advanced
    def on_toggle_advanced(self, on: bool) -> None:
        self.advanced = on
        config.set(CFG, "advanced", on)
        self._apply_advanced()
        self._refresh_local()
        if self._connected:
            self.service.submit("list", path=self.remote_cwd)

    def _apply_advanced(self) -> None:
        self.raw_row.setVisible(self.advanced)
        self.status.setText(self.status.text())

    # ---- misc ----
    def _log(self, text: str) -> None:
        self.log.appendPlainText(text)

    def shutdown(self) -> None:
        self.service.cancel_all()
        self.service.stop()
        self.service.wait(2000)
