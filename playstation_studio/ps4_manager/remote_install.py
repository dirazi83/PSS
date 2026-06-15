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
import re
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


# Packages are exposed under /p/<hex>.pkg — an ASCII-safe, reversible alias so
# the console never receives a URL with spaces or special characters.
_PKG_ALIAS_RE = re.compile(r"^/p/([0-9a-fA-F]+)\.pkg$")


def pkg_alias_url(server_ip: str, server_port: int, rel_path: str) -> str:
    """Build the safe ``http://ip:port/p/<hex>.pkg`` URL for a relative path."""
    token = rel_path.replace(os.sep, "/").encode("utf-8").hex()
    return f"http://{server_ip}:{server_port}/p/{token}.pkg"


class _PkgHttpHandler(SimpleHTTPRequestHandler):
    """Quiet static handler with HTTP/1.1 keep-alive + Range (206) support.

    The PS4 Remote PKG Installer (flatz) reads a package over a single
    ``SCE_HTTP_VERSION_1_1`` keep-alive connection: first the header at
    offset 0 with *no* ``Range`` (it reads only the header bytes and abandons
    the rest of the body), then ranged reads of the entry table, ``param.sfo``
    and ``icon0.png``. A plain HTTP/1.0 server — the stdlib default — desyncs
    that client when it abandons the big header response, so the follow-up
    ranged read fails and the console reports the unhelpful
    *"Unable to set up prerequisites"* with no reason.

    This handler therefore:
      * speaks **HTTP/1.1** (the version the console negotiates),
      * keep-alives the small ranged reads (206), but
      * sends ``Connection: close`` after a full-file (200) stream the client
        may abandon, so the connection can never desync,
      * always sends an exact ``Content-Length`` so framing is unambiguous.
    """

    # The console's sceHttp client is HTTP/1.1; match it so keep-alive and
    # range framing behave the way flatz's installer expects.
    protocol_version = "HTTP/1.1"

    def log_message(self, *args) -> None:
        pass

    def end_headers(self) -> None:
        # advertise range support on every response
        self.send_header("Accept-Ranges", "bytes")
        super().end_headers()

    def _resolve(self):
        """Map the request path to a real file + its human relative path.

        Packages are served under an ASCII-safe alias ``/p/<hex>.pkg`` where
        ``<hex>`` is the hex-encoded relative path. flatz's installer *unescapes*
        the URL before handing it to ``sceHttp``, so a normal percent-encoded
        path containing spaces / ``()`` / ``{}`` / ``™`` becomes an invalid URL
        and the console can't even open the connection — surfacing as
        *"Unable to set up prerequisites."* The hex alias contains only
        ``[0-9a-f/]`` so it survives unescaping intact and always parses.

        Returns ``(real_path, rel)`` where ``rel`` is the leading-slash human
        path used for progress reporting, or ``(None, raw)`` on a bad/unsafe
        alias. Non-alias requests fall back to the normal directory mapping
        (used by the bundled exploit host).
        """
        raw = urllib.parse.unquote(self.path.split("?", 1)[0])
        m = _PKG_ALIAS_RE.match(raw)
        if not m:
            return self.translate_path(self.path), raw
        try:
            rel = bytes.fromhex(m.group(1)).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None, raw
        base = os.path.realpath(self.directory)
        real = os.path.realpath(os.path.join(base, rel.replace("/", os.sep)))
        # never let a crafted alias escape the served directory
        if real != base and not real.startswith(base + os.sep):
            return None, raw
        return real, "/" + rel

    def do_HEAD(self) -> None:
        path, _ = self._resolve()
        if not path or not os.path.isfile(path):
            self.send_error(404, "File not found")
            return
        self.send_response(200)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Length", str(os.path.getsize(path)))
        self.end_headers()

    def do_GET(self) -> None:
        path, rel = self._resolve()
        if path is None:
            self.send_error(404, "File not found")
            return
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
                self.send_header("Content-Length", "0")
                self.close_connection = True
                self.end_headers()
                return
        length = end - start + 1
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            # A non-ranged GET streams the whole file, but the console reads
            # only the header and abandons the rest. Close afterwards so the
            # next request starts fresh instead of desyncing keep-alive.
            self.close_connection = True
            self.send_header("Connection", "close")
        self.end_headers()
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
                    # client hung up early (expected when it abandons the
                    # header read) — drop this connection, never reuse it
                    self.close_connection = True
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

    # Pause between packages so the console can finish committing the previous
    # install before we queue the next one. Firing installs back-to-back is what
    # makes the PS4's Remote PKG Installer crash; one-at-a-time avoids it.
    _SETTLE_SECONDS = 4

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
        self._cancel = False

    def cancel(self) -> None:
        """Ask the install loop to stop after the current step."""
        self._cancel = True

    def _url_for(self, pkg_path: str) -> str:
        """URL the console downloads from.

        Uses the ASCII-safe ``/p/<hex>.pkg`` alias rather than the percent-
        encoded real path. flatz's installer unescapes the URL before handing
        it to the console's HTTP client, so spaces / ``()`` / ``{}`` / ``™`` in
        the filename would make an invalid URL the PS4 can't open (it fails
        before connecting, as *"Unable to set up prerequisites"*). The hex alias
        survives unescaping and the server decodes it back to the real file.
        """
        rel = os.path.relpath(pkg_path, self.served_root)
        return pkg_alias_url(self.server_ip, self.server_port, rel)

    # ------------------------------------------------------------------ run
    def run(self) -> None:
        label = dict(INSTALL_METHODS).get(self.method, self.method)
        total = len(self.paths)
        self.log.emit(f"Starting remote install via {label} — {total} package(s), "
                      "one at a time…")
        for index, pkg_path in enumerate(self.paths):
            if self._cancel:
                self.log.emit("Install cancelled.")
                break
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
            # let the console settle before queuing the next package
            if index + 1 < total:
                time.sleep(self._SETTLE_SECONDS)
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

    # Known Remote PKG Installer / bgft rejection codes, mapped from observed
    # console behaviour with flatz' installer.
    _RPI_ERRORS = {
        0x80990015: "It's already installed on the PS4 — delete the existing "
                    "copy to reinstall the base game, or just install the "
                    "update / DLC on top.",
        0x80990004: "Its base game/app isn't installed yet — install the base "
                    "package first (this looks like an update or DLC).",
    }

    def _explain_code(self, code) -> str:
        """Friendly explanation for a console error code, or '' if unknown."""
        if isinstance(code, int):
            return self._RPI_ERRORS.get(code & 0xFFFFFFFF, "")
        return ""

    def _emit_hint(self, code) -> None:
        """Log the known explanation for ``code`` or a generic checklist."""
        explain = self._explain_code(code)
        if explain:
            self.log.emit(f"   ↳ {explain}")
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
            code = resp.get("error_code")
            ucode = (code & 0xFFFFFFFF) if isinstance(code, int) else None
            if ucode == 0x80990015:
                # "already installed" is an expected state, not a failure —
                # show the row as done rather than a red ✗ / Failed.
                self.log.emit(f"✓ {name}: already installed on the PS4")
                self.progress.emit(index, "Already installed", 100)
                return
            if isinstance(code, int):
                head = f"PS4 refused it [0x{code & 0xFFFFFFFF:08X}]"
            else:
                head = resp.get("error") or "PS4 rejected the package (no task id)"
            self.log.emit(f"✗ {name}: {head}")
            self._emit_hint(code)
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
            if self._cancel:
                self.log.emit(f"… {name}: install cancelled (continues on the PS4)")
                break
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
                self._emit_hint(code)
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
