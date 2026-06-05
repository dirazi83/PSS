"""Tiny JSON-backed settings store.

Persists IP addresses, ports and folder paths between runs so the app
remembers what you typed last time. Stored at
``~/.playstation_studio/config.json``.

Usage:
    from ..shared.config import config
    config.get("ps4", "ps4_ip", "")
    config.set("ps4", "ps4_ip", "192.168.1.20")
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

CONFIG_DIR = Path.home() / ".playstation_studio"
CONFIG_PATH = CONFIG_DIR / "config.json"


class _Config:
    def __init__(self) -> None:
        self._data: dict = {}
        self._lock = threading.Lock()
        self.load()

    def load(self) -> None:
        try:
            with open(CONFIG_PATH, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                self._data = data
        except (OSError, json.JSONDecodeError):
            self._data = {}

    def save(self) -> None:
        with self._lock:
            try:
                CONFIG_DIR.mkdir(parents=True, exist_ok=True)
                tmp = CONFIG_PATH.with_suffix(".tmp")
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(self._data, fh, indent=2)
                os.replace(tmp, CONFIG_PATH)
            except OSError as exc:
                print("config save failed:", exc)

    def section(self, name: str) -> dict:
        block = self._data.get(name)
        if not isinstance(block, dict):
            block = {}
            self._data[name] = block
        return block

    def get(self, section: str, key: str, default=None):
        return self.section(section).get(key, default)

    def set(self, section: str, key: str, value) -> None:
        self.section(section)[key] = value
        self.save()

    def update(self, section: str, **kwargs) -> None:
        self.section(section).update(kwargs)
        self.save()


# module-level singleton
config = _Config()
