"""Fast, stat-only size prediction for a PS5 dump before packing.

PFS pads every file up to a whole block, so a game with thousands of tiny
files can pack *larger* than the source at the default 64 KiB block. This
module predicts the image footprint at the default block size and at the
best auto-fit block size, so the UI can warn and recommend before wasting
time on a pack that bloats. It only reads file *sizes* (no content), so it
is cheap even on big games.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

from PySide6.QtCore import QThread, Signal

# Block sizes MkPFS's auto-fit chooses among (4 KiB … 64 KiB).
AUTO_FIT_CANDIDATES = (4096, 8192, 16384, 32768, 65536)
DEFAULT_BLOCK = 65536


@dataclass
class Estimate:
    source_dir: str
    files: int = 0
    raw: int = 0
    foot_default: int = 0          # footprint at the 64 KiB default block
    foot_best: int = 0             # footprint at the best auto-fit block
    best_block: int = DEFAULT_BLOCK
    ok: bool = True

    @property
    def padding_default(self) -> int:
        return max(0, self.foot_default - self.raw)

    @property
    def padding_best(self) -> int:
        return max(0, self.foot_best - self.raw)

    @property
    def autofit_saving(self) -> int:
        """Bytes auto-fit saves over the default 64 KiB block."""
        return max(0, self.foot_default - self.foot_best)

    @property
    def recommend_autofit(self) -> bool:
        """True when auto-fit meaningfully shrinks the image (>5% smaller)."""
        return (self.foot_default > 0
                and self.autofit_saving > self.foot_default * 0.05)


def _aligned(sizes: list[int], block: int) -> int:
    """Total block-aligned footprint for *sizes* at the given block size."""
    return sum((math.ceil(s / block) * block) if s > 0 else block for s in sizes)


def estimate_footprint(source_dir: str, min_block: int = AUTO_FIT_CANDIDATES[0]) -> Estimate:
    """Predict the PFS footprint of *source_dir* (stat-only, no file reads).

    ``min_block`` floors the block sizes considered for the "best" footprint, so
    ShadowMountPlus mode (>= 32 KiB block) estimates the size it will actually
    produce rather than a smaller auto-fit block it will not use.
    """
    sizes: list[int] = []
    try:
        for root, _dirs, files in os.walk(source_dir):
            for f in files:
                try:
                    sizes.append(os.path.getsize(os.path.join(root, f)))
                except OSError:
                    pass
    except OSError:
        return Estimate(source_dir=source_dir, ok=False)
    est = Estimate(source_dir=source_dir, files=len(sizes), raw=sum(sizes))
    est.foot_default = _aligned(sizes, DEFAULT_BLOCK)
    candidates = tuple(b for b in AUTO_FIT_CANDIDATES if b >= min_block) \
        or (AUTO_FIT_CANDIDATES[-1],)
    best = min(candidates, key=lambda b: (_aligned(sizes, b), -b))
    est.best_block = best
    est.foot_best = _aligned(sizes, best)
    return est


class EstimatorThread(QThread):
    """Estimate a list of source dirs off the GUI thread."""

    one = Signal(int, object)      # index, Estimate
    finished_all = Signal()

    def __init__(self, sources: list[str], min_block: int = AUTO_FIT_CANDIDATES[0],
                 parent=None) -> None:
        super().__init__(parent)
        self.sources = sources
        self.min_block = min_block
        self._running = True

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        for i, src in enumerate(self.sources):
            if not self._running:
                break
            self.one.emit(i, estimate_footprint(src, self.min_block))
        self.finished_all.emit()


# ---- compression rating (UX parity with PS5-FFPFSC-PRO) ----
def compression_rating(saved_pct: float) -> tuple[str, str]:
    """Map a saved-percentage to a ``(label, hex_color)`` quality badge."""
    if saved_pct < 0:
        return "Larger!", "#f87171"
    if saved_pct >= 40:
        return "Excellent", "#4ade80"
    if saved_pct >= 20:
        return "Good", "#86efac"
    if saved_pct >= 5:
        return "Okay", "#fbbf24"
    return "Poor", "#f59e0b"
