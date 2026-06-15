"""In-app updater.

Checks the project's GitHub Releases for a newer version and (for packaged
builds) downloads the matching zip and self-replaces the running app, then
relaunches. The repo is public, so no token/auth is needed.

Flow:
  UpdateChecker   -> queries /releases/latest, compares to the running version
  UpdateInstaller -> downloads + extracts the platform zip to a temp folder
  apply_and_relaunch -> spawns a detached helper that waits for this process to
                        exit, swaps the app on disk, and relaunches it
"""

from __future__ import annotations

import json
import os
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from PySide6.QtCore import QThread, Signal


def _ssl_context() -> ssl.SSLContext:
    """A verifying SSL context. Prefer certifi's CA bundle — python.org and
    PyInstaller builds often lack a usable system CA store, which otherwise
    fails GitHub's HTTPS with CERTIFICATE_VERIFY_FAILED."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


_SSL = _ssl_context()

REPO = "dirazi83/PSS"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
_UA = {"User-Agent": "PlayStation-Studio-Updater",
       "Accept": "application/vnd.github+json"}


def is_frozen() -> bool:
    """True when running as a PyInstaller build (vs. from source)."""
    return bool(getattr(sys, "frozen", False))


def asset_name() -> str:
    """The release asset for this platform."""
    return ("PlayStation-Studio-macOS.zip" if sys.platform == "darwin"
            else "PlayStation-Studio-Windows.zip")


def app_target() -> Path | None:
    """The on-disk app to replace: the .app bundle (macOS) or onedir folder
    (Windows). ``None`` when running from source (nothing to self-replace)."""
    if not is_frozen():
        return None
    exe = Path(sys.executable)
    if sys.platform == "darwin":
        for parent in exe.parents:
            if parent.suffix == ".app":
                return parent
        return None
    return exe.parent           # Windows onedir folder


def _parse(version: str) -> tuple[int, ...]:
    out: list[int] = []
    for chunk in version.strip().lstrip("vV").split("."):
        digits = ""
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        out.append(int(digits) if digits else 0)
    return tuple(out) or (0,)


def is_newer(latest: str, current: str) -> bool:
    a, b = _parse(latest), _parse(current)
    n = max(len(a), len(b))
    a += (0,) * (n - len(a))
    b += (0,) * (n - len(b))
    return a > b


class UpdateChecker(QThread):
    """Query the latest release in the background."""

    done = Signal(dict)   # {ok, available?, latest, current, notes, url, asset_url, error?}

    def __init__(self, current: str, parent=None) -> None:
        super().__init__(parent)
        self.current = current

    def run(self) -> None:
        try:
            req = urllib.request.Request(LATEST_API, headers=_UA)
            with urllib.request.urlopen(req, timeout=12, context=_SSL) as r:
                data = json.load(r)
        except (urllib.error.URLError, OSError, ValueError) as e:
            self.done.emit({"ok": False, "error": str(e)})
            return
        tag = data.get("tag_name", "") or ""
        want = asset_name()
        asset_url = ""
        for a in data.get("assets", []):
            if a.get("name") == want:
                asset_url = a.get("browser_download_url", "")
                break
        self.done.emit({
            "ok": True,
            "available": is_newer(tag, self.current),
            "latest": tag,
            "current": self.current,
            "notes": data.get("body", "") or "",
            "url": data.get("html_url", RELEASES_PAGE),
            "asset_url": asset_url,
        })


class UpdateInstaller(QThread):
    """Download + extract the update zip to a temp folder."""

    progress = Signal(int)        # 0..100 (-1 = indeterminate)
    status = Signal(str)
    ready = Signal(str)           # path to the extracted new app
    failed = Signal(str)

    def __init__(self, asset_url: str, parent=None) -> None:
        super().__init__(parent)
        self.asset_url = asset_url
        self._tmp = Path(tempfile.mkdtemp(prefix="pss-update-"))
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        zip_path = self._tmp / "update.zip"
        extract_dir = self._tmp / "app"
        try:
            self.status.emit("Downloading update…")
            req = urllib.request.Request(self.asset_url,
                                         headers={"User-Agent": _UA["User-Agent"]})
            with urllib.request.urlopen(req, timeout=30, context=_SSL) as r:
                total = int(r.headers.get("Content-Length", 0) or 0)
                got = 0
                with open(zip_path, "wb") as f:
                    while True:
                        if self._cancel:
                            return
                        chunk = r.read(262144)
                        if not chunk:
                            break
                        f.write(chunk)
                        got += len(chunk)
                        self.progress.emit(int(got / total * 100) if total else -1)

            self.status.emit("Extracting…")
            extract_dir.mkdir(parents=True, exist_ok=True)
            if sys.platform == "darwin":
                # ditto preserves bundle symlinks + the executable bit, which
                # Python's zipfile would silently drop (the .app wouldn't launch).
                subprocess.run(["/usr/bin/ditto", "-x", "-k",
                                str(zip_path), str(extract_dir)], check=True)
                new_app = next(extract_dir.glob("*.app"), None)
            else:
                with zipfile.ZipFile(zip_path) as z:
                    z.extractall(extract_dir)
                new_app = next((p for p in extract_dir.iterdir() if p.is_dir()), None)

            if new_app is None:
                self.failed.emit("The update archive didn't contain the app.")
                return
            self.ready.emit(str(new_app))
        except (urllib.error.URLError, OSError, zipfile.BadZipFile,
                subprocess.CalledProcessError) as e:
            self.failed.emit(str(e))


def apply_and_relaunch(new_app: str) -> None:
    """Spawn a detached helper that waits for us to quit, swaps the app on disk,
    and relaunches it. The caller should quit the app immediately after."""
    target = app_target()
    if target is None:
        raise RuntimeError("Not a packaged build — nothing to replace.")
    pid = os.getpid()
    tmp = Path(tempfile.gettempdir())

    if sys.platform == "darwin":
        script = (
            "#!/bin/sh\n"
            f'while kill -0 {pid} 2>/dev/null; do sleep 0.4; done\n'
            f'if /usr/bin/ditto "{new_app}" "{target}.new"; then\n'
            f'  rm -rf "{target}"\n'
            f'  mv "{target}.new" "{target}"\n'
            "fi\n"
            f'xattr -dr com.apple.quarantine "{target}" 2>/dev/null\n'
            f'open "{target}"\n'
        )
        sh = tmp / "pss_update.sh"
        sh.write_text(script, encoding="utf-8")
        os.chmod(sh, 0o755)
        subprocess.Popen(["/bin/sh", str(sh)], start_new_session=True)
    else:
        exe = str(target / "PlayStation Studio.exe")
        bat = (
            "@echo off\r\n"
            ":wait\r\n"
            f'tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul && '
            "(timeout /t 1 /nobreak >nul & goto wait)\r\n"
            f'robocopy "{new_app}" "{target}" /MIR /NJH /NJS /NDL /NFL /NP >nul\r\n'
            f'start "" "{exe}"\r\n'
        )
        bp = tmp / "pss_update.bat"
        bp.write_text(bat, encoding="utf-8")
        DETACHED = 0x00000008 | 0x00000200 | 0x08000000  # detached, new group, no window
        subprocess.Popen(["cmd", "/c", str(bp)], creationflags=DETACHED, close_fds=True)
