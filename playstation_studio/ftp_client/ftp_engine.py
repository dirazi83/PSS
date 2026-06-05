"""FTP engine (stdlib ftplib) + a serialized worker-thread service.

All blocking FTP calls run on one dedicated background thread that owns the
single control connection, so the GUI never blocks and the connection is
never touched concurrently. The UI talks to :class:`FtpService` by calling
``submit(...)`` and listening to its Qt signals.
"""

from __future__ import annotations

import ftplib
import os
import posixpath
import queue
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QThread, Signal


@dataclass
class FtpOptions:
    host: str = ""
    port: int = 21
    user: str = ""
    password: str = ""
    anonymous: bool = False
    passive: bool = True
    timeout: int = 20


@dataclass
class Entry:
    name: str
    is_dir: bool
    size: int = 0
    modified: str = ""


@dataclass
class TransferJob:
    job_id: int
    direction: str            # "upload" | "download"
    local_path: str
    remote_path: str
    size: int = 0
    status: str = "Queued"
    sent: int = 0
    started: float = field(default=0.0)


class FtpEngine:
    """Thin synchronous wrapper over ftplib.FTP. Not thread-safe by itself —
    always used from inside :class:`FtpService`'s single worker thread."""

    def __init__(self) -> None:
        self.ftp: ftplib.FTP | None = None

    @property
    def connected(self) -> bool:
        return self.ftp is not None

    def connect(self, opt: FtpOptions) -> str:
        ftp = ftplib.FTP()
        ftp.connect(opt.host, int(opt.port), timeout=opt.timeout)
        if opt.anonymous:
            ftp.login("anonymous", "anonymous@")
        else:
            ftp.login(opt.user, opt.password)
        ftp.set_pasv(opt.passive)
        self.ftp = ftp
        return ftp.getwelcome() or "Connected"

    def disconnect(self) -> None:
        if self.ftp is not None:
            try:
                self.ftp.quit()
            except (ftplib.all_errors, OSError):
                try:
                    self.ftp.close()
                except OSError:
                    pass
            self.ftp = None

    def pwd(self) -> str:
        return self.ftp.pwd() if self.ftp else "/"

    def list_dir(self, path: str) -> list[Entry]:
        assert self.ftp is not None
        entries: list[Entry] = []
        # Prefer MLSD (structured, reliable); fall back to LIST parsing.
        try:
            for name, facts in self.ftp.mlsd(path):
                if name in (".", ".."):
                    continue
                is_dir = facts.get("type") in ("dir", "cdir", "pdir")
                entries.append(Entry(name, is_dir,
                                     int(facts.get("size", 0) or 0),
                                     facts.get("modify", "")))
            return sorted(entries, key=lambda e: (not e.is_dir, e.name.lower()))
        except ftplib.error_perm:
            pass
        # LIST fallback (Unix-style)
        lines: list[str] = []
        self.ftp.dir(path, lines.append)
        for line in lines:
            entry = _parse_list_line(line)
            if entry and entry.name not in (".", ".."):
                entries.append(entry)
        return sorted(entries, key=lambda e: (not e.is_dir, e.name.lower()))

    def size(self, remote: str) -> int:
        try:
            self.ftp.voidcmd("TYPE I")
            return self.ftp.size(remote) or 0
        except ftplib.all_errors:
            return 0

    def download(self, remote: str, local: str, progress_cb) -> None:
        total = self.size(remote)
        os.makedirs(os.path.dirname(local) or ".", exist_ok=True)
        done = 0
        self.ftp.voidcmd("TYPE I")
        with open(local, "wb") as fh:
            def cb(chunk: bytes) -> None:
                nonlocal done
                fh.write(chunk)
                done += len(chunk)
                progress_cb(done, total)
            self.ftp.retrbinary(f"RETR {remote}", cb, blocksize=65536)

    def upload(self, local: str, remote: str, progress_cb) -> None:
        total = os.path.getsize(local)
        done = 0
        self.ftp.voidcmd("TYPE I")
        with open(local, "rb") as fh:
            def cb(buf: bytes) -> None:
                nonlocal done
                done += len(buf)
                progress_cb(done, total)
            self.ftp.storbinary(f"STOR {remote}", fh, blocksize=65536, callback=cb)

    def mkdir(self, path: str) -> None:
        self.ftp.mkd(path)

    def delete(self, path: str, is_dir: bool) -> None:
        if is_dir:
            self.ftp.rmd(path)
        else:
            self.ftp.delete(path)

    def rename(self, src: str, dst: str) -> None:
        self.ftp.rename(src, dst)


