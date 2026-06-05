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
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from PySide6.QtCore import QThread, Signal

from .pkg_parser import convert_bytes

PS4_API_PORT = 12800


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
                 server_port: int, served_root: str, parent=None) -> None:
        super().__init__(parent)
        self.server_ip = server_ip
        self.paths = paths
        self.ps4_ip = ps4_ip
        self.server_port = int(server_port)
        self.served_root = served_root

    def _url_for(self, pkg_path: str) -> str:
        rel = os.path.relpath(pkg_path, self.served_root)
        rel_posix = rel.replace(os.sep, "/")
        return f"http://{self.server_ip}:{self.server_port}/{rel_posix}"

    def _post(self, endpoint: str, payload: dict) -> dict:
        url = f"http://{self.ps4_ip}:{PS4_API_PORT}/api/{endpoint}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data, headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=15)
        return ast.literal_eval(resp.read().decode("utf-8").replace("\n", ""))

    def run(self) -> None:
        self.log.emit("Starting remote install…")
        for index, pkg_path in enumerate(self.paths):
            name = os.path.basename(pkg_path)
            url = self._url_for(pkg_path)
            try:
                resp = self._post("install", {"type": "direct", "packages": [url]})
                task_id = int(resp["task_id"])
            except (urllib.error.URLError, OSError, KeyError, ValueError) as e:
                self.log.emit(f"✗ {name}: {e}")
                self.progress.emit(index, "Failed", 0)
                continue

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
                    self.log.emit(f"✓ {name} ready "
                                  f"({convert_bytes(total)})")
                    self.progress.emit(index, "Done", 100)
                    break
                time.sleep(1)
        self.log.emit("All packages processed.")
        self.finished_all.emit()
