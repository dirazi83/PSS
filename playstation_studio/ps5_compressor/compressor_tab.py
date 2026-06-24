"""PS5 PFS compressor — embeddable tab widget."""

from __future__ import annotations

import os
import time
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtGui import (
    QColor, QDragEnterEvent, QDropEvent, QIcon, QTextCursor,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListView, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSlider, QSpinBox,
    QStackedWidget, QSystemTrayIcon, QTableWidget, QTableWidgetItem, QTreeView,
    QVBoxLayout, QWidget,
)

from .estimate import Estimate, EstimatorThread, compression_rating
from . import history
from .jobs import (
    Job, PackSettings, Status, iter_game_dirs, mkpfs_version,
    SHADOWMOUNT_MIN_BLOCK,
)
from .runner import BatchRunner
from ..shared.config import config
from ..shared.diskutil import (
    free_space_bytes, is_cloud_synced_path, is_network_path,
)
from ..shared.paths import (
    TEMP_DIR, TEMP_MODE_APP, TEMP_MODE_CUSTOM, TEMP_MODE_GAME, resolve_temp_dir,
    set_temp_policy, temp_mode as get_temp_mode, custom_temp_path,
)
from ..shared.theme import Palette
from ..shared.formatting import human_size

CFG = "ps5"


class GameScanWorker(QThread):
    """Scan folders for PS5 game dumps off the GUI thread.

    Mirrors the PKG Manager's ``ScanWorker``: walks the tree on a background
    thread and emits each game (with its metadata already read) the moment it's
    found, so the list fills in progressively and the UI never freezes — even
    for a folder with hundreds of games on a slow network share.
    """

    found = Signal(object)        # Job, ready to add
    progress = Signal(int, str)   # games found so far, current game name
    done = Signal(int, bool)      # total found, cancelled

    def __init__(self, roots: list[str], max_depth: int,
                 existing: list[str], parent=None) -> None:
        super().__init__(parent)
        self._roots = list(roots)
        self._max_depth = max_depth
        self._existing = set(existing)
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        seen = set(self._existing)
        n = 0
        for root in self._roots:
            for source_dir in iter_game_dirs(root, self._max_depth):
                if self._cancel:
                    self.done.emit(n, True)
                    return
                if source_dir in seen:
                    continue
                seen.add(source_dir)
                # Build the Job here (reads param.json + stats icon0.png) so the
                # per-game metadata read happens off the GUI thread, not on it.
                job = Job(source_dir=source_dir)
                n += 1
                self.found.emit(job)
                self.progress.emit(n, job.name)
        self.done.emit(n, self._cancel)


