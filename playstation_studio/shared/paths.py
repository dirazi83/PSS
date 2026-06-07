"""Standard app directories and temp-folder policy.

On startup the app creates three working folders under the data root
(`~/.playstation_studio`):

- ``payloads/`` — a home for payload files (ELF/BIN/JAR/…).
- ``host/``     — host files served to consoles (exploit host, etc.).
- ``temp/``     — scratch space for the PS5 compressor's intermediate data.

The compressor writes a lot of intermediate data while packing a game. Where
that data lives matters for speed: a near-full or slow system disk makes packing
crawl. The temp folder is therefore configurable:

- ``app``    → the app's own ``temp/`` folder (default).
- ``custom`` → a folder the user picks (put it on a fast, empty disk).
- ``game``   → right next to the game being packed, so temp I/O stays on the
               same disk as the source. Stored in the game's *parent* (never
               inside the source tree, which would pollute the packed image).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from .config import CONFIG_DIR, config

# Fixed working folders under the app data root.
PAYLOADS_DIR = CONFIG_DIR / "payloads"
HOST_DIR = CONFIG_DIR / "host"
TEMP_DIR = CONFIG_DIR / "temp"

# Config location for the temp-folder policy (app-wide).
SEC = "general"
KEY_TEMP_MODE = "temp_mode"
KEY_TEMP_PATH = "temp_path"

TEMP_MODE_APP = "app"
TEMP_MODE_CUSTOM = "custom"
TEMP_MODE_GAME = "game"

# Name of the scratch folder created beside a game in "game" temp mode.
_GAME_TEMP_NAME = ".pss_tmp"


def ensure_app_dirs() -> None:
    """Create the standard working folders if they do not exist yet."""
    for d in (CONFIG_DIR, PAYLOADS_DIR, HOST_DIR, TEMP_DIR):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass


def temp_mode() -> str:
    """Return the current temp-folder mode ("app" / "custom" / "game")."""
    mode = config.get(SEC, KEY_TEMP_MODE, TEMP_MODE_APP) or TEMP_MODE_APP
    if mode not in (TEMP_MODE_APP, TEMP_MODE_CUSTOM, TEMP_MODE_GAME):
        return TEMP_MODE_APP
    return mode


def custom_temp_path() -> str:
    """Return the user-chosen custom temp folder (may be empty)."""
    return (config.get(SEC, KEY_TEMP_PATH, "") or "").strip()


def set_temp_policy(mode: str, path: str = "") -> None:
    """Persist the temp-folder mode and (for custom mode) its path."""
    config.update(SEC, **{KEY_TEMP_MODE: mode, KEY_TEMP_PATH: path.strip()})


def resolve_temp_dir(source_dir: str | None = None,
                     mode: str | None = None,
                     path: str | None = None) -> Path:
    """Resolve the temp directory to use for packing *source_dir*.

    Falls back to the system temp folder if the chosen location can't be
    created (e.g. an unplugged custom drive).
    """
    mode = mode or temp_mode()
    chosen: Path
    if mode == TEMP_MODE_GAME and source_dir:
        # Beside the game (its parent) so temp I/O stays on the source disk and
        # never lands inside the packed source tree.
        chosen = Path(source_dir).expanduser().resolve().parent / _GAME_TEMP_NAME
    elif mode == TEMP_MODE_CUSTOM and (path or custom_temp_path()):
        chosen = Path(path or custom_temp_path()).expanduser()
    else:
        chosen = TEMP_DIR

    try:
        chosen.mkdir(parents=True, exist_ok=True)
        return chosen
    except OSError:
        fallback = Path(tempfile.gettempdir())
        try:
            fallback.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        return fallback
