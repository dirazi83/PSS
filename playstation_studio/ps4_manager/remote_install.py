"""PS4 remote-install support, modernized.

Replaces the original Twisted-based server with Python's stdlib
``http.server`` (ThreadingHTTPServer), and keeps the Remote PKG Installer
JSON protocol (PS4 homebrew listening on port 12800).

All paths are computed cross-platform.
"""

from __future__ import annotations

import ast
import datetime
import functools
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from PySide6.QtCore import QThread, Signal

from .pkg_parser import convert_bytes

PS4_API_PORT = 12800       # PS4 Remote PKG Installer
DPI_V2_PORT = 12800        # etaHEN DPI v2 web server (POST /upload)
DPI_V1_PORT = 9090         # etaHEN DPI v1 JSON-over-TCP

# Install methods, surfaced in the UI.
METHOD_PS4_RPI = "ps4_rpi"
METHOD_PS5_DPI_V2 = "ps5_dpi_v2"
METHOD_PS5_DPI_V1 = "ps5_dpi_v1"

INSTALL_METHODS = [
    (METHOD_PS4_RPI, "Remote PKG Installer (:12800)"),
    (METHOD_PS5_DPI_V2, "PS5 · etaHEN DPI v2 (:12800)"),
    (METHOD_PS5_DPI_V1, "PS5 · etaHEN DPI v1 (:9090)"),
]


def method_api_port(method: str) -> int:
    return DPI_V1_PORT if method == METHOD_PS5_DPI_V1 else 12800


