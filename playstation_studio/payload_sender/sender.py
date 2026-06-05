"""Send a payload file to a console over a raw TCP socket.

Many PS4/PS5 ELF loaders (elfldr / etaHEN / similar) simply listen on a
TCP port and execute whatever bytes you stream to them. This mirrors that:
open a connection to ``ip:port`` and send the file.
"""

from __future__ import annotations

import os
import socket

from PySide6.QtCore import QThread, Signal

# Common loader ports, shown as quick presets in the UI.
PORT_PRESETS = [
    ("PS5 · ELF/BIN (9021)", 9021),
    ("PS5 · etaHEN (9090)", 9090),
    ("PS4 · ELF (9020)", 9020),
    ("JAR loader (9025)", 9025),
]

SUPPORTED_EXTS = (".elf", ".bin", ".jar")
_CHUNK = 64 * 1024


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
                sent = 0
                while True:
                    chunk = fh.read(_CHUNK)
                    if not chunk:
                        break
                    sock.sendall(chunk)
                    sent += len(chunk)
                    self.progress.emit(sent, total)
        except (OSError, socket.timeout) as exc:
            self.done.emit(False, f"Send failed → {self.ip}:{self.port}: {exc}")
            return
        self.done.emit(
            True, f"Sent {name} → {self.ip}:{self.port}  ({sent:,} bytes)")
