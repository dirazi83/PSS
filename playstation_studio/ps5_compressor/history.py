"""Compression history: a persisted log of completed packs + a viewer dialog."""

from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ..shared.config import config
from ..shared.formatting import human_size

CFG = "ps5"
KEY = "history"
MAX_ENTRIES = 200


def record(name: str, size_in: int, size_out: int, output: str,
           elapsed: float) -> None:
    """Append a completed compression to the persisted history."""
    saved_pct = (1 - size_out / size_in) * 100 if size_in and size_out else 0.0
    entry = {
        "name": name, "date": time.strftime("%Y-%m-%d %H:%M"),
        "size_in": size_in, "size_out": size_out,
        "saved_pct": round(saved_pct, 1), "output": output,
        "elapsed": round(elapsed, 1),
    }
    items = config.get(CFG, KEY, []) or []
    items.insert(0, entry)
    config.set(CFG, KEY, items[:MAX_ENTRIES])


def entries() -> list[dict]:
    return config.get(CFG, KEY, []) or []


def clear() -> None:
    config.set(CFG, KEY, [])


class HistoryDialog(QDialog):
    COLS = ["Game", "Date", "Input", "Output", "Saved", "Time"]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Compression History")
        self.setMinimumSize(720, 420)
        lay = QVBoxLayout(self)

        self.summary = QLabel()
        lay.addWidget(self.summary)

        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        lay.addWidget(self.table, stretch=1)

        row = QHBoxLayout()
        row.addStretch(1)
        btn_clear = QPushButton("Clear History")
        btn_clear.setObjectName("Danger")
        btn_clear.clicked.connect(self._clear)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        row.addWidget(btn_clear)
        row.addWidget(btn_close)
        lay.addLayout(row)

        self._reload()

    def _reload(self) -> None:
        items = entries()
        self.table.setRowCount(0)
        total_in = total_out = 0
        for e in items:
            r = self.table.rowCount()
            self.table.insertRow(r)
            total_in += e.get("size_in", 0)
            total_out += e.get("size_out", 0)
            self.table.setItem(r, 0, QTableWidgetItem(e.get("name", "")))
            self.table.setItem(r, 1, QTableWidgetItem(e.get("date", "")))
            self.table.setItem(r, 2, QTableWidgetItem(human_size(e.get("size_in", 0))))
            self.table.setItem(r, 3, QTableWidgetItem(human_size(e.get("size_out", 0))))
            self.table.setItem(r, 4, QTableWidgetItem(f"{e.get('saved_pct', 0):.0f}%"))
            self.table.setItem(r, 5, QTableWidgetItem(f"{e.get('elapsed', 0):.0f}s"))
        if items:
            saved = max(0, total_in - total_out)
            self.summary.setText(
                f"{len(items)} compression(s)  ·  total {human_size(total_in)} → "
                f"{human_size(total_out)}  ·  saved {human_size(saved)}")
        else:
            self.summary.setText("No compressions yet.")

    def _clear(self) -> None:
        clear()
        self._reload()
