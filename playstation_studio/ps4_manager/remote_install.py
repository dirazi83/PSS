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
    (METHOD_PS4_RPI, "PS4 · Remote PKG Installer (:12800)"),
    (METHOD_PS5_DPI_V2, "PS5 · etaHEN DPI v2 (:12800)"),
    (METHOD_PS5_DPI_V1, "PS5 · etaHEN DPI v1 (:9090)"),
]


def method_api_port(method: str) -> int:
    return DPI_V1_PORT if method == METHOD_PS5_DPI_V1 else 12800


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:  # silence request logging
        pass


class FolderHttpServer(QThread):
    """Serve a directory over HTTP so the PS4 can pull packages from it."""

    started_ok = Signal(int)        # port
    failed = Signal(str)

    def __init__(self, directory: str, port: int, parent=None) -> None:
        super().__init__(parent)
        self.directory = directory
        self.port = int(port)
        self._httpd: ThreadingHTTPServer | None = None

    def run(self) -> None:
        if not os.path.isdir(self.directory):
            self.failed.emit(f"Folder does not exist: {self.directory}")
            return
        handler = functools.partial(_QuietHandler, directory=self.directory)
        try:
            self._httpd = ThreadingHTTPServer(("0.0.0.0", self.port), handler)
        except OSError as e:
            self.failed.emit(f"Cannot bind port {self.port}: {e}")
            return
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
    """Send packages to the PS4 Remote PKG Installer and track progress."""

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
    def _post(self, endpoint: str, payload: dict) -> dict:
        url = f"http://{self.ps4_ip}:{PS4_API_PORT}/api/{endpoint}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data, headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=15)
        return ast.literal_eval(resp.read().decode("utf-8").replace("\n", ""))

    def _install_ps4_rpi(self, index: int, url: str, name: str) -> None:
        try:
            resp = self._post("install", {"type": "direct", "packages": [url]})
            task_id = int(resp["task_id"])
        except (urllib.error.URLError, OSError, KeyError, ValueError) as e:
            self.log.emit(f"✗ {name}: {e}")
            self.progress.emit(index, "Failed", 0)
            return
        self.log.emit(f"Installing {name}")
        while True:
            try:
                st = self._post("get_task_progress", {"task_id": task_id})
            except (urllib.error.URLError, OSError, ValueError) as e:
                self.log.emit(f"… progress error: {e}")
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
        body = urllib.parse.urlencode({"url": url}).encode("utf-8")
        req = urllib.request.Request(
            endpoint, body,
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.progress.emit(index, "Sending…", 0)
        try:
            resp = urllib.request.urlopen(req, timeout=20)
            code = resp.getcode()
        except urllib.error.HTTPError as e:
            code = e.code
        if 200 <= code < 400:
            self.log.emit(f"✓ {name}: queued on PS5 (DPI v2) — "
                          "watch the console screen for progress")
            self.progress.emit(index, "Installing on PS5", 100)
        else:
            self.log.emit(f"✗ {name}: DPI v2 returned HTTP {code}")
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
            self.progress.emit(index, "Installing on PS5", 100)
        else:
            self.log.emit(f"✗ {name}: DPI v1 res={res} ({reply.strip()})")
            self.progress.emit(index, "Failed", 0)