def _parse_list_line(line: str) -> Entry | None:
    parts = line.split(maxsplit=8)
    if len(parts) < 9:
        return None
    perms, name = parts[0], parts[8]
    try:
        size = int(parts[4])
    except ValueError:
        size = 0
    modified = " ".join(parts[5:8])
    return Entry(name, perms.startswith("d"), size, modified)


class FtpService(QThread):
    """Owns the FTP connection on a background thread; serial command queue."""

    connected = Signal(bool, str)            # ok, message
    disconnected = Signal()
    listed = Signal(str, object, str)        # path, list[Entry], error
    progress = Signal(int, int, int)         # job_id, sent, total
    transfer_done = Signal(int, bool, str)   # job_id, ok, message
    op_done = Signal(str, bool, str)         # op_kind, ok, message
    log = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._engine = FtpEngine()
        self._q: queue.Queue = queue.Queue()
        self._running = True

    # ---- public API (thread-safe: just enqueues) ----
    def submit(self, kind: str, **kw) -> None:
        self._q.put({"kind": kind, **kw})

    def stop(self) -> None:
        self._running = False
        self._q.put({"kind": "__quit__"})

    # ---- worker loop ----
    def run(self) -> None:
        while self._running:
            try:
                op = self._q.get(timeout=0.2)
            except queue.Empty:
                continue
            kind = op.get("kind")
            if kind == "__quit__":
                break
            try:
                self._handle(kind, op)
            except ftplib.all_errors as exc:
                self.log.emit(f"FTP error: {exc}")
                self.op_done.emit(kind, False, str(exc))
            except OSError as exc:
                self.log.emit(f"error: {exc}")
                self.op_done.emit(kind, False, str(exc))
        self._engine.disconnect()

    def _handle(self, kind: str, op: dict) -> None:
        if kind == "connect":
            msg = self._engine.connect(op["options"])
            self.log.emit(f"Connected: {msg.strip()}")
            self.connected.emit(True, msg)
            self.submit("list", path=self._engine.pwd())
        elif kind == "disconnect":
            self._engine.disconnect()
            self.log.emit("Disconnected.")
            self.disconnected.emit()
        elif kind == "list":
            path = op["path"]
            try:
                entries = self._engine.list_dir(path)
                self.listed.emit(path, entries, "")
            except ftplib.all_errors as exc:
                self.listed.emit(path, [], str(exc))
        elif kind == "transfer":
            self._do_transfer(op["job"])
        elif kind == "mkdir":
            self._engine.mkdir(op["path"])
            self.log.emit(f"Created folder: {op['path']}")
            self.op_done.emit("mkdir", True, op["path"])
            self.submit("list", path=posixpath.dirname(op["path"].rstrip("/")) or "/")
        elif kind == "delete":
            self._engine.delete(op["path"], op["is_dir"])
            self.log.emit(f"Deleted: {op['path']}")
            self.op_done.emit("delete", True, op["path"])
            self.submit("list", path=op["parent"])
        elif kind == "rename":
            self._engine.rename(op["src"], op["dst"])
            self.log.emit(f"Renamed: {op['src']} → {op['dst']}")
            self.op_done.emit("rename", True, op["dst"])
            self.submit("list", path=op["parent"])

    def _do_transfer(self, job: TransferJob) -> None:
        job.started = time.time()

        def cb(sent: int, total: int) -> None:
            self.progress.emit(job.job_id, sent, total or job.size)

        try:
            if job.direction == "upload":
                self._engine.upload(job.local_path, job.remote_path, cb)
            else:
                self._engine.download(job.remote_path, job.local_path, cb)
        except ftplib.all_errors as exc:
            self.transfer_done.emit(job.job_id, False, str(exc))
            return
        self.transfer_done.emit(job.job_id, True, "")
