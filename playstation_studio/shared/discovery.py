"""Find PS4 / PS5 consoles on the local network.

Primary method: Sony's Device Discovery Protocol (DDP) — a UDP ``SRCH``
datagram broadcast to port 987 (PS4) / 9302 (PS5). Awake (or network-on)
consoles reply with their host type, name and IP.

Fallback: a quick TCP sweep of the /24 subnet for common homebrew loader
ports, for jailbroken consoles that have system discovery turned off.
"""

from __future__ import annotations

import concurrent.futures
import socket
import time

from PySide6.QtCore import QThread, Signal

DDP_PORTS = (987, 9302)                 # PS4, PS5
# TCP ports that strongly suggest a jailbroken console, mapped to a guess.
TCP_HINTS = {12800: "PS4", 9020: "PS4", 9021: "PS5", 9090: "PS5"}

_DDP_VERSION = {987: "00020020", 9302: "00030010"}


def local_ipv4() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def subnet_broadcast(ip: str) -> str:
    parts = ip.split(".")
    if len(parts) == 4:
        return ".".join(parts[:3] + ["255"])
    return "255.255.255.255"


def _srch(port: int) -> bytes:
    ver = _DDP_VERSION.get(port, "00020020")
    return (f"SRCH * HTTP/1.1\n"
            f"device-discovery-protocol-version:{ver}\n").encode("utf-8")


def _parse_ddp(data: bytes, ip: str) -> dict | None:
    text = data.decode("utf-8", "ignore")
    if "host-type" not in text.lower() and not text.startswith("HTTP"):
        return None
    info = {"ip": ip, "type": "Console", "name": "", "source": "DDP"}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key, value = key.strip().lower(), value.strip()
        if key == "host-type":
            info["type"] = value.upper()
        elif key == "host-name":
            info["name"] = value
        elif key == "running-app-name" and value:
            info["app"] = value
    return info


class ConsoleScanner(QThread):
    """Scan the LAN for consoles; emits one ``found`` per unique IP."""

    found = Signal(dict)            # {ip, type, name, source, [ports]}
    finished_scan = Signal(int)     # total found

    def __init__(self, ddp_ports=DDP_PORTS, tcp_ports=tuple(TCP_HINTS),
                 duration: float = 2.5, parent=None) -> None:
        super().__init__(parent)
        self.ddp_ports = tuple(ddp_ports)
        self.tcp_ports = tuple(tcp_ports)
        self.duration = duration

    def run(self) -> None:
        results: dict[str, dict] = {}
        self._ddp(results)
        self._tcp(results)
        for info in results.values():
            self.found.emit(info)
        self.finished_scan.emit(len(results))

    # ---- DDP broadcast ----
    def _ddp(self, results: dict) -> None:
        ip = local_ipv4()
        targets = {subnet_broadcast(ip), "255.255.255.255"}
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except OSError:
            pass
        try:
            sock.bind(("", 0))
        except OSError:
            pass
        sock.settimeout(0.4)
        for port in self.ddp_ports:
            msg = _srch(port)
            for target in targets:
                try:
                    sock.sendto(msg, (target, port))
                except OSError:
                    pass
        deadline = time.time() + self.duration
        while time.time() < deadline:
            try:
                data, addr = sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            info = _parse_ddp(data, addr[0])
            if info:
                results.setdefault(addr[0], {}).update(info)
        sock.close()

    # ---- TCP fallback sweep ----
    def _tcp(self, results: dict) -> None:
        if not self.tcp_ports:
            return
        ip = local_ipv4()
        if ip == "127.0.0.1":
            return
        base = ".".join(ip.split(".")[:3])
        hosts = [f"{base}.{i}" for i in range(1, 255)]

        def probe(host: str):
            hits = []
            for port in self.tcp_ports:
                try:
                    with socket.create_connection((host, port), timeout=0.25):
                        hits.append(port)
                except OSError:
                    pass
            return host, hits

        with concurrent.futures.ThreadPoolExecutor(max_workers=64) as pool:
            for host, hits in pool.map(probe, hosts):
                if not hits:
                    continue
                cur = results.setdefault(
                    host, {"ip": host, "type": "Console", "name": "",
                           "source": "port"})
                if cur.get("source") != "DDP" and cur.get("type") == "Console":
                    for port in hits:
                        guess = TCP_HINTS.get(port)
                        if guess:
                            cur["type"] = guess
                            break
                cur["ports"] = sorted(set(cur.get("ports", []) + hits))
