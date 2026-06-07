"""Send a payload file to a console over a raw TCP socket.

Many PS4/PS5 ELF loaders (elfldr / etaHEN / similar) simply listen on a
TCP port and execute whatever bytes you stream to them. This mirrors that:
open a connection to ``ip:port`` and send the file.
"""

from __future__ import annotations

import errno
import os
import socket

from PySide6.QtCore import QThread, Signal

from ..shared.config import config

# Common loader ports, shown as quick presets in the UI.
PORT_PRESETS = [
    ("PS5 · ELF loader (9021)", 9021),
    ("PS4 · ELF loader (9020)", 9020),
    ("PS5 · etaHEN cmd (9090)", 9090),
    ("JAR loader (9025)", 9025),
]

# Built-in PS4/PS5 payload file types. The user can extend this with custom
# extensions in the Payload Sender (saved to config).
DEFAULT_EXTS = (".elf", ".bin", ".jar", ".self", ".prx", ".sprx")
SUPPORTED_EXTS = DEFAULT_EXTS  # kept for backward-compatibility

_CHUNK = 64 * 1024


def custom_exts() -> tuple[str, ...]:
    """Extra payload extensions the user added, normalised to ``.ext`` form."""
    raw = config.get("payloads", "custom_exts", "") or ""
    out: list[str] = []
    for tok in raw.replace(",", " ").split():
        tok = tok.strip().lower()
        if not tok:
            continue
        if not tok.startswith("."):
            tok = "." + tok
        if tok not in out:
            out.append(tok)
    return tuple(out)


def effective_exts() -> tuple[str, ...]:
    """All payload extensions currently recognised (built-in + custom)."""
    return tuple(dict.fromkeys(DEFAULT_EXTS + custom_exts()))


def is_payload(path: str) -> bool:
    """True when *path* is a file with a recognised payload extension."""
    return (os.path.isfile(path)
            and os.path.splitext(path)[1].lower() in effective_exts())


def scan_payloads(folder: str, max_depth: int = 6) -> list[str]:
    """Recursively find payload files under *folder*, down to *max_depth*.

    Returns a sorted list of absolute file paths.
    """
    root = os.path.abspath(folder)
    exts = effective_exts()
    found: list[str] = []
    base_depth = root.rstrip(os.sep).count(os.sep)
    for dirpath, dirnames, filenames in os.walk(root):
        depth = dirpath.rstrip(os.sep).count(os.sep) - base_depth
        if depth >= max_depth:
            dirnames[:] = []          # stop descending past the limit
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() in exts:
                found.append(os.path.join(dirpath, fn))
    return sorted(found)


def _explain(exc: OSError, ip: str, port: int) -> str:
    """Turn a socket error into an actionable, human message."""
    eno = getattr(exc, "errno", None)
    if isinstance(exc, socket.gaierror):
        return (f"Can't resolve “{ip}”. Enter the console's numeric IP "
                "(e.g. 192.168.1.30), not a name.")
    if isinstance(exc, (socket.timeout, TimeoutError)) or eno == errno.ETIMEDOUT:
        return (f"Timed out reaching {ip}:{port}. Check the console IP, that "
                "it's powered on and awake, and on the same Wi-Fi/LAN.")
    if isinstance(exc, ConnectionRefusedError) or eno == errno.ECONNREFUSED:
        return (f"Connection refused on {ip}:{port}. Nothing is listening "
                "there — start the ELF/payload loader on the console first, "
                "and check the port (PS5 ELF loader is usually 9021, PS4 9020).")
    if isinstance(exc, ConnectionResetError) or eno == errno.ECONNRESET:
        return (f"{ip}:{port} reset the connection — the loader closed early. "
                "It may already be busy, or it rejected the payload. Reboot the "
                "loader and try again.")
    if eno in (errno.EHOSTUNREACH, errno.ENETUNREACH):
        return (f"{ip} is unreachable. Check the IP and that this computer is "
                "on the same network as the console.")
    return f"Send failed → {ip}:{port}: {exc}"


class PayloadSender(QThread):
    """Stream one file to ``ip:port`` and report progress / result."""

    progress = Signal(int, int)     # bytes_sent, total_bytes
    done = Signal(bool, str)        # success, message

    def __init__(self, path: str, ip: str, port: int, parent=None) -> None:
        super().__init__(parent)
        self.path = path
        self.ip = ip
        self.port = int(port)

    def run(self) -> None:
        name = os.path.basename(self.path)
        try:
            total = os.path.getsize(self.path)
        except OSError as exc:
            self.done.emit(False, f"Cannot read {name}: {exc}")
            return
        try:
            with open(self.path, "rb") as fh, \
                    socket.create_connection((self.ip, self.port), timeout=10) as sock:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                sent = 0
                while True:
                    chunk = fh.read(_CHUNK)
                    if not chunk:
                        break
                    sock.sendall(chunk)
                    sent += len(chunk)
                    self.progress.emit(sent, total)
                # signal end-of-data and give loaders that reply a moment to ack
                ack = ""
                try:
                    sock.shutdown(socket.SHUT_WR)
                    sock.settimeout(2.0)
                    reply = sock.recv(256)
                    if reply:
                        ack = "  · " + reply.decode("utf-8", "replace").strip()[:80]
                except OSError:
                    pass
        except (OSError, socket.timeout) as exc:
            self.done.emit(False, _explain(exc, self.ip, self.port))
            return
        if sent < total:
            self.done.emit(False, f"Only sent {sent:,}/{total:,} bytes to "
                                  f"{self.ip}:{self.port} before the link dropped.")
            return
        self.done.emit(
            True, f"Sent {name} → {self.ip}:{self.port}  ({sent:,} bytes){ack}")