class Ps5CompressTab(QWidget):
    COLS = ["Game", "Status", "Progress", "Input", "Output", "Saved"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.jobs: list[Job] = []
        self.bars: list[QProgressBar] = []
        self._active_indices: list[int] | None = None   # jobs in the current run
        self.estimates: dict[str, Estimate] = {}    # by source_dir
        self._estimator: EstimatorThread | None = None
        self._scanner: GameScanWorker | None = None  # async folder scan
        self._scanning = False
        self.runner = BatchRunner(self)
        self._wire_runner()

        self.setAcceptDrops(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        body = QHBoxLayout()
        body.setContentsMargins(18, 14, 18, 8)
        body.setSpacing(16)
        body.addLayout(self._build_main_column(), stretch=1)
        body.addWidget(self._build_settings_panel())
        root.addLayout(body, stretch=1)

        root.addWidget(self._build_footer())
        self._refresh_stats()

    # ========================================================== main column
    def _build_main_column(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(12)

        # toolbar
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.btn_scan = QPushButton("⊕  Scan Folder")
        self.btn_scan.setToolTip("Pick a folder and recursively find every game "
                                 "dump beneath it, down to the chosen depth.")
        self.btn_add = QPushButton("＋  Add Game(s)")
        self.btn_add.setToolTip("Add one or more individual game-dump folders.")
        self.btn_remove = QPushButton("－  Remove")
        self.btn_estimate = QPushButton("⊜  Estimate")
        self.btn_estimate.setToolTip("Predict the packed size and padding before "
                                     "compressing (recommends auto block size).")
        self.btn_extract_img = QPushButton("⊟  Extract…")
        self.btn_extract_img.setToolTip("Unpack a .ffpfs / .ffpfsc image back to "
                                        "a folder.")
        self.btn_extract_img.clicked.connect(self.on_extract_image)
        self.btn_history = QPushButton("History")
        self.btn_history.setObjectName("Ghost")
        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setObjectName("Ghost")
        self.btn_scan.clicked.connect(self.on_scan_clicked)
        self.btn_add.clicked.connect(self.on_add_games)
        self.btn_remove.clicked.connect(self.on_remove_selected)
        self.btn_estimate.clicked.connect(self.on_estimate)
        self.btn_history.clicked.connect(self.on_history)
        self.btn_clear.clicked.connect(self.on_clear)
        bar.addWidget(self.btn_scan)

        depth_lbl = QLabel("depth")
        depth_lbl.setStyleSheet(f"color:{Palette.text_dim}; font-size:12px;")
        self.scan_depth = QSpinBox()
        self.scan_depth.setRange(1, 10)
        self.scan_depth.setValue(3)
        self.scan_depth.setFixedWidth(58)
        self.scan_depth.setToolTip("How many sub-folder levels Scan Folder will "
                                   "search for game dumps.")
        bar.addWidget(depth_lbl)
        bar.addWidget(self.scan_depth)

        bar.addSpacing(8)
        bar.addWidget(self.btn_add)
        bar.addWidget(self.btn_remove)
        bar.addWidget(self.btn_estimate)
        bar.addWidget(self.btn_extract_img)
        bar.addStretch(1)
        self.stats_pill = QLabel("0 games")
        self.stats_pill.setObjectName("Pill")
        bar.addWidget(self.stats_pill)
        bar.addWidget(self.btn_history)
        bar.addWidget(self.btn_clear)
        col.addLayout(bar)

        # table
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setIconSize(QSize(40, 40))     # show game cover thumbnails
        self.table.verticalHeader().setDefaultSectionSize(48)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, len(self.COLS)):
            hdr.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self.table.setColumnWidth(2, 200)

        # empty-state drop zone shown when no jobs are queued
        self.drop_zone = self._build_drop_zone()

        # stack: index 0 = empty state, index 1 = populated table
        self.stack = QStackedWidget()
        self.stack.addWidget(self.drop_zone)
        self.stack.addWidget(self.table)
        col.addWidget(self.stack, stretch=3)

        # log
        log_title = QLabel("OUTPUT LOG")
        log_title.setObjectName("SectionTitle")
        col.addWidget(log_title)
        self.log = QPlainTextEdit()
        self.log.setObjectName("Log")
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        self.log.setFixedHeight(150)
        col.addWidget(self.log, stretch=1)
        return col

    def _build_drop_zone(self) -> QFrame:
        """Large, friendly empty-state shown when no games are queued."""
        zone = QFrame()
        zone.setObjectName("DropZone")
        lay = QVBoxLayout(zone)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(10)

        icon = QLabel("⬇")
        icon.setObjectName("DropIcon")
        icon.setAlignment(Qt.AlignCenter)

        head = QLabel("Drop game folders here")
        head.setObjectName("DropHead")
        head.setAlignment(Qt.AlignCenter)

        sub = QLabel("or use  ⊕ Scan Folder  to find every PS5 dump automatically")
        sub.setObjectName("DropSub")
        sub.setAlignment(Qt.AlignCenter)

        lay.addStretch(1)
        lay.addWidget(icon)
        lay.addWidget(head)
        lay.addWidget(sub)
        lay.addStretch(1)
        return zone

    # ======================================================= settings panel
    def _build_settings_panel(self) -> QWidget:
        """Pack settings, grouped into Output / Performance / Advanced and held
        in a scroll area so a short window scrolls instead of squashing the
        inputs (squashed inputs clip their text)."""
        panel = QFrame()
        panel.setObjectName("Panel")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.setSpacing(10)

        # ----------------------------------------------------------- OUTPUT
        lay.addWidget(self._subhead("OUTPUT", first=True))

        lay.addWidget(self._field_label("Output folder"))
        out_row = QHBoxLayout()
        out_row.setSpacing(6)
        self.out_dir = QLineEdit(config.get(CFG, "output_dir", ""))
        self.out_dir.setPlaceholderText("Same as each game's parent folder")
        self.out_dir.editingFinished.connect(
            lambda: config.set(CFG, "output_dir", self.out_dir.text().strip()))
        btn_browse = QPushButton("…")
        btn_browse.setFixedWidth(40)
        btn_browse.clicked.connect(self.on_pick_output)
        out_row.addWidget(self.out_dir)
        out_row.addWidget(btn_browse)
        lay.addLayout(out_row)

        lay.addWidget(self._field_label("Console profile"))
        version_badge = QLabel("PS5")
        version_badge.setObjectName("VersionBadge")
        version_badge.setToolTip("Output is built with the PS5 PFS profile.")
        badge_row = QHBoxLayout()
        badge_row.addWidget(version_badge)
        badge_row.addStretch(1)
        lay.addLayout(badge_row)

        # output format: compressed (.ffpfsc) vs uncompressed (.ffpfs)
        lay.addWidget(self._field_label("Output format"))
        self.fmt = QComboBox()
        self.fmt.addItem("Compressed PFS  ·  .ffpfsc", True)
        self.fmt.addItem("Uncompressed PFS  ·  .ffpfs", False)
        self.fmt.setToolTip(
            "Compressed (.ffpfsc) — smaller on disk; decompressed on the "
            "console.\nUncompressed (.ffpfs) — larger, full read speed.\n"
            "Both mount under ShadowMountPlus / MicroMount.")
        self.fmt.currentIndexChanged.connect(self._on_format_changed)
        lay.addWidget(self.fmt)

        self.lbl_level = QLabel("Compression level: 9")
        self.lbl_level.setStyleSheet(f"color:{Palette.text_dim}; font-size:12px;")
        lay.addWidget(self.lbl_level)
        self.level = QSlider(Qt.Horizontal)
        self.level.setRange(0, 9)
        self.level.setValue(9)
        self.level.valueChanged.connect(
            lambda v: self.lbl_level.setText(f"Compression level: {v}"))
        lay.addWidget(self.level)

        # ------------------------------------------------------ PERFORMANCE
        lay.addWidget(self._subhead("PERFORMANCE"))

        lay.addWidget(self._field_label("CPU cores (0 = auto)"))
        self.cpu = QSpinBox()
        self.cpu.setRange(0, 256)
        self.cpu.setValue(0)
        lay.addWidget(self.cpu)

        lay.addWidget(self._field_label("Temp files (intermediate data)"))
        self.temp_mode = QComboBox()
        self.temp_mode.addItem("App folder (default)", TEMP_MODE_APP)
        self.temp_mode.addItem("Beside the game", TEMP_MODE_GAME)
        self.temp_mode.addItem("Custom folder…", TEMP_MODE_CUSTOM)
        self.temp_mode.setToolTip(
            "Where the compressor writes intermediate data while packing.\n"
            "• App folder — ~/.playstation_studio/temp\n"
            "• Beside the game — same disk as the source (fast for local games)\n"
            "• Custom folder — put it on a fast, empty disk")
        idx = self.temp_mode.findData(get_temp_mode())
        self.temp_mode.setCurrentIndex(idx if idx >= 0 else 0)
        self.temp_mode.currentIndexChanged.connect(self._on_temp_mode_changed)
        lay.addWidget(self.temp_mode)

        temp_row = QHBoxLayout()
        temp_row.setSpacing(6)
        self.temp_path = QLineEdit(custom_temp_path())
        self.temp_path.setPlaceholderText("Pick a custom temp folder")
        self.temp_path.editingFinished.connect(self._save_temp_policy)
        self.btn_temp = QPushButton("…")
        self.btn_temp.setFixedWidth(40)
        self.btn_temp.clicked.connect(self.on_pick_temp)
        temp_row.addWidget(self.temp_path)
        temp_row.addWidget(self.btn_temp)
        lay.addLayout(temp_row)
        self._sync_temp_row()

        self.cb_lowmem = QCheckBox("Low-memory mode (1 core, slower)")
        self.cb_lowmem.setToolTip("Compress one file at a time to minimise peak "
                                  "RAM. Use on machines with little free memory.")
        self.cb_lowmem.setChecked(bool(config.get(CFG, "low_memory", False)))
        self.cb_lowmem.toggled.connect(
            lambda on: config.set(CFG, "low_memory", on))
        lay.addWidget(self.cb_lowmem)

        # --------------------------------------------------------- ADVANCED
        lay.addWidget(self._subhead("ADVANCED"))

        # ShadowMountPlus compatibility: force a >= 32 KiB block so images mount
        # cleanly under ShadowMountPlus. Opt-in (off by default) because it makes
        # tiny-file games larger than the smallest auto-fit image.
        self.cb_shadowmount = QCheckBox("ShadowMountPlus compatible (≥32 KiB block)")
        self.cb_shadowmount.setToolTip(
            "Build PFS images that mount cleanly under ShadowMountPlus.\n"
            f"Forces a {SHADOWMOUNT_MIN_BLOCK // 1024} KiB block size (ShadowMountPlus "
            "rejects smaller clusters on its default config).\n"
            "Turn this on if you use ShadowMountPlus. Leaving it off produces the "
            "smallest possible image for games with thousands of tiny files.")
        self.cb_shadowmount.setChecked(
            bool(config.get(CFG, "shadowmount_compatible", False)))
        self.cb_shadowmount.toggled.connect(self._on_shadowmount_toggle)

        self.cb_autoblock = QCheckBox("Shrink small-file games (auto block size)")
        self._autoblock_tip = (
            "Pick the block size that minimises per-file padding. Games with "
            "thousands of tiny files (e.g. Minecraft) can otherwise pack LARGER "
            "than the original because each file is padded to a 64 KiB block.")
        self.cb_autoblock.setToolTip(self._autoblock_tip)
        self.cb_autoblock.setChecked(bool(config.get(CFG, "auto_block_size", True)))
        self.cb_autoblock.toggled.connect(
            lambda on: config.set(CFG, "auto_block_size", on))
        self.cb_skipexec = QCheckBox("Store executables uncompressed")
        self.cb_skipexec.setChecked(True)
        self.cb_verify = QCheckBox("Verify after packing")
        self.cb_encrypt = QCheckBox("Encrypt blocks (AES-XTS)")
        self.cb_require = QCheckBox("Require game files")
        self.cb_overwrite = QCheckBox("Overwrite existing images")
        for cb in (self.cb_shadowmount, self.cb_autoblock, self.cb_skipexec,
                   self.cb_verify, self.cb_encrypt, self.cb_require,
                   self.cb_overwrite):
            lay.addWidget(cb)
        # auto-fit is overridden while ShadowMountPlus mode is on
        self._on_shadowmount_toggle(self.cb_shadowmount.isChecked())

        lay.addStretch(1)
        _ver = mkpfs_version()
        _vtxt = f" {_ver}" if _ver else ""
        credit = QLabel('Compression engine: '
                        f'<a href="https://github.com/PSBrew/MkPFS">MkPFS{_vtxt}</a>'
                        ' by PSBrew')
        credit.setOpenExternalLinks(True)
        credit.setStyleSheet(f"color:{Palette.text_faint}; font-size:11px;")
        lay.addWidget(credit)

        # Hold the card in a scroll area so a short window scrolls rather than
        # vertically compressing the inputs (which clips their text).
        scroll = QScrollArea()
        scroll.setWidget(panel)
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(342)        # 320 content + room for the scrollbar
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.viewport().setStyleSheet("background: transparent;")
        return scroll

    def _field_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color:{Palette.text_dim}; font-size:12px; font-weight:600;")
        return lbl

    def _subhead(self, text: str, first: bool = False) -> QLabel:
        """A small uppercase section divider inside the settings panel."""
        lbl = QLabel(text)
        lbl.setObjectName("SectionTitle")
        lbl.setStyleSheet("" if first else "margin-top:8px;")
        return lbl

    # =============================================================== footer
    def _build_footer(self) -> QFrame:
        f = QFrame()
        f.setObjectName("Header")
        f.setFixedHeight(76)
        lay = QHBoxLayout(f)
        lay.setContentsMargins(22, 0, 22, 0)
        lay.setSpacing(16)

        prog_box = QVBoxLayout()
        prog_box.setSpacing(4)
        self.status_lbl = QLabel("Ready")
        self.status_lbl.setObjectName("StatusBar")
        self.overall = QProgressBar()
        self.overall.setObjectName("Overall")
        self.overall.setRange(0, 100)
        self.overall.setValue(0)
        self.overall.setTextVisible(False)
        prog_box.addWidget(self.status_lbl)
        prog_box.addWidget(self.overall)
        lay.addLayout(prog_box, stretch=1)

        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setObjectName("Danger")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.on_stop)
        self.btn_start_sel = QPushButton("▶  Compress Selected")
        self.btn_start_sel.setToolTip("Compress only the selected game(s) in the list.")
        self.btn_start_sel.clicked.connect(lambda: self.on_start(selected_only=True))
        self.btn_start = QPushButton("▶  Compress All")
        self.btn_start.setObjectName("Primary")
        self.btn_start.clicked.connect(self.on_start)
        lay.addWidget(self.btn_stop)
        lay.addWidget(self.btn_start_sel)
        lay.addWidget(self.btn_start)
        return f

    # =========================================================== job mgmt
    def _rebuild_table(self) -> None:
        self.table.setRowCount(0)
        self.bars = []
        for job in self.jobs:
            self._append_row(job)
        self._refresh_stats()
        self.stack.setCurrentIndex(1 if self.jobs else 0)

    def _append_row(self, job: Job) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)

        name_item = QTableWidgetItem("  " + job.name)
        name_item.setToolTip(
            f"{job.title}\n{job.source_dir}" if job.title else job.source_dir)
        if job.icon_path:
            name_item.setIcon(QIcon(job.icon_path))
        self.table.setItem(r, 0, name_item)

        self.table.setItem(r, 1, self._status_item(job))

        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(job.progress)
        bar.setTextVisible(True)
        bar.setFormat("")
        self.table.setCellWidget(r, 2, bar)
        self.bars.append(bar)

        self.table.setItem(r, 3, self._input_item(job))
        self.table.setItem(r, 4, self._output_item(job))
        self.table.setItem(r, 5, self._saved_item(job))

    def _status_item(self, job: Job) -> QTableWidgetItem:
        item = QTableWidgetItem(job.status.value)
        item.setForeground(QColor(Palette.status_color(job.status.value)))
        if job.message:
            item.setToolTip(job.message)
        return item

    @staticmethod
    def _cell(text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignCenter)
        return item

    @staticmethod
    def _saved_text(job: Job) -> str:
        r = job.ratio
        return f"{(1 - r) * 100:.0f}%" if r is not None else "—"

    # ---- size / rating cells (estimate-aware) ----
    def _est(self, job: Job) -> Estimate | None:
        return self.estimates.get(job.source_dir)

    def _input_item(self, job: Job) -> QTableWidgetItem:
        est = self._est(job)
        val = job.size_in or (est.raw if est else 0)
        return self._cell(human_size(val) if val else "—")

    def _output_item(self, job: Job) -> QTableWidgetItem:
        if job.size_out:
            return self._cell(human_size(job.size_out))
        est = self._est(job)
        if est and est.foot_best:
            it = self._cell(f"≈ {human_size(est.foot_best)}")
            it.setForeground(QColor(Palette.text_dim))
            it.setToolTip(self._est_tooltip(est))
            return it
        return self._cell("—")

    def _saved_item(self, job: Job) -> QTableWidgetItem:
        r = job.ratio
        if r is not None:
            pct = (1 - r) * 100
            label, color = compression_rating(pct)
            it = self._cell(f"{pct:.0f}%  ·  {label}")
            it.setForeground(QColor(color))
            return it
        est = self._est(job)
        if est and est.recommend_autofit:
            it = self._cell("auto-fit ✓")
            it.setForeground(QColor("#fbbf24"))
            it.setToolTip(self._est_tooltip(est))
            return it
        return self._cell("—")

    @staticmethod
    def _est_tooltip(est: Estimate) -> str:
        base = (f"{est.files:,} files · {human_size(est.raw)} raw\n"
                f"At 64 KiB block: {human_size(est.foot_default)} "
                f"(+{human_size(est.padding_default)} padding)\n"
                f"Best block {est.best_block // 1024} KiB: "
                f"{human_size(est.foot_best)} (+{human_size(est.padding_best)} padding)")
        if est.recommend_autofit:
            return base + (f"\n→ Auto block size saves "
                           f"{human_size(est.autofit_saving)} — keep it enabled")
        return base + "\n→ 64 KiB block is fine for this game"

    def _update_row(self, idx: int) -> None:
        job = self.jobs[idx]
        self.table.setItem(idx, 1, self._status_item(job))
        if idx < len(self.bars):
            self.bars[idx].setValue(job.progress)
            self.bars[idx].setFormat(job.phase or "")
        self.table.setItem(idx, 3, self._input_item(job))
        self.table.setItem(idx, 4, self._output_item(job))
        self.table.setItem(idx, 5, self._saved_item(job))

    def _refresh_stats(self) -> None:
        total_in = sum(j.size_in or (self._est(j).raw if self._est(j) else 0)
                       for j in self.jobs)
        n = len(self.jobs)
        txt = f"{n} game{'s' if n != 1 else ''}"
        if total_in:
            txt += f"  ·  {human_size(total_in)}"
        self.stats_pill.setText(txt)

    # ============================================================ actions
    def on_scan_clicked(self) -> None:
        """The Scan button doubles as a Stop button while a scan is running."""
        if self._scanning:
            self.on_stop_scan()
        else:
            self.on_scan_folder()

    def on_scan_folder(self) -> None:
        parent = QFileDialog.getExistingDirectory(self, "Select a folder of game dumps")
        if parent:
            self._start_scan([parent], self.scan_depth.value())

    def on_add_games(self) -> None:
        dirs = self._select_multiple_dirs()
        if dirs:
            self._start_scan(dirs, self.scan_depth.value())

    # --------------------------------------------------------- async scan
    def _start_scan(self, roots: list[str], depth: int) -> None:
        """Scan *roots* for game dumps on a background thread, adding each game
        to the list as it's found so the UI never blocks."""
        if self._scanning or self.runner.running:
            return
        self._set_scanning(True)
        self.status_lbl.setText("Scanning for game dumps…")
        self._log(f"Scanning for game dumps (depth {depth})…\n")
        self._scanner = GameScanWorker(
            roots, depth, [j.source_dir for j in self.jobs], self)
        self._scanner.found.connect(self._on_scan_found)
        self._scanner.progress.connect(self._on_scan_progress)
        self._scanner.done.connect(self._on_scan_done)
        self._scanner.start()

    def on_stop_scan(self) -> None:
        if self._scanner is not None and self._scanner.isRunning():
            self._scanner.cancel()
            self.status_lbl.setText("Stopping scan…")

    def _on_scan_found(self, job: Job) -> None:
        # Append one game + one table row (no full rebuild) — keeps it snappy
        # even when hundreds of games stream in.
        self.jobs.append(job)
        if self.stack.currentIndex() != 1:
            self.stack.setCurrentIndex(1)
        self._append_row(job)

    def _on_scan_progress(self, count: int, name: str) -> None:
        self.status_lbl.setText(f"Scanning… {count} game(s) found  ·  {name}")
        self._refresh_stats()

    def _on_scan_done(self, n: int, cancelled: bool) -> None:
        self._set_scanning(False)
        self._refresh_stats()
        if n == 0:
            self.status_lbl.setText("No game dumps found.")
            self._log("No folders containing eboot.bin or sce_sys were found "
                      "(try increasing the depth next to Scan).\n")
        else:
            verb = "stopped" if cancelled else "complete"
            self.status_lbl.setText(f"Scan {verb} — {n} game(s) added.")
            self._log(f"Scan {verb} — {n} game(s) added.\n")

    def _set_scanning(self, scanning: bool) -> None:
        self._scanning = scanning
        self.btn_scan.setText("■  Stop scan" if scanning else "⊕  Scan Folder")
        self.btn_scan.setObjectName("Danger" if scanning else "")
        self.btn_scan.style().unpolish(self.btn_scan)
        self.btn_scan.style().polish(self.btn_scan)
        # block the actions that mutate the list / start a pack while scanning
        for w in (self.btn_add, self.btn_remove, self.btn_estimate,
                  self.btn_extract_img, self.btn_history, self.btn_clear,
                  self.btn_start, self.btn_start_sel):
            w.setEnabled(not scanning)

    def on_remove_selected(self) -> None:
        if self.runner.running or self._scanning:
            return
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            if 0 <= r < len(self.jobs):
                del self.jobs[r]
        self._rebuild_table()

    def on_clear(self) -> None:
        if self.runner.running or self._scanning:
            return
        self.jobs.clear()
        self.estimates.clear()
        self._rebuild_table()
        self.log.clear()

    # --------------------------------------------------------- estimate
    def on_estimate(self) -> None:
        if self.runner.running or not self.jobs:
            if not self.jobs:
                QMessageBox.information(self, "Nothing to estimate",
                                       "Add at least one game first.")
            return
        if self._estimator and self._estimator.isRunning():
            return
        self.btn_estimate.setEnabled(False)
        self.status_lbl.setText("Estimating sizes…")
        self._log("Estimating packed sizes (reading file sizes only)…\n")
        # In ShadowMountPlus mode the block can't go below 32 KiB, so estimate
        # the footprint the pack will actually produce.
        min_block = (SHADOWMOUNT_MIN_BLOCK if self.cb_shadowmount.isChecked()
                     else 4096)
        self._estimator = EstimatorThread(
            [j.source_dir for j in self.jobs], min_block, self)
        self._estimator.one.connect(self._on_estimate_one)
        self._estimator.finished_all.connect(self._on_estimate_done)
        self._estimator.start()

    def _on_estimate_one(self, idx: int, est: Estimate) -> None:
        if not est.ok:
            return
        self.estimates[est.source_dir] = est
        if idx < len(self.jobs):
            self._update_row(idx)

    def _on_estimate_done(self) -> None:
        self.btn_estimate.setEnabled(True)
        ests = [self.estimates.get(j.source_dir) for j in self.jobs]
        ests = [e for e in ests if e]
        if not ests:
            self.status_lbl.setText("Ready")
            return
        total_best = sum(e.foot_best for e in ests)
        total_default = sum(e.foot_default for e in ests)
        saving = max(0, total_default - total_best)
        bloat = [e for e in ests if e.recommend_autofit]
        msg = (f"Estimated {len(ests)} game(s): ~{human_size(total_best)} packed "
               f"(auto block size)")
        if saving:
            msg += f", saving {human_size(saving)} vs 64 KiB blocks"
        self.status_lbl.setText(msg)
        self._log(msg + ".\n")
        self._refresh_stats()
        # Nudge the user to keep auto-fit on when it clearly helps. Skip the
        # nudge in ShadowMountPlus mode, where the block is intentionally fixed.
        if bloat and not self.cb_autoblock.isChecked() \
                and not self.cb_shadowmount.isChecked():
            names = ", ".join(self._job_for(e).name for e in bloat[:4])
            choice = QMessageBox.question(
                self, "Enable auto block size?",
                f"{len(bloat)} game(s) ({names}) have many small files and would "
                "pack much smaller with auto block size — which is currently "
                "OFF.\n\nEnable it now?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if choice == QMessageBox.Yes:
                self.cb_autoblock.setChecked(True)

    def _job_for(self, est: Estimate) -> Job:
        return next(j for j in self.jobs if j.source_dir == est.source_dir)

    def on_history(self) -> None:
        history.HistoryDialog(self).exec()

    def on_extract_image(self) -> None:
        """Open the PFS Extract dialog (unpack .ffpfs / .ffpfsc → folder)."""
        from .extract_dialog import ExtractDialog
        ExtractDialog(self).exec()

    def on_pick_output(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose output folder")
        if d:
            self.out_dir.setText(d)
            config.set(CFG, "output_dir", d)

    # --------------------------------------------------------- temp folder
    def _sync_temp_row(self) -> None:
        """Show the custom-path row only when 'Custom folder' is selected."""
        is_custom = self.temp_mode.currentData() == TEMP_MODE_CUSTOM
        self.temp_path.setVisible(is_custom)
        self.btn_temp.setVisible(is_custom)

    def _on_temp_mode_changed(self, _index: int) -> None:
        self._sync_temp_row()
        self._save_temp_policy()

    def _save_temp_policy(self) -> None:
        set_temp_policy(self.temp_mode.currentData() or TEMP_MODE_APP,
                        self.temp_path.text().strip())

    def on_pick_temp(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose temp folder")
        if d:
            self.temp_path.setText(d)
            self._save_temp_policy()

    # --------------------------------------------------------- run control
    def _collect_settings(self) -> PackSettings:
        return PackSettings(
            output_dir=self.out_dir.text().strip(),
            version="PS5",
            compress=bool(self.fmt.currentData()),
            compression_level=self.level.value(),
            verify=self.cb_verify.isChecked(),
            encrypted=self.cb_encrypt.isChecked(),
            require_game_files=self.cb_require.isChecked(),
            skip_executable_compression=self.cb_skipexec.isChecked(),
            cpu_count=self.cpu.value(),
            low_memory=self.cb_lowmem.isChecked(),
            overwrite=self.cb_overwrite.isChecked(),
            auto_block_size=self.cb_autoblock.isChecked(),
            shadowmount_compatible=self.cb_shadowmount.isChecked(),
            temp_mode=self.temp_mode.currentData() or TEMP_MODE_APP,
            temp_path=self.temp_path.text().strip(),
        )

    def on_start(self, selected_only: bool = False) -> None:
        if self.runner.running:
            return
        if not self.jobs:
            QMessageBox.information(self, "Nothing to do", "Add at least one game first.")
            return
        # Decide which jobs to run: the whole list, or just the selected rows.
        if selected_only:
            run_indices = sorted({i.row() for i in self.table.selectedIndexes()
                                  if 0 <= i.row() < len(self.jobs)})
            if not run_indices:
                QMessageBox.information(self, "Nothing selected",
                                       "Select one or more games in the list first.")
                return
        else:
            run_indices = list(range(len(self.jobs)))
        run_jobs = [self.jobs[i] for i in run_indices]
        # Warn if any source lives in iCloud (Desktop & Documents sync / iCloud
        # Drive): macOS downloads files on demand and evicts them under disk
        # pressure, so packing crawls or fails. This is the #1 cause of a
        # compression that looks hung on a Mac.
        cloud_jobs = [j for j in run_jobs if is_cloud_synced_path(j.source_dir)]
        if cloud_jobs:
            names = "\n".join(f"  • {j.name}" for j in cloud_jobs[:6])
            more = f"\n  …and {len(cloud_jobs) - 6} more" if len(cloud_jobs) > 6 else ""
            choice = QMessageBox.warning(
                self, "Game is in an iCloud folder",
                f"{len(cloud_jobs)} game(s) are inside iCloud "
                f"(Desktop/Documents sync or iCloud Drive):\n{names}{more}\n\n"
                "macOS downloads these files on demand and can evict them when "
                "the disk is low, so compression becomes extremely slow and may "
                "fail partway (files disappear mid-pack).\n\nMove the game to a "
                "plain local folder outside Desktop/Documents (e.g. "
                "~/Games) first.\n\nTry to compress from iCloud anyway?",
                QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
            if choice != QMessageBox.Yes:
                return
        # Warn if any source lives on a slow network share (SMB/NFS): reading
        # thousands of game files over the network is very slow and looks frozen.
        net_jobs = [j for j in run_jobs
                    if is_network_path(j.source_dir)
                    and not is_cloud_synced_path(j.source_dir)]
        if net_jobs:
            names = "\n".join(f"  • {j.name}" for j in net_jobs[:6])
            more = f"\n  …and {len(net_jobs) - 6} more" if len(net_jobs) > 6 else ""
            choice = QMessageBox.warning(
                self, "Game is on a network drive",
                f"{len(net_jobs)} game(s) are on a network share:\n{names}{more}\n\n"
                "Compressing reads every file over the network, which is very "
                "slow (often many minutes with little visible progress) and can "
                "look frozen.\n\nFor much faster compression, copy the game to a "
                "local disk first.\n\nCompress from the network anyway?",
                QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
            if choice != QMessageBox.Yes:
                return
        # Storage pre-flight: packing needs room for the image *and* temp spool
        # (~2.2x the source). Warn early if the output or temp disk is short.
        if not self._storage_preflight(run_jobs):
            return
        # reset transient state (only for the jobs we're about to run)
        for j in run_jobs:
            if j.status != Status.DONE or self.cb_overwrite.isChecked():
                j.status = Status.QUEUED
                j.progress = 0
                j.phase = ""
                j.size_out = 0
                j.output_path = ""
        self._active_indices = run_indices
        self._rebuild_table()
        self.overall.setValue(0)
        self._set_running_ui(True)
        scope = (f"{len(run_indices)} selected game(s)" if selected_only
                 else "batch")
        self._log("=" * 50 + f"\nStarting {scope}…\n")
        self.runner.start(self.jobs, self._collect_settings(), indices=run_indices)

    def _total_source_bytes(self, jobs: list[Job]) -> int | None:
        """Best-effort total source size. Uses estimates; falls back to a quick
        local walk. Returns None when it can't be determined cheaply."""
        total = 0
        for j in jobs:
            est = self._est(j)
            if est:
                total += est.raw
            elif (is_cloud_synced_path(j.source_dir)
                  or is_network_path(j.source_dir)):
                return None             # too slow to size up front; skip check
            else:
                total += sum(
                    os.path.getsize(os.path.join(r, f))
                    for r, _d, fs in os.walk(j.source_dir) for f in fs
                    if os.path.exists(os.path.join(r, f)))
        return total

    def _storage_preflight(self, jobs: list[Job]) -> bool:
        """Warn (and let the user cancel) when disk space looks insufficient."""
        total = self._total_source_bytes(jobs)
        if not total:
            return True
        out_dir = (self.out_dir.text().strip()
                   or str(Path(jobs[0].source_dir).parent))
        temp_dir = str(resolve_temp_dir(
            jobs[0].source_dir, self.temp_mode.currentData() or TEMP_MODE_APP,
            self.temp_path.text().strip()))
        out_free = free_space_bytes(out_dir)
        temp_free = free_space_bytes(temp_dir)
        problems = []
        if out_free is not None and out_free < int(total * 1.1):
            problems.append(f"  • Output disk: {human_size(out_free)} free, "
                            f"needs ≈ {human_size(int(total * 1.1))}")
        if temp_free is not None and temp_free < total:
            problems.append(f"  • Temp disk: {human_size(temp_free)} free, "
                            f"needs ≈ {human_size(total)}")
        if not problems:
            return True
        details = "\n".join(problems)
        return QMessageBox.warning(
            self, "Low disk space",
            f"Compressing needs room for the image plus temporary data "
            f"(≈ 2× the {human_size(total)} source).\n\n{details}\n\n"
            "MkPFS may fail partway if it runs out of space. Continue anyway?",
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel
        ) == QMessageBox.Yes

    def on_stop(self) -> None:
        self.status_lbl.setText("Stopping…")
        self.runner.stop()

    def _set_running_ui(self, running: bool) -> None:
        self.btn_start.setEnabled(not running)
        self.btn_start_sel.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        for w in (self.btn_scan, self.btn_add, self.btn_remove, self.btn_clear,
                  self.btn_estimate, self.btn_extract_img):
            w.setEnabled(not running)

    # ----------------------------------------------------- runner signals
    def _wire_runner(self) -> None:
        self.runner.jobStarted.connect(self._on_job_started)
        self.runner.jobProgress.connect(self._on_job_progress)
        self.runner.jobOutput.connect(self._on_job_output)
        self.runner.jobFinished.connect(self._on_job_finished)
        self.runner.batchFinished.connect(self._on_batch_finished)

    # MkPFS is silent during scanning / temp-image build (no % line), which on
    # games with many files looks like a hang. Detect the stage from its output
    # and show a busy (indeterminate) bar so the user knows it's working.
    _STAGE_KEYWORDS = (
        ("Scanning", "Scanning files…"),
        ("Compressing", "Compressing…"),
        ("Writing PFS", "Writing image…"),
        ("Writing", "Writing image…"),
        ("Verifying", "Verifying…"),
    )

    def _set_busy(self, idx: int, label: str) -> None:
        """Put a job's bar into an indeterminate 'working' state with a label."""
        if idx < len(self.bars):
            bar = self.bars[idx]
            bar.setRange(0, 0)          # indeterminate (animated) bar
            bar.setFormat(label)

    def _on_job_started(self, idx: int) -> None:
        self._update_row(idx)
        self._set_busy(idx, "Preparing…")
        self.status_lbl.setText(f"Compressing  {self.jobs[idx].name}  "
                                f"({idx + 1}/{len(self.jobs)}) — preparing…")
        self.table.selectRow(idx)

    def _on_job_progress(self, idx: int, pct: int, phase: str) -> None:
        self.jobs[idx].progress = pct
        self.jobs[idx].phase = phase
        if idx < len(self.bars):
            bar = self.bars[idx]
            if bar.maximum() == 0:      # leaving the indeterminate state
                bar.setRange(0, 100)
            bar.setValue(pct)
            bar.setFormat(f"{phase} {pct}%")
        self._update_overall()

    def _on_job_output(self, idx: int, text: str) -> None:
        name = self.jobs[idx].name if 0 <= idx < len(self.jobs) else "?"
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            self._log(f"[{name}] {stripped}\n")
            # surface the current stage on the busy bar + status line
            for needle, label in self._STAGE_KEYWORDS:
                if needle in stripped and idx < len(self.bars) \
                        and self.bars[idx].maximum() == 0:
                    self._set_busy(idx, label)
                    self.status_lbl.setText(
                        f"Compressing  {self.jobs[idx].name}  "
                        f"({idx + 1}/{len(self.jobs)}) — {label}")
                    break

    def _on_job_finished(self, idx: int, success: bool, message: str) -> None:
        if idx < len(self.bars):        # leave indeterminate state on finish
            self.bars[idx].setRange(0, 100)
        self._update_row(idx)
        job = self.jobs[idx]
        if job.status == Status.DONE:
            self._log(f"[{job.name}] ✓ done — {human_size(job.size_in)} → "
                      f"{human_size(job.size_out)} ({self._saved_text(job)} saved, "
                      f"{job.elapsed:.1f}s)\n")
            history.record(job.name, job.size_in, job.size_out,
                           job.output_path, job.elapsed)
        elif job.status == Status.SKIPPED:
            self._log(f"[{job.name}] ↷ skipped — {message}\n")
        elif job.status == Status.STOPPED:
            self._log(f"[{job.name}] ■ stopped\n")
        else:
            self._log(f"[{job.name}] ✗ failed — {message}\n")
        self._update_overall()

    def _on_batch_finished(self, done: int, failed: int) -> None:
        self._set_running_ui(False)
        self.overall.setValue(100)
        self._active_indices = None
        skipped = sum(1 for j in self.jobs if j.status == Status.SKIPPED)
        msg = f"Finished — {done} done"
        if skipped:
            msg += f", {skipped} skipped"
        if failed:
            msg += f", {failed} failed"
        self.status_lbl.setText(msg)
        self._log("=" * 50 + f"\n{msg}\n")
        self._refresh_stats()
        self._cleanup_temp()

        # Completion summary with total space saved + a desktop notification.
        done_jobs = [j for j in self.jobs if j.status == Status.DONE]
        total_in = sum(j.size_in for j in done_jobs)
        total_out = sum(j.size_out for j in done_jobs)
        saved = max(0, total_in - total_out)
        if done_jobs:
            pct = (saved / total_in * 100) if total_in else 0
            body = (f"Compressed {len(done_jobs)} game(s)\n"
                    f"{human_size(total_in)} → {human_size(total_out)}\n"
                    f"Saved {human_size(saved)} ({pct:.0f}%)")
            if failed:
                body += f"\n{failed} failed"
            self._notify("Compression complete", body)
            QMessageBox.information(self, "Compression complete", body)
        elif failed:
            self._notify("Compression failed", f"{failed} game(s) failed.")

    def _notify(self, title: str, body: str) -> None:
        """Best-effort desktop notification via the system tray."""
        try:
            if QSystemTrayIcon.isSystemTrayAvailable():
                if not getattr(self, "_tray", None):
                    self._tray = QSystemTrayIcon(self.window().windowIcon(), self)
                    self._tray.show()
                self._tray.showMessage(title, body, QSystemTrayIcon.Information, 6000)
        except (RuntimeError, AttributeError):
            pass

    def _cleanup_temp(self) -> None:
        """Sweep stale MkPFS spool/.tmp files from the app temp folder."""
        import glob
        cutoff = time.time() - 300
        for pat in ("mkpfs-*.pfsc", "*.tmp"):
            for f in glob.glob(str(TEMP_DIR / pat)):
                try:
                    if os.path.getmtime(f) < cutoff:
                        os.remove(f)
                except OSError:
                    pass

    def _update_overall(self) -> None:
        if not self.jobs:
            return
        # Only count the jobs in the current run (all of them for "Compress All",
        # or just the picked rows for "Compress Selected") so the bar can reach
        # 100%.
        idxs = (self._active_indices if self._active_indices is not None
                else range(len(self.jobs)))
        run = [self.jobs[i] for i in idxs if 0 <= i < len(self.jobs)]
        if not run:
            return
        # Weight each game's progress by its size so the bar tracks real work,
        # not "1 of N games" (a 30 GB game ≠ a 200 MB one).
        weights = [max(j.size_in or (self._est(j).raw if self._est(j) else 0), 1)
                   for j in run]
        done = sum(j.progress * w for j, w in zip(run, weights))
        self.overall.setValue(int(done / sum(weights)))

    # ---------------------------------------------------------------- misc
    def _log(self, text: str) -> None:
        self.log.moveCursor(QTextCursor.End)
        self.log.insertPlainText(text)
        self.log.moveCursor(QTextCursor.End)

    def _on_format_changed(self, _idx: int = 0) -> None:
        # the compression level only applies to the compressed (.ffpfsc) format
        on = bool(self.fmt.currentData())
        self.level.setEnabled(on)
        self.lbl_level.setEnabled(on)

    def _on_shadowmount_toggle(self, on: bool) -> None:
        config.set(CFG, "shadowmount_compatible", on)
        # While SMP mode is on the block size is fixed >= 32 KiB, so auto-fit
        # has no effect — disable it and explain why.
        self.cb_autoblock.setEnabled(not on)
        self.cb_autoblock.setToolTip(
            f"Overridden while 'ShadowMountPlus compatible' is on "
            f"(block fixed at {SHADOWMOUNT_MIN_BLOCK // 1024} KiB)."
            if on else self._autoblock_tip)

    # ---------------------------------------------------------- drag/drop
    def _set_drop_active(self, active: bool) -> None:
        """Toggle the highlighted border on the empty-state drop zone."""
        self.drop_zone.setProperty("active", active)
        self.drop_zone.style().unpolish(self.drop_zone)
        self.drop_zone.style().polish(self.drop_zone)

    def dragEnterEvent(self, e: QDragEnterEvent) -> None:
        if e.mimeData().hasUrls() and any(
                Path(u.toLocalFile()).is_dir() for u in e.mimeData().urls()):
            e.acceptProposedAction()
            self._set_drop_active(True)

    def dragLeaveEvent(self, e) -> None:
        self._set_drop_active(False)

    def dropEvent(self, e: QDropEvent) -> None:
        self._set_drop_active(False)
        if self.runner.running or self._scanning:
            return
        # Scan whatever was dropped on a background thread (the worker finds
        # games inside a parent folder, or takes a dropped game folder directly).
        roots = [u.toLocalFile() for u in e.mimeData().urls()
                 if Path(u.toLocalFile()).is_dir()]
        if roots:
            self._start_scan(roots, self.scan_depth.value())

    # ---- non-native multi-directory picker --------------------------------
    def _select_multiple_dirs(self) -> list[str]:
        dlg = QFileDialog(self, "Select one or more game folders")
        dlg.setFileMode(QFileDialog.Directory)
        dlg.setOption(QFileDialog.DontUseNativeDialog, True)
        dlg.setOption(QFileDialog.ShowDirsOnly, True)
        # Enable multi-selection on the internal views. PySide6's findChildren
        # takes a single type (not a tuple), so query each view type separately.
        views = dlg.findChildren(QListView) + dlg.findChildren(QTreeView)
        for view in views:
            if view.objectName() in ("listView", "treeView"):
                view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        if dlg.exec():
            return dlg.selectedFiles()
        return []

    # ---------------------------------------------------------------- lifecycle
    def shutdown(self) -> None:
        """Stop background threads cleanly when the app closes."""
        if self._scanner is not None and self._scanner.isRunning():
            self._scanner.cancel()
            self._scanner.wait(2000)
        if self._estimator is not None and self._estimator.isRunning():
            self._estimator.stop()
            self._estimator.wait(2000)
        if self.runner.running:
            self.runner.stop()
