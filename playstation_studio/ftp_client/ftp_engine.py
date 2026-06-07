"""FTP engine (stdlib ftplib) + a serialized worker-thread service.

All blocking FTP calls run on one dedicated background thread that owns the
single control connection, so the GUI never blocks and the connection is
never touched concurrently. The UI talks to :class:`FtpService` by calling
``submit(...)`` and listening to its Qt signals.

Folder transfers are expanded recursively *inside* the worker (so every FTP
call stays on the one connection) and reported as a single aggregate job.
"""

from __future__ import annotations

import ftplib
import os
import posixpath
import queue
import threading
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QThread, Signal


class TransferCancelled(Exception):
    """Raised inside a transfer callback to abort the current transfer."""


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
    size: int = 0             # total bytes (whole tree for a folder)
    is_dir: bool = False
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

    # ---- recursive tree walks (folder transfers) ----
    def walk_remote(self, root: str) -> tuple[list[str], list[tuple[str, int]]]:
        """Return ``(dirs, files)`` under *root* (depth-first).

        ``dirs`` are remote directory paths in creation order; ``files`` are
        ``(remote_path, size)`` tuples.
        """
        dirs: list[str] = []
        files: list[tuple[str, int]] = []
        stack = [root]
        while stack:
            cur = stack.pop()
            for e in self.list_dir(cur):
                full = posixpath.join(cur, e.name)
                if e.is_dir:
                    dirs.append(full)
                    stack.append(full)
                else:
                    files.append((full, e.size or self.size(full)))
        return dirs, files

    def remote_tree_size(self, root: str) -> int:
        _dirs, files = self.walk_remote(root)
        return sum(s for _f, s in files)

    def download_tree(self, remote_root: str, local_root: str,
                      progress_cb, should_cancel) -> None:
        """Recursively download *remote_root* into *local_root*.

        ``progress_cb(done_bytes, total_bytes)`` is called continuously;
        ``should_cancel()`` is polled to allow aborting between/within files.
        """
        dirs, files = self.walk_remote(remote_root)
        total = sum(s for _f, s in files) or 1
        os.makedirs(local_root, exist_ok=True)
        for d in dirs:
            rel = posixpath.relpath(d, remote_root)
            os.makedirs(os.path.join(local_root, rel), exist_ok=True)
        done = 0
        for remote, _size in files:
            if should_cancel():
                raise TransferCancelled()
            rel = posixpath.relpath(remote, remote_root)
            local = os.path.join(local_root, rel)
            os.makedirs(os.path.dirname(local) or ".", exist_ok=True)
            base = done

            def cb(d: int, _t: int) -> None:
                if should_cancel():
                    raise TransferCancelled()
                progress_cb(base + d, total)
            self.download(remote, local, cb)
            done += _size

    def upload_tree(self, local_root: str, remote_root: str,
                    progress_cb, should_cancel) -> None:
        """Recursively upload *local_root* into *remote_root*."""
        files: list[tuple[str, str, int]] = []
        total = 0
        self._mkdir_quiet(remote_root)
        for cur, subdirs, filenames in os.walk(local_root):
            rel = os.path.relpath(cur, local_root)
            remote_dir = remote_root if rel == "." else posixpath.join(
                remote_root, rel.replace(os.sep, "/"))
            self._mkdir_quiet(remote_dir)
            for fn in filenames:
                lp = os.path.join(cur, fn)
                try:
                    sz = os.path.getsize(lp)
                except OSError:
                    sz = 0
                files.append((lp, posixpath.join(remote_dir, fn), sz))
                total += sz
        total = total or 1
        done = 0
        for lp, rp, sz in files:
            if should_cancel():
                raise TransferCancelled()
            base = done

            def cb(d: int, _t: int) -> None:
                if should_cancel():
                    raise TransferCancelled()
                progress_cb(base + d, total)
            self.upload(lp, rp, cb)
            done += sz

    def _mkdir_quiet(self, path: str) -> None:
        try:
            self.ftp.mkd(path)
        except ftplib.all_errors:
            pass        # already exists / not permitted — keep going

    def mkdir(self, path: str) -> None:
        self.ftp.mkd(path)

    def delete(self, path: str, is_dir: bool) -> None:
        if is_dir:
            self.ftp.rmd(path)
        else:
            self.ftp.delete(path)

    def delete_recursive(self, path: str) -> None:
        """Remove a directory and everything inside it (depth-first)."""
        dirs, files = self.walk_remote(path)
        for f, _s in files:
            try:
                self.ftp.delete(f)
            except ftplib.all_errors:
                pass
        for d in sorted(dirs, key=len, reverse=True):    # deepest first
            try:
                self.ftp.rmd(d)
            except ftplib.all_errors:
                pass
        self.ftp.rmd(path)

    def rename(self, src: str, dst: str) -> None:
        self.ftp.rename(src, dst)

    def chmod(self, path: str, mode: str) -> str:
        """SITE CHMOD <mode> <path>. Returns the server reply."""
        return self.ftp.sendcmd(f"SITE CHMOD {mode} {path}")

    def raw(self, command: str) -> str:
        """Send an arbitrary FTP command and return the server's reply."""
        return self.ftp.sendcmd(command)


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
    transfer_done = Signal(int, bool, str)   # job_id, ok, message ("" / "cancelled")
    op_done = Signal(str, bool, str)         # op_kind, ok, message
    log = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._engine = FtpEngine()
        self._q: queue.Queue = queue.Queue()
        self._running = True
        # transfer control (set from the GUI thread, read on the worker)
        self._cancelled: set[int] = set()
        self._cancel_all = False
        self._lock = threading.Lock()
        self._resume = threading.Event()
        self._resume.set()                   # not paused by default
        self._current_job: int | None = None

    # ---- public API (thread-safe: just enqueues / flags) ----
    def submit(self, kind: str, **kw) -> None:
        self._q.put({"kind": kind, **kw})

    def cancel(self, job_id: int) -> None:
        with self._lock:
            self._cancelled.add(job_id)

    def cancel_all(self) -> None:
        with self._lock:
            self._cancel_all = True
        self._resume.set()                   # unblock a paused worker so it can stop

    def pause(self) -> None:
        self._resume.clear()

    def resume(self) -> None:
        self._resume.set()

    @property
    def paused(self) -> bool:
        return not self._resume.is_set()

    def stop(self) -> None:
        self._running = False
        self._cancel_all = True
        self._resume.set()
        self._q.put({"kind": "__quit__"})

    # ---- cancel helpers (worker side) ----
    def _should_cancel(self, job_id: int) -> bool:
        with self._lock:
            return self._cancel_all or job_id in self._cancelled

    def _clear_cancel(self, job_id: int) -> None:
        with self._lock:
            self._cancelled.discard(job_id)

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
            with self._lock:
                self._cancel_all = False
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
            if op.get("recursive") and op["is_dir"]:
                self._engine.delete_recursive(op["path"])
            else:
                self._engine.delete(op["path"], op["is_dir"])
            self.log.emit(f"Deleted: {op['path']}")
            self.op_done.emit("delete", True, op["path"])
            self.submit("list", path=op["parent"])
        elif kind == "rename":
            self._engine.rename(op["src"], op["dst"])
            self.log.emit(f"Renamed: {op['src']} → {op['dst']}")
            self.op_done.emit("rename", True, op["dst"])
            self.submit("list", path=op["parent"])
        elif kind == "chmod":
            reply = self._engine.chmod(op["path"], op["mode"])
            self.log.emit(f"chmod {op['mode']} {op['path']} → {reply}")
            self.op_done.emit("chmod", True, reply)
            self.submit("list", path=op["parent"])
        elif kind == "raw":
            reply = self._engine.raw(op["command"])
            self.log.emit(f"> {op['command']}\n{reply}")
            self.op_done.emit("raw", True, reply)

    def _do_transfer(self, job: TransferJob) -> None:
        # Honor pause; allow cancel to break out of a paused wait.
        while not self._resume.wait(timeout=0.2):
            if self._should_cancel(job.job_id):
                break
        if self._should_cancel(job.job_id):
            self._clear_cancel(job.job_id)
            self.transfer_done.emit(job.job_id, False, "cancelled")
            return

        self._current_job = job.job_id
        job.started = time.time()

        def cb(sent: int, total: int) -> None:
            self.progress.emit(job.job_id, sent, total or job.size)

        def should_cancel() -> bool:
            return self._should_cancel(job.job_id)

        try:
            if job.is_dir:
                if job.direction == "upload":
                    self._engine.upload_tree(job.local_path, job.remote_path,
                                             cb, should_cancel)
                else:
                    self._engine.download_tree(job.remote_path, job.local_path,
                                               cb, should_cancel)
            elif job.direction == "upload":
                self._engine.upload(job.local_path, job.remote_path,
                                    lambda s, t: (cb(s, t), self._tick(job.job_id))[0])
            else:
                self._engine.download(job.remote_path, job.local_path,
                                      lambda s, t: (cb(s, t), self._tick(job.job_id))[0])
        except TransferCancelled:
            self._clear_cancel(job.job_id)
            self.transfer_done.emit(job.job_id, False, "cancelled")
            return
        except ftplib.all_errors as exc:
            self.transfer_done.emit(job.job_id, False, str(exc))
            return
        finally:
            self._current_job = None
        self.transfer_done.emit(job.job_id, True, "")

    def _tick(self, job_id: int) -> None:
        """For single-file transfers: raise to abort if cancelled mid-stream."""
        if self._should_cancel(job_id):
            raise TransferCancelled()
