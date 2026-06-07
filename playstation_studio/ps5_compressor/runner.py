"""Sequential batch runner that drives mkpfs via QProcess and streams progress."""

from __future__ import annotations

import re
import sys
import time

from PySide6.QtCore import QObject, QProcess, Signal

from .jobs import Job, PackSettings, Status

# Matches the progress line mkpfs writes to stderr, e.g.
#   [####------]  42% compress @ 12.3MB/s ETA 9s
_PROGRESS_RE = re.compile(r"(\d{1,3})%\s+([A-Za-z_]+)")


class BatchRunner(QObject):
    """Runs a list of Jobs one after another, emitting progress signals.

    Only one job runs at a time so each pack gets full CPU and the progress
    stream stays unambiguous.
    """

    jobStarted = Signal(int)                 # index
    jobProgress = Signal(int, int, str)      # index, percent, phase
    jobOutput = Signal(int, str)             # index, raw text line
    jobFinished = Signal(int, bool, str)     # index, success, message
    batchFinished = Signal(int, int)         # done_count, failed_count

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.jobs: list[Job] = []
        self.settings = PackSettings()
        self._order: list[int] = []     # job indices to process, in order
        self._pos = -1                  # position within self._order
        self._index = -1                # current job index (into self.jobs)
        self._proc: QProcess | None = None
        self._stop_requested = False
        self._stderr_buf = ""
        self._t0 = 0.0
        self._done = 0
        self._failed = 0

    @property
    def running(self) -> bool:
        return self._proc is not None

    # ------------------------------------------------------------------ start
    def start(self, jobs: list[Job], settings: PackSettings,
              indices: list[int] | None = None) -> None:
        """Run *jobs*. If *indices* is given, only those positions in *jobs*
        are processed (e.g. "Compress Selected"); the full list is still kept
        so emitted signal indices line up with the UI rows."""
        self.jobs = jobs
        self.settings = settings
        self._order = (list(indices) if indices is not None
                       else list(range(len(jobs))))
        self._pos = -1
        self._index = -1
        self._stop_requested = False
        self._done = 0
        self._failed = 0
        self._next()

    def stop(self) -> None:
        """Abort the current job and cancel the rest of the queue."""
        self._stop_requested = True
        if self._proc is not None:
            self._proc.kill()

    # ------------------------------------------------------------------ queue
    def _next(self) -> None:
        if self._stop_requested:
            self._mark_remaining_stopped()
            self.batchFinished.emit(self._done, self._failed)
            return

        self._pos += 1
        if self._pos >= len(self._order):
            self.batchFinished.emit(self._done, self._failed)
            return
        self._index = self._order[self._pos]

        job = self.jobs[self._index]

        # Resolve output target + skip logic.
        if not job.output_path:
            job.output_path = job.default_output(self.settings)
        actual = job.resolve_actual_output()
        from pathlib import Path
        if not self.settings.overwrite and Path(actual).exists() and Path(actual).is_file():
            job.status = Status.SKIPPED
            job.message = "Output already exists"
            self.jobFinished.emit(self._index, True, job.message)
            self._next()
            return

        # Make sure the output directory exists.
        Path(job.output_path).parent.mkdir(parents=True, exist_ok=True)

        job.compute_input_size()
        job.status = Status.RUNNING
        self._stderr_buf = ""
        self._t0 = time.time()

        cmd = job.build_command(self.settings)
        self.jobStarted.emit(self._index)
        self.jobOutput.emit(self._index, "$ " + " ".join(cmd) + "\n")

        proc = QProcess(self)
        proc.setProgram(cmd[0])
        proc.setArguments(cmd[1:])
        proc.readyReadStandardError.connect(self._on_stderr)
        proc.readyReadStandardOutput.connect(self._on_stdout)
        proc.finished.connect(self._on_finished)
        proc.errorOccurred.connect(self._on_error)
        self._proc = proc
        proc.start()

    # ------------------------------------------------------------------ io
    def _on_stdout(self) -> None:
        if not self._proc:
            return
        data = bytes(self._proc.readAllStandardOutput()).decode("utf-8", "replace")
        if data:
            self.jobOutput.emit(self._index, data)

    def _on_stderr(self) -> None:
        if not self._proc:
            return
        data = bytes(self._proc.readAllStandardError()).decode("utf-8", "replace")
        # Progress uses \r; normalise both \r and \n into line units.
        self._stderr_buf += data
        parts = re.split(r"[\r\n]", self._stderr_buf)
        self._stderr_buf = parts.pop()  # keep trailing partial fragment
        for line in parts:
            line = line.strip()
            if not line:
                continue
            m = _PROGRESS_RE.search(line)
            if m:
                pct = min(100, int(m.group(1)))
                phase = m.group(2)
                self.jobProgress.emit(self._index, pct, phase)
            else:
                self.jobOutput.emit(self._index, line + "\n")

    # ------------------------------------------------------------------ done
    def _on_error(self, err: QProcess.ProcessError) -> None:
        # Most failures surface through finished(); only handle "failed to
        # start" here, which never emits finished().
        if err == QProcess.FailedToStart and self._proc is not None:
            self._complete(False, "Failed to launch mkpfs")

    def _on_finished(self, code: int, status: QProcess.ExitStatus) -> None:
        if self._stop_requested:
            self._complete(False, "Stopped", status_override=Status.STOPPED)
            return
        if status == QProcess.CrashExit or code != 0:
            self._complete(False, f"mkpfs exited with code {code}")
        else:
            self._complete(True, "")

    def _complete(self, success: bool, message: str,
                  status_override: Status | None = None) -> None:
        job = self.jobs[self._index]
        job.elapsed = time.time() - self._t0
        if success:
            job.status = Status.DONE
            job.progress = 100
            actual = job.resolve_actual_output()
            job.output_path = actual
            from pathlib import Path
            try:
                job.size_out = Path(actual).stat().st_size
            except OSError:
                job.size_out = 0
            self._done += 1
        else:
            job.status = status_override or Status.FAILED
            job.message = message
            if job.status == Status.FAILED:
                self._failed += 1
        if self._proc is not None:
            self._proc.deleteLater()
            self._proc = None
        self.jobFinished.emit(self._index, success, message)
        self._next()

    def _mark_remaining_stopped(self) -> None:
        # Stop the current and any not-yet-started jobs in the run order.
        for j in self._order[max(self._pos, 0):]:
            job = self.jobs[j]
            if job.status in (Status.QUEUED, Status.RUNNING):
                job.status = Status.STOPPED
                self.jobFinished.emit(j, False, "Stopped")