class _PkgHttpHandler(SimpleHTTPRequestHandler):
    """Quiet static handler with HTTP Range (206) support.

    PS4/PS5 background download managers request packages in byte ranges;
    the stdlib handler ignores ``Range`` and always returns 200 + the whole
    file, which makes console installs stall. This adds proper 206/416.
    """

    def log_message(self, *args) -> None:
        pass

    def end_headers(self) -> None:
        # advertise range support on every response
        self.send_header("Accept-Ranges", "bytes")
        super().end_headers()

    def do_GET(self) -> None:
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            return super().do_GET()
        if not os.path.isfile(path):
            self.send_error(404, "File not found")
            return
        size = os.path.getsize(path)
        ctype = self.guess_type(path)
        rng = self.headers.get("Range")
        start, end, partial = 0, size - 1, False
        if rng and rng.startswith("bytes="):
            partial = True
            first, _, last = rng[6:].partition("-")
            try:
                if first == "":                 # suffix form: bytes=-N
                    start = max(0, size - int(last))
                    end = size - 1
                else:
                    start = int(first)
                    end = int(last) if last else size - 1
                if start > end or start >= size:
                    raise ValueError
                end = min(end, size - 1)
            except ValueError:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
        length = end - start + 1
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        rel = urllib.parse.unquote(self.path.split("?", 1)[0])
        owner = getattr(self.server, "owner", None)
        with open(path, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(262144, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    break
                remaining -= len(chunk)
                if owner is not None:
                    owner.note_bytes(rel, len(chunk), size)


class FolderHttpServer(QThread):
    """Serve a directory over HTTP so the console can pull packages from it."""

    started_ok = Signal(int)            # port
    failed = Signal(str)
    # byte counts can exceed 2 GB → use 64-bit (qlonglong), not Qt int (32-bit)
    progress = Signal(str, "qlonglong", "qlonglong")  # rel_path, sent, total
    completed = Signal(str)             # rel_path

    def __init__(self, directory: str, port: int, parent=None) -> None:
        super().__init__(parent)
        self.directory = directory
        self.port = int(port)
        self._httpd: ThreadingHTTPServer | None = None
        self._lock = threading.Lock()
        self._served: dict[str, int] = {}
        self._last_emit: dict[str, int] = {}
        self._done: set[str] = set()

    def reset_counters(self) -> None:
        with self._lock:
            self._served.clear()
            self._last_emit.clear()
            self._done.clear()

    def note_bytes(self, rel: str, n: int, total: int) -> None:
        """Called from request threads as bytes stream to the console."""
        with self._lock:
            served = self._served.get(rel, 0) + n
            self._served[rel] = served
            emit_progress = served - self._last_emit.get(rel, 0) >= 1_000_000
            if emit_progress:
                self._last_emit[rel] = served
            finished = total and served >= total and rel not in self._done
            if finished:
                self._done.add(rel)
        if emit_progress:
            self.progress.emit(rel, min(served, total), total)
        if finished:
            self.progress.emit(rel, total, total)
            self.completed.emit(rel)

    def run(self) -> None:
        if not os.path.isdir(self.directory):
            self.failed.emit(f"Folder does not exist: {self.directory}")
            return
        handler = functools.partial(_PkgHttpHandler, directory=self.directory)
        try:
            self._httpd = ThreadingHTTPServer(("0.0.0.0", self.port), handler)
        except OSError as e:
            self.failed.emit(f"Cannot bind port {self.port}: {e}")
            return
        self._httpd.owner = self          # handlers report bytes back to us
        self.started_ok.emit(self.port)
        self._httpd.serve_forever()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None


class ExploitHost(FolderHttpServer):
    """Serve the bundled exploit-host site (defaults to port 80)."""

    def __init__(self, directory: str, port: int = 80, parent=None) -> None:
        super().__init__(directory, port, parent)


class TestConnectivity(QThread):
    """Check that the PS4 is reachable and that our HTTP server answers."""

    result = Signal(dict)           # {'ps4': bool, 'http': bool}

    def __init__(self, server_ip: str, server_port: int, ps4_ip: str,
                 ps4_port: int = PS4_API_PORT, parent=None) -> None:
        super().__init__(parent)
        self.server_ip = server_ip
        self.server_port = int(server_port)
        self.ps4_ip = ps4_ip
        self.ps4_port = int(ps4_port)

    def run(self) -> None:
        status = {"ps4": False, "http": False}
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(4)
                status["ps4"] = s.connect_ex((self.ps4_ip, self.ps4_port)) == 0
        except OSError:
            status["ps4"] = False
        try:
            urllib.request.urlopen(
                f"http://{self.server_ip}:{self.server_port}", timeout=4)
            status["http"] = True
        except (urllib.error.URLError, OSError):
            status["http"] = False
        self.result.emit(status)


class RemoteInstaller(QThread):
    """Send packages to the Remote PKG Installer and track progress."""

    log = Signal(str)
    progress = Signal(int, str, int)   # row index, time-remaining text, percent
    finished_all = Signal()

    def __init__(self, server_ip: str, paths: list[str], ps4_ip: str,
                 server_port: int, served_root: str,
                 method: str = METHOD_PS4_RPI, parent=None) -> None:
        super().__init__(parent)
        self.server_ip = server_ip
        self.paths = paths
        self.ps4_ip = ps4_ip            # the console IP (PS4 or PS5)
        self.server_port = int(server_port)
        self.served_root = served_root
        self.method = method

    def _url_for(self, pkg_path: str) -> str:
        """URL the console will download from — path segments are
        percent-encoded so filenames with spaces / () / ™ work."""
        rel = os.path.relpath(pkg_path, self.served_root).replace(os.sep, "/")
        enc = "/".join(urllib.parse.quote(seg) for seg in rel.split("/"))
        return f"http://{self.server_ip}:{self.server_port}/{enc}"

    # ------------------------------------------------------------------ run
    def run(self) -> None:
        label = dict(INSTALL_METHODS).get(self.method, self.method)
        self.log.emit(f"Starting remote install via {label}…")
        for index, pkg_path in enumerate(self.paths):
            name = os.path.basename(pkg_path)
            url = self._url_for(pkg_path)
            try:
                if self.method == METHOD_PS5_DPI_V2:
                    self._install_dpi_v2(index, url, name)
                elif self.method == METHOD_PS5_DPI_V1:
                    self._install_dpi_v1(index, url, name)
                else:
                    self._install_ps4_rpi(index, url, name)
            except (urllib.error.URLError, OSError, ValueError) as e:
                self.log.emit(f"✗ {name}: {e}")
                self.progress.emit(index, "Failed", 0)
        self.log.emit("All packages processed.")
        self.finished_all.emit()

    # ---- PS4 Remote PKG Installer (JSON API on :12800, with progress) ----
    # Protocol & response schema per flatz' ps4_remote_pkg_installer:
    # https://github.com/flatz/ps4_remote_pkg_installer
    @staticmethod
    def _parse_rpi(raw: str) -> dict:
        """Parse a Remote PKG Installer reply.

        The installer emits responses whose numeric fields are hex integer
        *literals* (e.g. ``"transferred": 0x1A2B``) — valid Python but invalid
        JSON, so ``json.loads`` can't read them and we use ``ast.literal_eval``
        instead. Returns ``{}`` when the body can't be parsed.
        """
        try:
            out = ast.literal_eval(raw.replace("\n", "").strip())
        except (ValueError, SyntaxError):
            return {}
        return out if isinstance(out, dict) else {}

    def _post(self, endpoint: str, payload: dict) -> dict:
        url = f"http://{self.ps4_ip}:{PS4_API_PORT}/api/{endpoint}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data, headers={"Content-Type": "application/json"})
        try:
            resp = urllib.request.urlopen(req, timeout=15)
            return self._parse_rpi(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            # The installer returns its {"status":"fail","error":…} body even
            # with a non-2xx code — read it so we can show the real reason.
            return self._parse_rpi(e.read().decode("utf-8", "ignore"))

    def _hint(self, reason: str) -> None:
        """Surface the most common PS4-side causes when an install is rejected."""
        low = (reason or "").lower()
        if "space" in low or "free" in low or "0x80990015" in low:
            self.log.emit("   ↳ The PS4 likely doesn't have enough free space "
                          "for this package.")
        elif ("content type" in low or "prerequisites" in low
              or "title" in low or "format" in low or "sfo" in low):
            self.log.emit("   ↳ The file may be corrupt or not a valid PS4 "
                          "package for this firmware.")
        else:
            self.log.emit("   ↳ Check: PS4 free space, that the package matches "
                          "your console's firmware, and that the HTTP server "
                          "stays running for the whole download.")

    def _install_ps4_rpi(self, index: int, url: str, name: str) -> None:
        try:
            resp = self._post("install", {"type": "direct", "packages": [url]})
        except (urllib.error.URLError, OSError) as e:
            self.log.emit(f"✗ {name}: cannot reach PS4 ({e})")
            self.progress.emit(index, "Failed", 0)
            return
        # The PS4 reports *why* it refused a package — surface it instead of a
        # bare "Failed". A success reply has status=success + a task_id.
        if resp.get("status") != "success" or "task_id" not in resp:
            reason = resp.get("error") or "PS4 rejected the package (no task id)"
            self.log.emit(f"✗ {name}: {reason}")
            self._hint(reason)
            self.progress.emit(index, "Failed", 0)
            return
        try:
            task_id = int(resp["task_id"])
        except (TypeError, ValueError):
            self.log.emit(f"✗ {name}: invalid task id {resp.get('task_id')!r}")
            self.progress.emit(index, "Failed", 0)
            return
        self.log.emit(f"Installing {resp.get('title') or name}")
        while True:
            try:
                st = self._post("get_task_progress", {"task_id": task_id})
            except (urllib.error.URLError, OSError) as e:
                self.log.emit(f"… progress error: {e}")
                self.progress.emit(index, "Failed", 0)
                break
            if not st:
                self.log.emit(f"✗ {name}: no progress response from PS4")
                self.progress.emit(index, "Failed", 0)
                break
            # A non-zero error means the install died mid-download (e.g. the
            # console ran out of space or the connection dropped).
            err = int(st.get("error", 0) or 0)
            if err:
                code = err & 0xFFFFFFFF
                self.log.emit(f"✗ {name}: PS4 install error 0x{code:08X}")
                self._hint(f"0x{code:08X}")
                self.progress.emit(index, "Failed", 0)
                break
            transferred = int(st.get("transferred", 0))
            total = int(st.get("length_total", 0)) or 1
            rest = int(st.get("rest_sec", 0))
            pct = int(transferred / total * 100) if transferred else 0
            eta = str(datetime.timedelta(seconds=rest))
            self.progress.emit(index, eta if transferred else "Installing…", pct)
            if rest == 0 and transferred:
                self.log.emit(f"✓ {name} ready ({convert_bytes(total)})")
                self.progress.emit(index, "Done", 100)
                break
            time.sleep(1)

    # ---- etaHEN DPI v2 (HTTP POST /upload, form url=…) ----
    def _install_dpi_v2(self, index: int, url: str, name: str) -> None:
        endpoint = f"http://{self.ps4_ip}:{DPI_V2_PORT}/upload"
        # etaHEN can also receive content_id/content_name to label the install
        fields = {"url": url}
        body = urllib.parse.urlencode(fields).encode("utf-8")
        req = urllib.request.Request(
            endpoint, body,
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.progress.emit(index, "Requesting…", 0)
        try:
            resp = urllib.request.urlopen(req, timeout=30)
            text = resp.read().decode("utf-8", "ignore").strip()
        except urllib.error.HTTPError as e:
            text = f"HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:200]}"
        # etaHEN ALWAYS returns HTTP 200; the real result is in the body:
        #   "SUCCESS: …Task started"  or  "FAILED: …error …, code 0x…"
        if text.upper().startswith("SUCCESS"):
            self.log.emit(f"✓ {name}: {text}")
            # leave the bar at 0 — the HTTP server drives it as the PS5 downloads
            self.progress.emit(index, "Downloading to PS5…", 0)
        else:
            self.log.emit(f"✗ {name}: {text or 'no response from DPI v2'}")
            self.progress.emit(index, "Failed", 0)

    # ---- etaHEN DPI v1 (JSON over raw TCP :9090, reply {"res":"0"}) ----
    def _install_dpi_v1(self, index: int, url: str, name: str) -> None:
        payload = json.dumps({"url": url}).encode("utf-8")
        self.progress.emit(index, "Sending…", 0)
        with socket.create_connection((self.ps4_ip, DPI_V1_PORT), timeout=15) as s:
            s.sendall(payload)
            try:
                reply = s.recv(256).decode("utf-8", "ignore")
            except OSError:
                reply = ""
        res = None
        try:
            res = str(json.loads(reply).get("res"))
        except (ValueError, AttributeError):
            pass
        if res == "0":
            self.log.emit(f"✓ {name}: accepted on PS5 (DPI v1)")
            self.progress.emit(index, "Downloading to PS5…", 0)
        else:
            self.log.emit(f"✗ {name}: DPI v1 res={res} ({reply.strip()})")
            self.progress.emit(index, "Failed", 0)
