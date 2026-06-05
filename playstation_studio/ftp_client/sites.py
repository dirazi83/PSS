"""FTP Site Manager — CRUD persisted via the shared config store.

Passwords are stored in the OS keyring when the optional ``keyring`` package
is installed; otherwise they fall back into the config file (clearly flagged
as insecure). Site metadata always lives in config.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field

from ..shared.config import config

CFG = "ftp_sites"
KEYRING_SERVICE = "PlayStationStudio-FTP"

try:                                   # optional secure storage
    import keyring
    HAVE_KEYRING = True
except Exception:                      # pragma: no cover - import guard
    keyring = None
    HAVE_KEYRING = False


@dataclass
class Site:
    name: str = "New Site"
    host: str = ""
    port: int = 21
    user: str = ""
    anonymous: bool = False
    passive: bool = True
    remote_dir: str = "/"
    local_dir: str = ""
    notes: str = ""
    favorite: bool = False
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    # password is handled separately (keyring / fallback), never in asdict()
    password: str = field(default="", compare=False, repr=False)


class SiteManager:
    """Loads/saves the list of FTP sites and their credentials."""

    def __init__(self) -> None:
        self.sites: list[Site] = []
        self._load()

    # ---- persistence ----
    def _load(self) -> None:
        raw = config.get(CFG, "sites", []) or []
        self.sites = []
        for d in raw:
            site = Site(**{k: v for k, v in d.items() if k in Site.__annotations__})
            site.password = self._read_password(site.id, d.get("password", ""))
            self.sites.append(site)

    def _save(self) -> None:
        out = []
        for s in self.sites:
            d = asdict(s)
            d.pop("password", None)
            if not self._write_password(s.id, s.password):
                d["password"] = s.password      # insecure fallback
            out.append(d)
        config.set(CFG, "sites", out)

    # ---- credential storage ----
    def _read_password(self, site_id: str, fallback: str) -> str:
        if HAVE_KEYRING:
            try:
                pw = keyring.get_password(KEYRING_SERVICE, site_id)
                if pw is not None:
                    return pw
            except Exception:
                pass
        return fallback

    def _write_password(self, site_id: str, password: str) -> bool:
        """Return True if stored securely (keyring), False if caller must
        keep it in config."""
        if HAVE_KEYRING and password:
            try:
                keyring.set_password(KEYRING_SERVICE, site_id, password)
                return True
            except Exception:
                return False
        return False

    # ---- CRUD ----
    def add(self, site: Site) -> Site:
        self.sites.append(site)
        self._save()
        return site

    def update(self, site: Site) -> None:
        self._save()

    def remove(self, site: Site) -> None:
        if HAVE_KEYRING:
            try:
                keyring.delete_password(KEYRING_SERVICE, site.id)
            except Exception:
                pass
        self.sites = [s for s in self.sites if s.id != site.id]
        self._save()

    def duplicate(self, site: Site) -> Site:
        clone = Site(**{k: getattr(site, k) for k in Site.__annotations__
                        if k != "id"})
        clone.name = f"{site.name} (copy)"
        clone.password = site.password
        return self.add(clone)

    def find(self, site_id: str) -> Site | None:
        return next((s for s in self.sites if s.id == site_id), None)
