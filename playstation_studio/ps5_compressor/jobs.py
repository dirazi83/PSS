"""Job model + packing settings used by the runner and UI."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


def mkpfs_command() -> list[str]:
    """Base command to invoke the bundled mkpfs engine.

    In a normal Python install this is ``python -m mkpfs``. In a frozen
    (PyInstaller) build there is no system Python, so the app re-invokes its
    own executable with ``--run-mkpfs`` (handled in the entry point).
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, "--run-mkpfs"]
    return [sys.executable, "-m", "mkpfs"]


# Files that mark a directory as a real PS5 game dump.
GAME_MARKERS = ("eboot.bin", "sce_sys")
PFS_EXTENSIONS = (".ffpfs", ".ffpfsc", ".pfs", ".dat", ".bin")


def dir_is_game(path: Path) -> bool:
    """True when *path* directly contains a game-dump marker."""
    return any((path / m).exists() for m in GAME_MARKERS)


def find_game_dirs(root: str | Path, max_depth: int = 3) -> list[str]:
    """Recursively locate game-dump folders under *root*.

    Descends up to *max_depth* levels. A directory that itself looks like a
    game is collected and **not** descended into (so we never dive into a
    game's own ``sce_sys``). Returns a sorted list of unique absolute paths.
    """
    root = Path(root)
    found: list[str] = []
    seen: set[str] = set()

    def _walk(dir_path: Path, depth: int) -> None:
        if dir_is_game(dir_path):
            resolved = str(dir_path.resolve())
            if resolved not in seen:
                seen.add(resolved)
                found.append(resolved)
            return  # don't descend into a game's internals
        if depth <= 0:
            return
        try:
            children = sorted(p for p in dir_path.iterdir() if p.is_dir())
        except OSError:
            return
        for child in children:
            _walk(child, depth - 1)

    _walk(root, max_depth)
    return found


class Status(str, Enum):
    QUEUED = "Queued"
    RUNNING = "Running"
    DONE = "Done"
    FAILED = "Failed"
    SKIPPED = "Skipped"
    STOPPED = "Stopped"


@dataclass
class PackSettings:
    """Global packing options shared by every job, mapped to mkpfs flags."""

    output_dir: str = ""
    version: str = "PS5"            # PS5 only
    compress: bool = True
    compression_level: int = 9      # 0-9
    verify: bool = False
    encrypted: bool = False
    require_game_files: bool = False
    skip_executable_compression: bool = True
    cpu_count: int = 0              # 0 = auto/all
    low_memory: bool = False        # cap to 1 worker to minimise peak RAM
    overwrite: bool = False         # re-pack even if output exists


@dataclass
class Job:
    """A single game dump to compress."""

    source_dir: str
    name: str = ""
    output_path: str = ""
    status: Status = Status.QUEUED
    progress: int = 0               # 0-100
    phase: str = ""
    message: str = ""
    size_in: int = 0
    size_out: int = 0
    elapsed: float = 0.0

    def __post_init__(self) -> None:
        if not self.name:
            self.name = Path(self.source_dir).name

    # ---- helpers ----
    @property
    def ratio(self) -> float | None:
        if self.size_in and self.size_out:
            return self.size_out / self.size_in
        return None

    def compute_input_size(self) -> int:
        total = 0
        for root, _dirs, files in os.walk(self.source_dir):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
        self.size_in = total
        return total

    def looks_like_game(self) -> bool:
        return dir_is_game(Path(self.source_dir))

    def default_output(self, settings: PackSettings) -> str:
        """Compute the intended output path from the global settings."""
        out_dir = settings.output_dir or str(Path(self.source_dir).parent)
        ext = ".ffpfsc" if settings.compress else ".ffpfs"
        return str(Path(out_dir) / f"{self.name}{ext}")

    def resolve_actual_output(self) -> str:
        """mkpfs may auto-adjust the extension. Find the file it actually wrote
        by matching the output stem against known PFS extensions."""
        intended = Path(self.output_path)
        if intended.exists():
            return str(intended)
        parent, stem = intended.parent, intended.stem
        candidates = [
            c for c in parent.glob(f"{stem}.*")
            if c.suffix.lower() in PFS_EXTENSIONS
        ]
        if candidates:
            return str(max(candidates, key=lambda c: c.stat().st_mtime))
        return self.output_path

    def build_command(self, settings: PackSettings) -> list[str]:
        """Assemble the `mkpfs pack folder ...` command line."""
        cmd = mkpfs_command() + ["pack", "folder",
               self.source_dir, self.output_path,
               "--version", settings.version]

        cmd += ["--compress"] if settings.compress else ["--no-compress"]
        if settings.compress:
            cmd += ["--compression-level", str(settings.compression_level)]
        if settings.skip_executable_compression:
            cmd += ["--skip-executable-compression"]
        # Low-memory mode forces a single worker (one file at a time) to keep
        # peak RAM low; otherwise honour the requested cpu count (0 = auto).
        effective_cpu = 1 if settings.low_memory else settings.cpu_count
        if effective_cpu > 0:
            cmd += ["--cpu-count", str(effective_cpu)]
        if settings.verify:
            cmd += ["--verify"]
        if settings.encrypted:
            cmd += ["--encrypted"]
        if settings.require_game_files:
            cmd += ["--require-game-files"]
        return cmd
