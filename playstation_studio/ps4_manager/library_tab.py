"""PKG Manager tab: browse, inspect, rename, export, remote-install."""

from __future__ import annotations

import os
import socket
import time

from PySide6.QtCore import QSortFilterProxyModel, Qt, QThread, Signal
from PySide6.QtGui import QImage, QPixmap, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSpinBox,
    QStackedWidget, QTableView, QTabWidget, QVBoxLayout, QWidget,
)

from .pkg_parser import PkgInfo, get_pkg_info, iter_pkg_files
from .remote_install import (
    INSTALL_METHODS, METHOD_PS4_RPI, ExploitHost, FolderHttpServer,
    RemoteInstaller, TestConnectivity, method_api_port,
)
from .rename import BulkRenamer
from ..shared.config import config
from ..shared.detect_dialog import detect_console
from ..shared.formatting import human_size
from ..shared.theme import Palette

CFG = "ps4"

# columns: 0 is a checkbox used to queue for install
COLS = ["", "TITLE_ID", "TITLE", "CONTENT_ID", "VERSION", "CATEGORY",
        "SIZE", "REGION", "SYS_VER", "LANGUAGES", "PATH"]
PATH_COL = COLS.index("PATH")


def local_ip() -> str:
    """Best-effort LAN IP of this machine."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


class ScanWorker(QThread):
    found = Signal(object)      # PkgInfo
    done = Signal(int, bool)    # count, cancelled

    def __init__(self, root: str, parent=None) -> None:
        super().__init__(parent)
        self.root = root
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        n = 0
        for path in iter_pkg_files(self.root):
            if self._cancel:
                break
            info = get_pkg_info(path)
            if info is not None:
                self.found.emit(info)
                n += 1
        self.done.emit(n, self._cancel)


class RenameDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Bulk rename .pkg files")
        self.setMinimumWidth(440)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Filename template — available tokens:"))
        tokens = QLabel("[TITLE]  [TITLE_ID]  [SIZE]  [CATEGORY]  [SYS_VER]  [VER]")
        tokens.setStyleSheet(f"color:{Palette.accent}; font-weight:600;")
        lay.addWidget(tokens)
        self.template = QLineEdit("[TITLE] [[TITLE_ID]] [VER]")
        lay.addWidget(self.template)
        self.no_spaces = QCheckBox("Replace spaces with dashes")
        lay.addWidget(self.no_spaces)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)


class Ps4LibraryTab(QWidget):
    CATEGORIES = ("Game", "Update", "DLC")

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.infos: dict[str, PkgInfo] = {}
        self.models: dict[str, QStandardItemModel] = {}
        self.proxies: dict[str, QSortFilterProxyModel] = {}
        self.views: dict[str, QTableView] = {}
        self._server: FolderHttpServer | None = None
        self._server_wired = False
        self._exploit: ExploitHost | None = None
        self._scan: ScanWorker | None = None
        self._scanning = False
        self.scanned_root = ""
        self._installer: RemoteInstaller | None = None
        self._installing = False     # an install run is pending or active
        self._install_bars: dict[int, QProgressBar] = {}
        self._dl_rows: dict[str, int] = {}      # served rel-path -> install row
        self._dl_start: dict[int, float] = {}   # row -> download start time
        self._install_rows: list[int] = []      # installer index -> model row
        self._syncing = False        # guard while mirroring related checks

        body = QHBoxLayout(self)
        body.setContentsMargins(18, 14, 18, 10)
        body.setSpacing(16)
        body.addLayout(self._build_main_column(), stretch=1)
        body.addWidget(self._build_side_panel())

    # ----------------------------------------------------------- main column
    def _build_main_column(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(12)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.path_edit = QLineEdit(config.get(CFG, "folder", ""))
        self.path_edit.setPlaceholderText("Folder containing your .pkg files…")
        self.path_edit.editingFinished.connect(
            lambda: config.set(CFG, "folder", self.path_edit.text().strip()))
        btn_browse = QPushButton("Browse")
        btn_browse.clicked.connect(self.on_browse)
        self.btn_scan = QPushButton("⊕  Scan")
        self.btn_scan.setObjectName("Primary")
        self.btn_scan.clicked.connect(self.on_scan_clicked)
        bar.addWidget(self.path_edit, stretch=1)
        bar.addWidget(btn_browse)
        bar.addWidget(self.btn_scan)
        col.addLayout(bar)

        bar2 = QHBoxLayout()
        bar2.setSpacing(8)
        self.cb_all = QCheckBox("Select all")
        self.cb_all.setToolTip("Check / uncheck every item in the current list.")
        self.cb_all.toggled.connect(self.on_select_all)
        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍  Filter the current list…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        self.btn_rename = QPushButton("Rename…")
        self.btn_rename.clicked.connect(self.on_rename)
        self.btn_export = QPushButton("Export Excel")
        self.btn_export.clicked.connect(self.on_export)
        bar2.addWidget(self.cb_all)
        bar2.addWidget(self.search, stretch=1)
        bar2.addWidget(self.btn_rename)
        bar2.addWidget(self.btn_export)
        col.addLayout(bar2)

        # category sub-tabs
        self.sub = QTabWidget()
        for cat in self.CATEGORIES:
            self.sub.addTab(self._build_table(cat), f"{cat}s")
        self.sub.addTab(self._build_install_tab(), "Install")
        self.sub.currentChanged.connect(self._on_subtab_changed)
        col.addWidget(self.sub, stretch=3)

        # log
        title = QLabel("OUTPUT LOG")
        title.setObjectName("SectionTitle")
        col.addWidget(title)
        self.log = QPlainTextEdit()
        self.log.setObjectName("Log")
        self.log.setReadOnly(True)
        self.log.setFixedHeight(110)
        col.addWidget(self.log)
        return col

    def _build_table(self, cat: str) -> QWidget:
        model = QStandardItemModel()
        model.setHorizontalHeaderLabels(COLS)
        proxy = QSortFilterProxyModel()
        proxy.setSourceModel(model)
        proxy.setFilterKeyColumn(-1)
        proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)

        view = QTableView()
        view.setModel(proxy)
        view.setSortingEnabled(True)
        view.setSelectionBehavior(QAbstractItemView.SelectRows)
        view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        view.setAlternatingRowColors(True)
        view.verticalHeader().setVisible(False)
        view.setColumnWidth(0, 28)
        view.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        view.setColumnHidden(PATH_COL, True)
        view.selectionModel().selectionChanged.connect(
            lambda *_: self._show_info(cat))
        model.itemChanged.connect(self._on_item_checked)

        self.models[cat] = model
        self.proxies[cat] = proxy
        self.views[cat] = view
        return view

    def _build_install_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 8, 0, 0)
        self.install_model = QStandardItemModel()
        self.install_model.setHorizontalHeaderLabels(
            ["TITLE_ID", "TITLE", "TYPE", "SIZE", "Status", "Progress", "PATH"])
        self.install_view = QTableView()
        self.install_view.setModel(self.install_model)
        self.install_view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.install_view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.install_view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.install_view.verticalHeader().setVisible(False)
        self.install_view.setColumnHidden(6, True)
        self.install_view.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        lay.addWidget(self.install_view)

        row = QHBoxLayout()
        self.btn_remove_sel = QPushButton("Remove Selected")
        self.btn_remove_sel.setObjectName("Ghost")
        self.btn_remove_sel.clicked.connect(self.on_remove_selected)
        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setObjectName("Ghost")
        self.btn_clear.clicked.connect(self._clear_install)
        self.btn_install_sel = QPushButton("▶  Install Selected")
        self.btn_install_sel.clicked.connect(self.on_install_selected)
        self.btn_install = QPushButton("▶  Install All")
        self.btn_install.setObjectName("Primary")
        self.btn_install.clicked.connect(self.on_install_all)
        row.addWidget(self.btn_remove_sel)
        row.addWidget(self.btn_clear)
        row.addStretch(1)
        row.addWidget(self.btn_install_sel)
        row.addWidget(self.btn_install)
        lay.addLayout(row)
        return w

    # ------------------------------------------------------------ side panel
    def _build_side_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("Panel")
        panel.setFixedWidth(330)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)

        lay.addWidget(self._section("COVER ART"))
        self.cover = QLabel()
        self.cover.setObjectName("Cover")
        self.cover.setFixedHeight(180)
        self.cover.setAlignment(Qt.AlignCenter)
        self.cover.setText("no selection")
        lay.addWidget(self.cover)

        lay.addWidget(self._section("DETAILS"))
        self.info_model = QStandardItemModel()
        self.info_model.setHorizontalHeaderLabels(["Field", "Value"])
        self.info_view = QTableView()
        self.info_view.setModel(self.info_model)
        self.info_view.verticalHeader().setVisible(False)
        self.info_view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.info_view.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.info_view, stretch=1)

        lay.addWidget(self._section("REMOTE INSTALL"))
        form = QVBoxLayout()
        form.setSpacing(6)
        form.addWidget(self._field_label("Install method"))
        self.method = QComboBox()
        for key, label in INSTALL_METHODS:
            self.method.addItem(label, key)
        saved_method = config.get(CFG, "install_method", METHOD_PS4_RPI)
        idx = self.method.findData(saved_method)
        if idx >= 0:
            self.method.setCurrentIndex(idx)
        self.method.currentIndexChanged.connect(
            lambda *_: config.set(CFG, "install_method", self.method.currentData()))
        form.addWidget(self.method)
        self.ps4_ip = QLineEdit(config.get(CFG, "ps4_ip", ""))
        self.ps4_ip.setPlaceholderText("Console IP  (PS4 or PS5, e.g. 192.168.1.20)")
        self.ps4_ip.editingFinished.connect(
            lambda: config.set(CFG, "ps4_ip", self.ps4_ip.text().strip()))
        ip_row = QHBoxLayout()
        ip_row.setSpacing(6)
        self.btn_detect = QPushButton("Auto-Detect")
        self.btn_detect.setToolTip("Scan the network for a PS4/PS5 and fill the IP.")
        self.btn_detect.clicked.connect(self.on_auto_detect)
        ip_row.addWidget(self.ps4_ip, stretch=1)
        ip_row.addWidget(self.btn_detect)
        form.addLayout(ip_row)
        port_row = QHBoxLayout()
        self.server_ip = QComboBox()
        self.server_ip.addItem(local_ip())
        self.server_ip.setEditable(True)
        saved_server = config.get(CFG, "server_ip", "")
        if saved_server:
            self.server_ip.setCurrentText(saved_server)
        self.server_ip.editTextChanged.connect(
            lambda t: config.set(CFG, "server_ip", t.strip()))
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(int(config.get(CFG, "port", 9999)))
        self.port.valueChanged.connect(lambda v: config.set(CFG, "port", v))
        port_row.addWidget(QLabel("Serve from"))
        port_row.addWidget(self.server_ip, stretch=1)
        port_row.addWidget(self.port)
        form.addLayout(port_row)

        btn_row = QHBoxLayout()
        self.btn_test = QPushButton("Test")
        self.btn_test.setToolTip("Check the console is reachable on the selected "
                                 "method's port.")
        self.btn_test.clicked.connect(self.on_test)
        self.btn_exploit = QPushButton("Start Exploit Host")
        self.btn_exploit.setObjectName("Ghost")
        self.btn_exploit.clicked.connect(self.on_toggle_exploit)
        btn_row.addWidget(self.btn_test)
        btn_row.addWidget(self.btn_exploit)
        form.addLayout(btn_row)

        self.conn_lbl = QLabel("Not tested")
        self.conn_lbl.setStyleSheet(f"color:{Palette.text_dim}; font-size:11px;")
        form.addWidget(self.conn_lbl)
        lay.addLayout(form)
        return panel

    def _section(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("SectionTitle")
        return lbl

    def _field_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color:{Palette.text_dim}; font-size:12px; font-weight:600;")
        return lbl

    # =============================================================== actions
    def on_browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Select folder of .pkg files")
        if d:
            self.path_edit.setText(d)
            config.set(CFG, "folder", d)

    def on_scan_clicked(self) -> None:
        """Scan button doubles as a Stop button while a scan is running."""
        if self._scanning:
            self.on_stop_scan()
        else:
            self.on_scan()

    def on_scan(self) -> None:
        root = self.path_edit.text().strip()
        if not os.path.isdir(root):
            QMessageBox.information(self, "Pick a folder",
                                    "Choose a valid folder that contains .pkg files.")
            return
        for cat in self.CATEGORIES:
            self.models[cat].removeRows(0, self.models[cat].rowCount())
        self.infos.clear()
        self.scanned_root = root
        self._set_scanning(True)
        self._log(f"Scanning {root} …")
        self._scan = ScanWorker(root, self)
        self._scan.found.connect(self._add_info)
        self._scan.done.connect(self._scan_done)
        self._scan.start()

    def on_stop_scan(self) -> None:
        if self._scan is not None and self._scan.isRunning():
            self._scan.cancel()
            self.btn_scan.setEnabled(False)   # re-enabled in _scan_done
            self._log("Stopping scan…")

    def _set_scanning(self, scanning: bool) -> None:
        self._scanning = scanning
        self.btn_scan.setEnabled(True)
        self.btn_scan.setText("■  Stop" if scanning else "⊕  Scan")
        self.btn_scan.setObjectName("Danger" if scanning else "Primary")
        # re-apply the stylesheet for the new objectName
        self.btn_scan.style().unpolish(self.btn_scan)
        self.btn_scan.style().polish(self.btn_scan)

    def _add_info(self, info: PkgInfo) -> None:
        self.infos[os.path.normpath(info.path)] = info
        cat = info.category_label
        model = self.models.get(cat)
        if model is None:        # unknown category → bucket into Game
            model = self.models["Game"]
        row = info.as_row()
        check = QStandardItem()
        check.setCheckable(True)
        items = [check] + [QStandardItem(row.get(c, "")) for c in COLS[1:]]
        model.appendRow(items)
        self._refresh_counts()

    def _scan_done(self, n: int, cancelled: bool) -> None:
        self._set_scanning(False)
        for v in self.views.values():
            v.resizeColumnsToContents()
            v.setColumnHidden(PATH_COL, True)
        self._refresh_counts()
        if cancelled:
            self._log(f"Scan stopped — {n} package(s) found so far.")
        else:
            self._log(f"Scan complete — {n} package(s) found.")

    def _refresh_counts(self) -> None:
        for i, cat in enumerate(self.CATEGORIES):
            self.sub.setTabText(i, f"{cat}s [{self.models[cat].rowCount()}]")
        self.sub.setTabText(3, f"Install [{self.install_model.rowCount()}]")

    def _apply_filter(self, *_) -> None:
        text = self.search.text()
        for proxy in self.proxies.values():
            proxy.setFilterFixedString(text)

    def _on_subtab_changed(self, *_) -> None:
        # "Select all" is per-list, so reset it when the list changes.
        self.cb_all.blockSignals(True)
        self.cb_all.setChecked(False)
        self.cb_all.blockSignals(False)
        self.cb_all.setEnabled(self._current_cat() is not None)
        self._apply_filter()

    def on_select_all(self, checked: bool) -> None:
        cat = self._current_cat()
        if cat is None:
            return
        target = Qt.Checked if checked else Qt.Unchecked
        model = self.models[cat]
        for r in range(model.rowCount()):
            cell = model.item(r, 0)
            if cell.checkState() != target:
                cell.setCheckState(target)

    def _current_cat(self) -> str | None:
        idx = self.sub.currentIndex()
        return self.CATEGORIES[idx] if idx < len(self.CATEGORIES) else None

    def _show_info(self, cat: str) -> None:
        view = self.views[cat]
        rows = view.selectionModel().selectedRows()
        if not rows:
            return
        src = self.proxies[cat].mapToSource(rows[0])
        path = self.models[cat].item(src.row(), PATH_COL).text()
        info = self.infos.get(os.path.normpath(path))
        if info is None:
            return
        # cover
        if info.icon:
            img = QImage()
            if img.loadFromData(info.icon):
                self.cover.setPixmap(QPixmap.fromImage(img).scaled(
                    self.cover.width(), self.cover.height(),
                    Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                self.cover.setText("no art")
        else:
            self.cover.setText("no art")
        # details
        self.info_model.removeRows(0, self.info_model.rowCount())
        for k, v in info.as_row().items():
            if v:
                self.info_model.appendRow(
                    [QStandardItem(k), QStandardItem(str(v))])

    def _on_item_checked(self, item: QStandardItem) -> None:
        if item.column() != 0 or not item.isCheckable():
            return
        model = item.model()
        path = model.item(item.row(), PATH_COL).text()
        info = self.infos.get(os.path.normpath(path))
        if info is None:
            return
        checked = item.checkState() == Qt.Checked
        if checked:
            self._queue_install(info)
        else:
            self._dequeue_install(info)
        # Checking a Game pulls in its matching Update + DLC (same TITLE_ID)
        # so the whole title queues (or clears) together.
        if info.category_label == "Game" and not self._syncing:
            self._sync_related(info.title_id, checked)
        self._refresh_counts()

    def _sync_related(self, title_id: str, checked: bool) -> None:
        """Mirror a game's check state onto its updates and DLC."""
        if not title_id:
            return
        target = Qt.Checked if checked else Qt.Unchecked
        self._syncing = True
        try:
            for cat in ("Update", "DLC"):
                model = self.models[cat]
                for r in range(model.rowCount()):
                    if model.item(r, COLS.index("TITLE_ID")).text() == title_id:
                        cell = model.item(r, 0)
                        if cell.checkState() != target:
                            cell.setCheckState(target)
        finally:
            self._syncing = False

    def _queue_install(self, info: PkgInfo) -> None:
        np = os.path.normpath(info.path)
        for r in range(self.install_model.rowCount()):
            if self.install_model.item(r, 6).text() == np:
                return
        self.install_model.appendRow([
            QStandardItem(info.title_id), QStandardItem(info.title.strip()),
            QStandardItem(info.category_label), QStandardItem(info.size),
            QStandardItem("Queued"), QStandardItem(""), QStandardItem(np),
        ])

    def _dequeue_install(self, info: PkgInfo) -> None:
        np = os.path.normpath(info.path)
        for r in range(self.install_model.rowCount()):
            if self.install_model.item(r, 6).text() == np:
                self.install_model.removeRow(r)
                return

    def _clear_install(self) -> None:
        """Empty the install queue *and* untick every selected package."""
        # Uncheck across all category lists. Suppress the game→update/DLC
        # re-sync while we do it (we're clearing everything anyway).
        self._syncing = True
        try:
            for model in self.models.values():
                for r in range(model.rowCount()):
                    cell = model.item(r, 0)
                    if cell is not None and cell.checkState() != Qt.Unchecked:
                        cell.setCheckState(Qt.Unchecked)
        finally:
            self._syncing = False
        # belt-and-braces: drop any rows left in the queue
        self.install_model.removeRows(0, self.install_model.rowCount())
        # reset the per-list "Select all" toggle too
        self.cb_all.blockSignals(True)
        self.cb_all.setChecked(False)
        self.cb_all.blockSignals(False)
        self._refresh_counts()

    def on_rename(self) -> None:
        root = self.path_edit.text().strip()
        if not os.path.isdir(root):
            QMessageBox.information(self, "Pick a folder",
                                    "Scan or choose a folder first.")
            return
        dlg = RenameDialog(self)
        if not dlg.exec():
            return
        self._renamer = BulkRenamer(root, dlg.template.text(),
                                    dlg.no_spaces.isChecked(), self)
        self._renamer.log.connect(self._log)
        self._renamer.finished_all.connect(
            lambda n: self._log(f"Renamed {n} file(s). Re-scan to refresh."))
        self._renamer.start()

    def on_export(self) -> None:
        name, _ = QFileDialog.getSaveFileName(
            self, "Export to Excel", "PKG Library.xlsx", "Excel (*.xlsx)")
        if not name:
            return
        try:
            from openpyxl import Workbook
        except ImportError:
            QMessageBox.warning(self, "openpyxl missing",
                                "Install openpyxl to export:\n\npip install openpyxl")
            return
        wb = Workbook()
        wb.remove(wb.active)
        headers = COLS[1:]
        for cat in self.CATEGORIES:
            ws = wb.create_sheet(cat)
            ws.append(headers)
            model = self.models[cat]
            for r in range(model.rowCount()):
                ws.append([model.item(r, c).text() for c in range(1, len(COLS))])
        wb.save(name)
        self._log(f"Exported library to {name}")

    # --------------------------------------------------------- remote install
    def on_auto_detect(self) -> None:
        console = detect_console(self, prefer_type="PS4")
        if console:
            self.ps4_ip.setText(console["ip"])
            config.set(CFG, "ps4_ip", console["ip"])
            self._log(f"Auto-detected {console.get('type','Console')} at "
                      f"{console['ip']}"
                      + (f"  ({console['name']})" if console.get("name") else ""))

    def on_test(self) -> None:
        if not self.ps4_ip.text().strip():
            QMessageBox.information(self, "Console IP",
                                    "Enter your console's IP address.")
            return
        self.conn_lbl.setText("Testing…")
        self._tester = TestConnectivity(
            self.server_ip.currentText(), self.port.value(),
            self.ps4_ip.text().strip(),
            method_api_port(self.method.currentData()), parent=self)
        self._tester.result.connect(self._on_test_result)
        self._tester.start()

    def _on_test_result(self, status: dict) -> None:
        ps4 = "✓ PS4 reachable" if status["ps4"] else "✗ PS4 unreachable"
        http = "✓ HTTP up" if status["http"] else "· HTTP not running"
        self.conn_lbl.setText(f"{ps4}   |   {http}")

    def on_toggle_exploit(self) -> None:
        if self._exploit is None:
            host_dir = os.path.join(os.path.dirname(__file__), "exploit_host")
            self._exploit = ExploitHost(host_dir, 80, self)
            self._exploit.started_ok.connect(
                lambda p: self._log(f"Exploit host serving on port {p}"))
            self._exploit.failed.connect(
                lambda m: self._log(f"Exploit host error: {m}"))
            self._exploit.start()
            self.btn_exploit.setText("Stop Exploit Host")
        else:
            self._exploit.stop()
            self._exploit = None
            self.btn_exploit.setText("Start Exploit Host")
            self._log("Exploit host stopped.")

    def _selected_install_rows(self) -> list[int]:
        return sorted({i.row() for i in
                       self.install_view.selectionModel().selectedRows()})

    def on_install_all(self) -> None:
        self._start_install(list(range(self.install_model.rowCount())))

    def on_install_selected(self) -> None:
        rows = self._selected_install_rows()
        if not rows:
            QMessageBox.information(
                self, "Nothing selected",
                "Select one or more rows in the Install list first.")
            return
        self._start_install(rows)

    def on_remove_selected(self) -> None:
        rows = self._selected_install_rows()
        if not rows:
            return
        # untick the matching source packages, then drop the rows bottom-up
        for r in rows:
            item = self.install_model.item(r, 6)
            if item is None:
                continue
            info = self.infos.get(os.path.normpath(item.text()))
            if info is not None:
                self._uncheck_source(info)
        for r in reversed(rows):
            self.install_model.removeRow(r)
        self._refresh_counts()

    def _uncheck_source(self, info: PkgInfo) -> None:
        """Untick a single package's checkbox in its category list."""
        model = self.models.get(info.category_label)
        if model is None:
            return
        np = os.path.normpath(info.path)
        self._syncing = True
        try:
            for r in range(model.rowCount()):
                if model.item(r, PATH_COL).text() == np:
                    cell = model.item(r, 0)
                    if cell.checkState() != Qt.Unchecked:
                        cell.setCheckState(Qt.Unchecked)
                    break
        finally:
            self._syncing = False

    def _set_install_buttons(self, enabled: bool) -> None:
        for b in (self.btn_install, self.btn_install_sel,
                  self.btn_remove_sel, self.btn_clear):
            b.setEnabled(enabled)

    def _start_install(self, rows: list[int]) -> None:
        if self._installing:
            QMessageBox.information(
                self, "Install in progress",
                "Packages install one at a time — wait for the current run "
                "to finish.")
            return
        rows = [r for r in rows if 0 <= r < self.install_model.rowCount()]
        if not rows:
            QMessageBox.information(self, "Nothing queued",
                                    "Tick packages in the Games/Updates/DLC tabs.")
            return
        if not self.ps4_ip.text().strip():
            QMessageBox.information(self, "Console IP",
                                    "Enter your console's IP address.")
            return
        paths = [self.install_model.item(r, 6).text() for r in rows]

        # map served URL path → real model row, and the installer's 0-based
        # index → real model row (so installing a subset updates the right rows).
        self._install_bars.clear()
        self._dl_rows.clear()
        self._dl_start.clear()
        self._install_rows = list(rows)
        for r, p in zip(rows, paths):
            rel = os.path.relpath(p, self.scanned_root).replace(os.sep, "/")
            self._dl_rows["/" + rel] = r
            self.install_model.setItem(r, 4, QStandardItem("Queued"))

        self._installing = True
        self._set_install_buttons(False)
        # Build but DON'T start the installer yet. It must not talk to the
        # console until our HTTP server is actually listening — otherwise the
        # PS4's package-header fetch races the socket bind and fails with
        # "Unable to set up prerequisites" (notably on Windows, where the bind
        # is slower). The installer is started from _on_server_ready.
        self._installer = RemoteInstaller(
            self.server_ip.currentText(), paths, self.ps4_ip.text().strip(),
            self.port.value(), self.scanned_root,
            method=self.method.currentData(), parent=self)
        self._installer.log.connect(self._log)
        self._installer.progress.connect(self._on_install_progress)
        self._installer.finished_all.connect(self._on_install_done)

        # If a server is already running but for a different folder (the user
        # re-scanned) or a different port, retire it so the *new* folder is the
        # one served — otherwise the alias resolves against the old directory
        # and every package 404s.
        if self._server is not None and (
                self._server.directory != self.scanned_root
                or self._server.port != self.port.value()):
            self._server.stop()
            self._server.wait(1500)
            self._server = None
            self._server_wired = False

        if self._server is None:
            self._server = FolderHttpServer(
                self.scanned_root, self.port.value(), self)
            self._server.started_ok.connect(self._on_server_ready)
            self._server.failed.connect(self._on_server_failed)
            self._server.progress.connect(self._on_download_progress)
            self._server.completed.connect(self._on_download_complete)
            self._server_wired = True
            self._server.start()        # installer starts in _on_server_ready
        else:
            self._server.reset_counters()
            self._installer.start()

    def _on_server_ready(self, port: int) -> None:
        self._log(f"HTTP server serving packages on port {port}")
        self._server.reset_counters()
        if self._installing and self._installer is not None \
                and not self._installer.isRunning():
            self._installer.start()

    def _on_server_failed(self, msg: str) -> None:
        self._log(f"Server: {msg}")
        if self._server is not None:
            self._server.stop()
        self._server = None
        self._server_wired = False
        self._installing = False
        self._set_install_buttons(True)

    def _on_install_done(self) -> None:
        self._installing = False
        self._set_install_buttons(True)

    def _row_bar(self, row: int) -> QProgressBar:
        bar = self._install_bars.get(row)
        if bar is None:
            bar = QProgressBar()
            bar.setValue(0)
            self.install_view.setIndexWidget(self.install_model.index(row, 5), bar)
            self._install_bars[row] = bar
        return bar

    def _on_download_progress(self, rel: str, sent: int, total: int) -> None:
        row = self._dl_rows.get(rel)
        if row is None:
            return
        pct = min(100, int(sent / total * 100)) if total else 0
        self._row_bar(row).setValue(pct)
        start = self._dl_start.setdefault(row, time.time())
        speed = sent / max(time.time() - start, 1e-6)
        self.install_model.setItem(
            row, 4, QStandardItem(f"{human_size(sent)} / {human_size(total)}"
                                  f"  ·  {human_size(speed)}/s"))

    def _on_download_complete(self, rel: str) -> None:
        row = self._dl_rows.get(rel)
        if row is None:
            return
        self._row_bar(row).setValue(100)
        self.install_model.setItem(
            row, 4, QStandardItem("Downloaded ✓ — installing on PS5"))
        self._log(f"✓ PS5 finished downloading: {os.path.basename(rel)}")

    def _on_install_progress(self, index: int, eta: str, pct: int) -> None:
        row = self._install_rows[index] if index < len(self._install_rows) else index
        if row >= self.install_model.rowCount():
            return
        self.install_model.setItem(row, 4, QStandardItem(eta))
        self._row_bar(row).setValue(pct)

    # ---------------------------------------------------------------- misc
    def _log(self, text: str) -> None:
        self.log.appendPlainText(text)

    def shutdown(self) -> None:
        if self._scan is not None and self._scan.isRunning():
            self._scan.cancel()
            self._scan.wait(2000)
        if self._installer is not None and self._installer.isRunning():
            self._installer.cancel()
            self._installer.wait(6000)
        for thread in (self._server, self._exploit):
            if thread is not None:
                thread.stop()
                thread.wait(1500)
