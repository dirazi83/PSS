"""PS5 PFS compressor — embeddable tab widget."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import (
    QColor, QDragEnterEvent, QDropEvent, QIcon, QTextCursor,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListView, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QSlider, QSpinBox,
    QStackedWidget, QTableWidget, QTableWidgetItem, QTreeView,
    QVBoxLayout, QWidget,
)

from .jobs import Job, PackSettings, Status, find_game_dirs
from .runner import BatchRunner
from ..shared.config import config
from ..shared.diskutil import is_cloud_synced_path, is_network_path
from ..shared.paths import (
    TEMP_MODE_APP, TEMP_MODE_CUSTOM, TEMP_MODE_GAME, set_temp_policy,
    temp_mode as get_temp_mode, custom_temp_path,
)
from ..shared.theme import Palette
from ..shared.formatting import human_size

CFG = "ps5"


class Ps5CompressTab(QWidget):
    COLS = ["Game", "Status", "Progress", "Input", "Output", "Saved"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.jobs: list[Job] = []
        self.bars: list[QProgressBar] = []
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
        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setObjectName("Ghost")
        self.btn_scan.clicked.connect(self.on_scan_folder)
        self.btn_add.clicked.connect(self.on_add_games)
        self.btn_remove.clicked.connect(self.on_remove_selected)
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
        bar.addStretch(1)
        self.stats_pill = QLabel("0 games")
        self.stats_pill.setObjectName("Pill")
        bar.addWidget(self.stats_pill)
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
    def _build_settings_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("Panel")
        panel.setFixedWidth(320)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.setSpacing(14)

        title = QLabel("PACK SETTINGS")
        title.setObjectName("SectionTitle")
        lay.addWidget(title)

        # output dir
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

        # version — PS5 only
        lay.addWidget(self._field_label("Console profile"))
        version_badge = QLabel("PS5")
        version_badge.setObjectName("VersionBadge")
        version_badge.setToolTip("Output is built with the PS5 PFS profile.")
        badge_row = QHBoxLayout()
        badge_row.addWidget(version_badge)
        badge_row.addStretch(1)
        lay.addLayout(badge_row)

        # compress + level
        self.cb_compress = QCheckBox("PFSC compression")
        self.cb_compress.setChecked(True)
        self.cb_compress.toggled.connect(self._on_compress_toggle)
        lay.addWidget(self.cb_compress)

        self.lbl_level = QLabel("Compression level: 9")
        self.lbl_level.setStyleSheet(f"color:{Palette.text_dim}; font-size:12px;")
        lay.addWidget(self.lbl_level)
        self.level = QSlider(Qt.Horizontal)
        self.level.setRange(0, 9)
        self.level.setValue(9)
        self.level.valueChanged.connect(
            lambda v: self.lbl_level.setText(f"Compression level: {v}"))
        lay.addWidget(self.level)

        # cpu
        lay.addWidget(self._field_label("CPU cores (0 = auto)"))
        self.cpu = QSpinBox()
        self.cpu.setRange(0, 256)
        self.cpu.setValue(0)
        lay.addWidget(self.cpu)

        # temp folder policy
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

        # toggles
        self.cb_autoblock = QCheckBox("Shrink small-file games (auto block size)")
        self.cb_autoblock.setToolTip(
            "Pick the block size that minimises per-file padding. Games with "
            "thousands of tiny files (e.g. Minecraft) can otherwise pack LARGER "
            "than the original because each file is padded to a 64 KiB block.")
        self.cb_autoblock.setChecked(bool(config.get(CFG, "auto_block_size", True)))
        self.cb_autoblock.toggled.connect(
            lambda on: config.set(CFG, "auto_block_size", on))
        self.cb_skipexec = QCheckBox("Store executables uncompressed")
        self.cb_skipexec.setChecked(True)
        self.cb_verify = QCheckBox("Verify after packing")
        self.cb_encrypt = QCheckBox("Encrypt blocks (AES-XTS)")
        self.cb_require = QCheckBox("Require game files")
        self.cb_lowmem = QCheckBox("Low-memory mode (1 core, slower)")
        self.cb_lowmem.setToolTip("Compress one file at a time to minimise peak "
                                  "RAM. Use on machines with little free memory.")
        self.cb_lowmem.setChecked(bool(config.get(CFG, "low_memory", False)))
        self.cb_lowmem.toggled.connect(
            lambda on: config.set(CFG, "low_memory", on))
        self.cb_overwrite = QCheckBox("Overwrite existing images")
        for cb in (self.cb_autoblock, self.cb_skipexec, self.cb_verify,
                   self.cb_encrypt, self.cb_require, self.cb_lowmem,
                   self.cb_overwrite):
            lay.addWidget(cb)

        lay.addStretch(1)
        credit = QLabel('Compression engine: <a href="https://github.com/PSBrew/MkPFS">'
                        'MkPFS</a> by PSBrew')
        credit.setOpenExternalLinks(True)
        credit.setStyleSheet(f"color:{Palette.text_faint}; font-size:11px;")
        lay.addWidget(credit)
        return panel

    def _field_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color:{Palette.text_dim}; font-size:12px; font-weight:600;")
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
        self.btn_start = QPushButton("▶  Compress All")
        self.btn_start.setObjectName("Primary")
        self.btn_start.clicked.connect(self.on_start)
        lay.addWidget(self.btn_stop)
        lay.addWidget(self.btn_start)
        return f

    # =========================================================== job mgmt
    def _add_job(self, source_dir: str) -> bool:
        source_dir = str(Path(source_dir).resolve())
        if any(j.source_dir == source_dir for j in self.jobs):
            return False
        self.jobs.append(Job(source_dir=source_dir))
        return True

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

        self.table.setItem(r, 3, self._cell(human_size(job.size_in) if job.size_in else "—"))
        self.table.setItem(r, 4, self._cell(human_size(job.size_out) if job.size_out else "—"))
        self.table.setItem(r, 5, self._cell(self._saved_text(job)))

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

    def _update_row(self, idx: int) -> None:
        job = self.jobs[idx]
        self.table.setItem(idx, 1, self._status_item(job))
        if idx < len(self.bars):
            self.bars[idx].setValue(job.progress)
            self.bars[idx].setFormat(job.phase or "")
        self.table.setItem(idx, 3, self._cell(human_size(job.size_in) if job.size_in else "—"))
        self.table.setItem(idx, 4, self._cell(human_size(job.size_out) if job.size_out else "—"))
        self.table.setItem(idx, 5, self._cell(self._saved_text(job)))

    def _refresh_stats(self) -> None:
        total_in = sum(j.size_in for j in self.jobs)
        n = len(self.jobs)
        txt = f"{n} game{'s' if n != 1 else ''}"
        if total_in:
            txt += f"  ·  {human_size(total_in)}"
        self.stats_pill.setText(txt)

    # ============================================================ actions
    def on_scan_folder(self) -> None:
        parent = QFileDialog.getExistingDirectory(self, "Select a folder of game dumps")
        if not parent:
            return
        depth = self.scan_depth.value()
        matches = find_game_dirs(parent, max_depth=depth)
        added = sum(1 for d in matches if self._add_job(d))
        self._rebuild_table()
        dupes = len(matches) - added
        msg = f"Scanned {parent} (depth {depth}): found {len(matches)} game(s)"
        if dupes:
            msg += f", {added} new ({dupes} already listed)"
        self._log(msg + ".\n")
        if not matches:
            QMessageBox.information(self, "No games found",
                f"No folders containing eboot.bin or sce_sys were found within "
                f"{depth} level(s) of:\n\n{parent}\n\n"
                "Try increasing the depth next to the Scan button.")

    def on_add_games(self) -> None:
        dirs = self._select_multiple_dirs()
        added = sum(1 for d in dirs if self._add_job(d))
        self._rebuild_table()
        if added:
            self._log(f"Added {added} game(s).\n")

    def on_remove_selected(self) -> None:
        if self.runner.running:
            return
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            if 0 <= r < len(self.jobs):
                del self.jobs[r]
        self._rebuild_table()

    def on_clear(self) -> None:
        if self.runner.running:
            return
        self.jobs.clear()
        self._rebuild_table()
        self.log.clear()

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
            compress=self.cb_compress.isChecked(),
            compression_level=self.level.value(),
            verify=self.cb_verify.isChecked(),
            encrypted=self.cb_encrypt.isChecked(),
            require_game_files=self.cb_require.isChecked(),
            skip_executable_compression=self.cb_skipexec.isChecked(),
            cpu_count=self.cpu.value(),
            low_memory=self.cb_lowmem.isChecked(),
            overwrite=self.cb_overwrite.isChecked(),
            auto_block_size=self.cb_autoblock.isChecked(),
            temp_mode=self.temp_mode.currentData() or TEMP_MODE_APP,
            temp_path=self.temp_path.text().strip(),
        )

    def on_start(self) -> None:
        if self.runner.running:
            return
        if not self.jobs:
            QMessageBox.information(self, "Nothing to do", "Add at least one game first.")
            return
        # Warn if any source lives in iCloud (Desktop & Documents sync / iCloud
        # Drive): macOS downloads files on demand and evicts them under disk
        # pressure, so packing crawls or fails. This is the #1 cause of a
        # compression that looks hung on a Mac.
        cloud_jobs = [j for j in self.jobs if is_cloud_synced_path(j.source_dir)]
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
        net_jobs = [j for j in self.jobs
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
        # reset transient state
        for j in self.jobs:
            if j.status != Status.DONE or self.cb_overwrite.isChecked():
                j.status = Status.QUEUED
                j.progress = 0
                j.phase = ""
                j.size_out = 0
                j.output_path = ""
        self._rebuild_table()
        self.overall.setValue(0)
        self._set_running_ui(True)
        self._log("=" * 50 + "\nStarting batch…\n")
        self.runner.start(self.jobs, self._collect_settings())

    def on_stop(self) -> None:
        self.status_lbl.setText("Stopping…")
        self.runner.stop()

    def _set_running_ui(self, running: bool) -> None:
        self.btn_start.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        for w in (self.btn_scan, self.btn_add, self.btn_remove, self.btn_clear):
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
        skipped = sum(1 for j in self.jobs if j.status == Status.SKIPPED)
        msg = f"Finished — {done} done"
        if skipped:
            msg += f", {skipped} skipped"
        if failed:
            msg += f", {failed} failed"
        self.status_lbl.setText(msg)
        self._log("=" * 50 + f"\n{msg}\n")
        self._refresh_stats()

    def _update_overall(self) -> None:
        if not self.jobs:
            return
        total = sum(j.progress for j in self.jobs)
        self.overall.setValue(int(total / len(self.jobs)))

    # ---------------------------------------------------------------- misc
    def _log(self, text: str) -> None:
        self.log.moveCursor(QTextCursor.End)
        self.log.insertPlainText(text)
        self.log.moveCursor(QTextCursor.End)

    def _on_compress_toggle(self, on: bool) -> None:
        self.level.setEnabled(on)
        self.lbl_level.setEnabled(on)

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
        if self.runner.running:
            return
        depth = self.scan_depth.value()
        targets: list[str] = []
        non_games: list[str] = []
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if not Path(p).is_dir():
                continue
            if Job(source_dir=p).looks_like_game():
                targets.append(p)
            else:
                # Not a game itself — search inside it like Scan Folder does.
                found = find_game_dirs(p, max_depth=depth)
                targets.extend(found)
                if not found:
                    non_games.append(p)

        added = sum(1 for d in targets if self._add_job(d))
        if added:
            self._rebuild_table()
            self._log(f"Added {added} game(s) via drag & drop.\n")
        if non_games and not added:
            names = ", ".join(Path(p).name for p in non_games)
            self._log(f"Ignored (no game dump found within depth {depth}): {names}\n")
            QMessageBox.information(self, "No games found",
                f"No folders containing eboot.bin or sce_sys were found within "
                f"{depth} level(s) of what you dropped.\n\n"
                "Drop a game folder directly, or raise the depth next to Scan.")

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
