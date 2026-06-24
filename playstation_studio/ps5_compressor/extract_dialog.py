"""PFS Extract dialog — unpack .ffpfs / .ffpfsc images back to folders."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .extractor import ExtractJob, ExtractRunner
from .jobs import PFS_EXTENSIONS, Status
from ..shared.formatting import human_size
from ..shared.theme import Palette

_PFS_FILTER = "PFS images (*.ffpfs *.ffpfsc *.pfs);;All files (*)"
_OUT_SUFFIX = "_extracted"


class ExtractDialog(QDialog):
    """Pick one or more PFS images and unpack each to a folder via mkpfs."""

    COLS = ["Image", "Status", "Result"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Extract PFS Image")
        self.setMinimumSize(720, 560)
        self.setAcceptDrops(True)

        self.jobs: list[ExtractJob] = []
        self.bars: list[QProgressBar] = []
        self.runner = ExtractRunner(self)
        self._wire_runner()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 16)
        lay.setSpacing(12)

        intro = QLabel("Unpack <b>.ffpfs</b> / <b>.ffpfsc</b> images back to a "
                       "folder using the bundled MkPFS engine.")
        intro.setStyleSheet(f"color:{Palette.text_dim};")
        lay.addWidget(intro)

        # toolbar
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.btn_add = QPushButton("＋  Add Images…")
        self.btn_add.clicked.connect(self.on_add)
        self.btn_remove = QPushButton("－  Remove")
        self.btn_remove.clicked.connect(self.on_remove)
        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setObjectName("Ghost")
        self.btn_clear.clicked.connect(self.on_clear)
        bar.addWidget(self.btn_add)
        bar.addWidget(self.btn_remove)
        bar.addStretch(1)
        bar.addWidget(self.btn_clear)
        lay.addLayout(bar)

        # table
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.Stretch)
        lay.addWidget(self.table, stretch=2)

        # destination
        dest_row = QHBoxLayout()
        dest_row.setSpacing(8)
        dest_lbl = QLabel("Extract to")
        dest_lbl.setStyleSheet(f"color:{Palette.text_dim}; font-weight:600;")
        self.dest_mode = QComboBox()
        self.dest_mode.addItem("Beside each image (in a subfolder)", "beside")
        self.dest_mode.addItem("Custom folder…", "custom")
        self.dest_mode.currentIndexChanged.connect(self._sync_dest)
        self.dest_path = QLineEdit()
        self.dest_path.setPlaceholderText("Pick a destination folder")
        self.btn_dest = QPushButton("…")
        self.btn_dest.setFixedWidth(40)
        self.btn_dest.clicked.connect(self.on_pick_dest)
        dest_row.addWidget(dest_lbl)
        dest_row.addWidget(self.dest_mode)
        dest_row.addWidget(self.dest_path, stretch=1)
        dest_row.addWidget(self.btn_dest)
        lay.addLayout(dest_row)

        # options
        opt_row = QHBoxLayout()
        opt_row.setSpacing(14)
        self.cb_overwrite = QCheckBox("Overwrite existing output")
        self.cb_overwrite.setChecked(True)
        self.cb_newcrypt = QCheckBox("newCrypt key derivation")
        self.cb_newcrypt.setToolTip("Use the alternate newCrypt EKPFS derivation "
                                    "for encrypted images.")
        opt_row.addWidget(self.cb_overwrite)
        opt_row.addWidget(self.cb_newcrypt)
        opt_row.addStretch(1)
        lay.addLayout(opt_row)

        key_row = QHBoxLayout()
        key_row.setSpacing(8)
        key_lbl = QLabel("EKPFS key")
        key_lbl.setStyleSheet(f"color:{Palette.text_dim};")
        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText("Optional — 64 hex chars, only for encrypted images")
        key_row.addWidget(key_lbl)
        key_row.addWidget(self.key_edit, stretch=1)
        lay.addLayout(key_row)

        # log
        self.log = QPlainTextEdit()
        self.log.setObjectName("Log")
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        self.log.setFixedHeight(120)
        lay.addWidget(self.log, stretch=1)

        # footer
        foot = QHBoxLayout()
        foot.setSpacing(10)
        self.status_lbl = QLabel("Add one or more images to extract.")
        self.status_lbl.setStyleSheet(f"color:{Palette.text_dim};")
        foot.addWidget(self.status_lbl, stretch=1)
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setObjectName("Danger")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.on_stop)
        self.btn_close = QPushButton("Close")
        self.btn_close.setObjectName("Ghost")
        self.btn_close.clicked.connect(self.reject)
        self.btn_extract = QPushButton("▶  Extract")
        self.btn_extract.setObjectName("Primary")
        self.btn_extract.clicked.connect(self.on_extract)
        foot.addWidget(self.btn_stop)
        foot.addWidget(self.btn_close)
        foot.addWidget(self.btn_extract)
        lay.addLayout(foot)

        self._sync_dest()

    # ------------------------------------------------------------------ jobs
    def _add_paths(self, paths: list[str]) -> None:
        existing = {j.image_path for j in self.jobs}
        added = 0
        for p in paths:
            if (Path(p).suffix.lower() in PFS_EXTENSIONS
                    and p not in existing and Path(p).is_file()):
                self.jobs.append(ExtractJob(image_path=p, out_dir=""))
                existing.add(p)
                added += 1
        if added:
            self._rebuild()
            self.status_lbl.setText(f"{len(self.jobs)} image(s) queued.")

    def on_add(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select PFS image(s)", "", _PFS_FILTER)
        if files:
            self._add_paths(files)

    def on_remove(self) -> None:
        if self.runner.running:
            return
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            if 0 <= r < len(self.jobs):
                del self.jobs[r]
        self._rebuild()

    def on_clear(self) -> None:
        if self.runner.running:
            return
        self.jobs.clear()
        self._rebuild()
        self.log.clear()

    def _rebuild(self) -> None:
        self.table.setRowCount(0)
        self.bars = []
        for job in self.jobs:
            self._append_row(job)

    def _append_row(self, job: ExtractJob) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        name_item = QTableWidgetItem("  " + job.name)
        name_item.setToolTip(job.image_path)
        self.table.setItem(r, 0, name_item)
        self.table.setItem(r, 1, self._status_item(job))
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(job.progress)
        bar.setTextVisible(True)
        bar.setFormat("")
        self.table.setCellWidget(r, 2, bar)
        self.bars.append(bar)

    def _status_item(self, job: ExtractJob) -> QTableWidgetItem:
        item = QTableWidgetItem(job.status.value)
        item.setForeground(QColor(Palette.status_color(job.status.value)))
        if job.message:
            item.setToolTip(job.message)
        return item

    # ------------------------------------------------------------ destination
    def _sync_dest(self) -> None:
        custom = self.dest_mode.currentData() == "custom"
        self.dest_path.setVisible(custom)
        self.btn_dest.setVisible(custom)

    def on_pick_dest(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose destination folder")
        if d:
            self.dest_path.setText(d)

    def _resolve_out_dir(self, image_path: str) -> str:
        stem = Path(image_path).stem
        if self.dest_mode.currentData() == "custom":
            base = self.dest_path.text().strip() or str(Path(image_path).parent)
        else:
            base = str(Path(image_path).parent)
        return str(Path(base) / f"{stem}{_OUT_SUFFIX}")

    # ----------------------------------------------------------------- run
    def on_extract(self) -> None:
        if self.runner.running:
            return
        if not self.jobs:
            QMessageBox.information(self, "Nothing to extract",
                                   "Add one or more PFS images first.")
            return
        if (self.dest_mode.currentData() == "custom"
                and not self.dest_path.text().strip()):
            QMessageBox.information(self, "Destination needed",
                                   "Pick a custom destination folder, or choose "
                                   "'Beside each image'.")
            return
        for job in self.jobs:
            job.out_dir = self._resolve_out_dir(job.image_path)
            job.status = Status.QUEUED
            job.progress = 0
            job.message = ""
        self._rebuild()
        self._set_running(True)
        self._log("=" * 50 + f"\nExtracting {len(self.jobs)} image(s)…\n")
        self.runner.start(
            self.jobs,
            overwrite=self.cb_overwrite.isChecked(),
            ekpfs_key=self.key_edit.text(),
            new_crypt=self.cb_newcrypt.isChecked(),
        )

    def on_stop(self) -> None:
        self.status_lbl.setText("Stopping…")
        self.runner.stop()

    def _set_running(self, running: bool) -> None:
        self.btn_extract.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        for w in (self.btn_add, self.btn_remove, self.btn_clear,
                  self.btn_close, self.dest_mode, self.btn_dest):
            w.setEnabled(not running)

    # --------------------------------------------------------- runner signals
    def _wire_runner(self) -> None:
        self.runner.jobStarted.connect(self._on_started)
        self.runner.jobOutput.connect(self._on_output)
        self.runner.jobFinished.connect(self._on_finished)
        self.runner.batchFinished.connect(self._on_batch_finished)

    def _on_started(self, idx: int) -> None:
        self.table.setItem(idx, 1, self._status_item(self.jobs[idx]))
        if idx < len(self.bars):
            self.bars[idx].setRange(0, 0)        # indeterminate
            self.bars[idx].setFormat("Extracting…")
        self.table.selectRow(idx)
        self.status_lbl.setText(f"Extracting  {self.jobs[idx].name}  "
                                f"({idx + 1}/{len(self.jobs)})…")

    def _on_output(self, idx: int, text: str) -> None:
        name = self.jobs[idx].name if 0 <= idx < len(self.jobs) else "?"
        for line in text.splitlines():
            s = line.strip()
            if s:
                self._log(f"[{name}] {s}\n")

    def _on_finished(self, idx: int, success: bool, message: str) -> None:
        job = self.jobs[idx]
        if idx < len(self.bars):
            bar = self.bars[idx]
            bar.setRange(0, 100)
            bar.setValue(100 if success else 0)
            bar.setFormat("Done" if success else "")
        result = ""
        if job.status == Status.DONE:
            result = (f"{job.files:,} files · {human_size(job.bytes_out)} "
                      f"· {job.elapsed:.1f}s")
            self._log(f"[{job.name}] ✓ extracted to {job.out_dir}\n")
        elif job.status == Status.STOPPED:
            result = "stopped"
            self._log(f"[{job.name}] ■ stopped\n")
        else:
            result = message
            self._log(f"[{job.name}] ✗ failed — {message}\n")
        self.table.setItem(idx, 1, self._status_item(job))
        self.table.setItem(idx, 2, QTableWidgetItem(result))

    def _on_batch_finished(self, done: int, failed: int) -> None:
        self._set_running(False)
        msg = f"Finished — {done} extracted"
        if failed:
            msg += f", {failed} failed"
        self.status_lbl.setText(msg)
        self._log("=" * 50 + f"\n{msg}\n")
        if done and not failed:
            QMessageBox.information(self, "Extraction complete",
                                   f"Extracted {done} image(s).")

    # ------------------------------------------------------------------ misc
    def _log(self, text: str) -> None:
        self.log.moveCursor(QTextCursor.End)
        self.log.insertPlainText(text)
        self.log.moveCursor(QTextCursor.End)

    # ----------------------------------------------------------- drag/drop
    def dragEnterEvent(self, e: QDragEnterEvent) -> None:
        if e.mimeData().hasUrls() and any(
                Path(u.toLocalFile()).suffix.lower() in PFS_EXTENSIONS
                for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent) -> None:
        if self.runner.running:
            return
        self._add_paths([u.toLocalFile() for u in e.mimeData().urls()])

    def reject(self) -> None:
        if self.runner.running:
            self.runner.stop()
        super().reject()
