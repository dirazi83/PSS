"""PFS extraction runner — drives ``mkpfs unpack`` via QProcess, sequentially.

Unpacks ``.ffpfs`` / ``.ffpfsc`` images back to a folder. mkpfs emits no
per-percent progress for unpack (it prints a summary at the end), so the UI
shows a busy bar while a job runs and parses the final "Files/Bytes written"
summary for the result.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Signal

from .jobs import Status, mkpfs_command

_FILES_RE = re.compile(r"Files written:\s*([\d,]+)")
_BYTES_RE = re.compile(r"Bytes written:\s*([\d,]+)")


@dataclass
class ExtractJob:
    """A single PFS image to unpack into ``out_dir``."""

    image_path: str
    out_dir: str
    status: Status = Status.QUEUED
    progress: int = 0
    message: str = ""
    files: int = 0
    bytes_out: int = 0
    elapsed: float = 0.0

    @property
    def name(self) -> str:
        return Path(self.image_path).name


class ExtractRunner(QObject):
    """Runs a list of ExtractJobs one after another (one at a time)."""

    jobStarted = Signal(int)              # index
    jobOutput = Signal(int, str)          # index, raw text
    jobFinished = Signal(int, bool, str)  # index, success, message
    batchFinished = Signal(int, int)      # done_count, failed_count

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.jobs: list[ExtractJob] = []
        self.overwrite = True
        self.ekpfs_key = ""
        self.new_crypt = False
        self._pos = -1
        self._proc: QProcess | None = None
        self._stop = False
        self._t0 = 0.0
        self._done = 0
        self._failed = 0

    @property
    def running(self) -> bool:
        return self._proc is not None

    def start(self, jobs: list[ExtractJob], overwrite: bool = True,
              ekpfs_key: str = "", new_crypt: bool = False) -> None:
        self.jobs = jobs
        self.overwrite = overwrite
        self.ekpfs_key = ekpfs_key.strip()
        self.new_crypt = new_crypt
        self._pos = -1
        self._stop = False
        self._done = 0
        self._failed = 0
        self._next()

    def stop(self) -> None:
        self._stop = True
        if self._proc is not None:
            self._proc.kill()

    def _build_cmd(self, job: ExtractJob) -> list[str]:
        cmd = mkpfs_command() + ["unpack", job.image_path, job.out_dir]
        if self.overwrite:
            cmd += ["--overwrite"]
        if self.ekpfs_key:
            cmd += ["--ekpfs-key", self.ekpfs_key]
        if self.new_crypt:
            cmd += ["--new-crypt"]
        return cmd

    def _next(self) -> None:
        if self._stop:
            for j in self.jobs[max(self._pos, 0):]:
                if j.status in (Status.QUEUED, Status.RUNNING):
                    j.status = Status.STOPPED
            self.batchFinished.emit(self._done, self._failed)
            return
        self._pos += 1
        if self._pos >= len(self.jobs):
            self.batchFinished.emit(self._done, self._failed)
            return

        job = self.jobs[self._pos]
        Path(job.out_dir).mkdir(parents=True, exist_ok=True)
        job.status = Status.RUNNING
        self._t0 = time.time()
        cmd = self._build_cmd(job)
        self.jobStarted.emit(self._pos)
        self.jobOutput.emit(self._pos, "$ " + " ".join(cmd) + "\n")

        proc = QProcess(self)
        proc.setProgram(cmd[0])
        proc.setArguments(cmd[1:])
        proc.readyReadStandardOutput.connect(self._on_out)
        proc.readyReadStandardError.connect(self._on_err)
        proc.finished.connect(self._on_finished)
        proc.errorOccurred.connect(self._on_error)
        self._proc = proc
        proc.start()

    def _emit(self, data: str) -> None:
        job = self.jobs[self._pos]
        for line in re.split(r"[\r\n]", data):
            line = line.strip()
            if not line:
                continue
            self.jobOutput.emit(self._pos, line + "\n")
            m = _FILES_RE.search(line)
            if m:
                job.files = int(m.group(1).replace(",", ""))
            m = _BYTES_RE.search(line)
            if m:
                job.bytes_out = int(m.group(1).replace(",", ""))

    def _on_out(self) -> None:
        if self._proc:
            self._emit(bytes(self._proc.readAllStandardOutput()).decode("utf-8", "replace"))

    def _on_err(self) -> None:
        if self._proc:
            self._emit(bytes(self._proc.readAllStandardError()).decode("utf-8", "replace"))

    def _on_error(self, err: QProcess.ProcessError) -> None:
        if err == QProcess.FailedToStart and self._proc is not None:
            self._complete(False, "Failed to launch mkpfs")

    def _on_finished(self, code: int, status: QProcess.ExitStatus) -> None:
        if self._stop:
            self._complete(False, "Stopped", Status.STOPPED)
            return
        if status == QProcess.CrashExit or code != 0:
            self._complete(False, f"mkpfs exited with code {code}")
        else:
            self._complete(True, "")

    def _complete(self, success: bool, message: str,
                  override: Status | None = None) -> None:
        job = self.jobs[self._pos]
        job.elapsed = time.time() - self._t0
        if success:
            job.status = Status.DONE
            job.progress = 100
            self._done += 1
        else:
            job.status = override or Status.FAILED
            job.message = message
            if job.status == Status.FAILED:
                self._failed += 1
        if self._proc is not None:
            self._proc.deleteLater()
            self._proc = None
        self.jobFinished.emit(self._pos, success, message)
        self._next()
