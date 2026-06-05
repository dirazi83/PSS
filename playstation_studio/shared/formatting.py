"""Small formatting helpers."""

from __future__ import annotations


def human_size(num: int | float) -> str:
    """Render a byte count as a compact human-readable string."""
    n = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(n) < 1024.0:
            if unit == "B":
                return f"{int(n)} {unit}"
            return f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} EB"
