"""Pure-Python PlayStation ``.pkg`` reader.

Parses the ``param.sfo`` embedded in a PS4 ``.pkg`` (magic ``\\x7FCNT``) and
returns its metadata plus the ``icon0.png`` cover art. No third-party
dependencies and fully cross-platform — adapted from the original
PKGINFO.py of the PS4 PKGs Manager.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass, field

PSF_MAGIC = b"\0PSF"
PKG_MAGIC = b"\x7FCNT"

# param.sfo file-table entry ids
ENTRY_PARAM_SFO = 0x1000
ENTRY_ICON0_PNG = 0x1200

CATEGORY_LABELS = {"gd": "Game", "gp": "Update", "ac": "DLC"}

# CONTENT_ID first byte -> region
_REGION_BY_PREFIX = {ord("E"): "EU", ord("U"): "US", ord("H"): "CN", ord("I"): "IN", ord("J"): "JP"}

TITLE_LANG_MAP = {
    "00": "JA", "01": "EN", "02": "FR", "03": "ES", "04": "DE",
    "05": "IT", "06": "NL", "07": "PT", "08": "RU", "09": "KO",
    "10": "CH", "11": "ZH", "12": "FI", "13": "SV", "14": "DA",
    "15": "NO", "16": "PL", "17": "BR", "18": "GB", "19": "TR",
    "20": "LA", "21": "AR", "22": "CA", "23": "CS", "24": "HU",
    "25": "EL", "26": "RO", "27": "TH", "28": "VI", "29": "IN",
}


def convert_bytes(num: float) -> str:
    """Human-readable byte size, e.g. ``12.4 GB``."""
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if num < 1024.0:
            return f"{num:3.1f} {unit}"
        num /= 1024.0
    return f"{num:3.1f} PB"


def _le32(b: bytes) -> int:
    return b[0] | (b[1] << 8) | (b[2] << 16) | (b[3] << 24)


def _le16(b: bytes) -> int:
    return b[0] | (b[1] << 8)


@dataclass
class PkgInfo:
    """Parsed metadata for a single ``.pkg`` file."""

    path: str
    title: str = ""
    title_id: str = ""
    content_id: str = ""
    category: str = ""           # raw: gd / gp / ac
    version: str = ""
    app_ver: str = ""
    app_type: str = ""
    fmt: str = ""
    system_ver: str = ""
    sys_ver: str = ""
    parental_level: str = ""
    size: str = ""
    size_bytes: int = 0
    region: str = "UNKNOWN"
    languages: str = ""
    ver: str = ""
    icon: bytes = b""
    raw: dict = field(default_factory=dict)

    @property
    def category_label(self) -> str:
        return CATEGORY_LABELS.get(self.category, self.category or "Unknown")

    def as_row(self) -> dict:
        """Flat string dict for table display / export."""
        return {
            "TITLE_ID": self.title_id, "TITLE": self.title.strip(),
            "CONTENT_ID": self.content_id, "VERSION": self.version,
            "APP_TYPE": self.app_type, "APP_VER": self.app_ver,
            "CATEGORY": self.category_label, "FORMAT": self.fmt,
            "PARENTAL_LEVEL": self.parental_level, "SYSTEM_VER": self.system_ver,
            "SIZE": self.size, "REGION": self.region, "SYS_VER": self.sys_ver,
            "VER": self.ver, "LANGUAGES": self.languages,
            "PATH": os.path.normpath(self.path),
        }


def _read_file_table(f, num_entries: int, table_offset: int) -> list[dict]:
    entries = []
    f.seek(table_offset)
    fmt = ">IIIIII8x"
    size = struct.calcsize(fmt)
    for _ in range(num_entries):
        etype, _unk, _f1, _f2, offset, length = struct.unpack(fmt, f.read(size))
        entries.append({"type": etype, "offset": offset, "size": length})
    return entries


def _parse_param_sfo(data: bytes) -> dict[str, str]:
    """Parse a raw param.sfo blob into a ``{key: str}`` dict."""
    if not data.startswith(PSF_MAGIC):
        return {}
    label_ptr = _le32(data[8:12])
    data_ptr = _le32(data[12:16])
    nsects = _le32(data[16:20])
    labels = data[label_ptr:]
    values = data[data_ptr:]

    out: dict[str, str] = {}
    index = 20  # sizeof(PsfHdr)
    for _ in range(nsects):
        sect = data[index:index + 16]
        if len(sect) < 16:
            break
        label_off = _le16(sect[0:2])
        data_type = sect[3]
        used = _le32(sect[4:8])
        data_off = _le32(sect[12:16])
        key = labels[label_off:].split(b"\x00", 1)[0].decode("ascii", "ignore")
        if data_type == 2:  # utf-8 string
            raw = values[data_off:data_off + used - 1]
            out[key] = raw.decode("utf-8", "ignore")
        elif data_type == 4:  # integer
            out[key] = "%X" % _le32(values[data_off:data_off + used])
        index += 16
    return out


def get_pkg_info(pkg_path: str, *, load_icon: bool = True) -> PkgInfo | None:
    """Read a ``.pkg`` and return :class:`PkgInfo`, or ``None`` if unreadable."""
    try:
        with open(pkg_path, "rb") as f:
            if f.read(4) != PKG_MAGIC:
                return None

            f.seek(0x10)
            num_entries = struct.unpack(">I", f.read(4))[0]
            f.seek(0x18)
            table_offset = struct.unpack(">I", f.read(4))[0]
            entries = _read_file_table(f, num_entries, table_offset)

            sfo: dict[str, str] = {}
            icon = b""
            for e in entries:
                if e["type"] == ENTRY_PARAM_SFO:
                    f.seek(e["offset"])
                    sfo = _parse_param_sfo(f.read(e["size"]))
                elif e["type"] == ENTRY_ICON0_PNG and load_icon:
                    f.seek(e["offset"])
                    icon = f.read(e["size"])

            f.seek(0, os.SEEK_END)
            size_bytes = f.tell()

        info = PkgInfo(path=pkg_path, raw=sfo, icon=icon, size_bytes=size_bytes)
        info.title = sfo.get("TITLE", "")
        info.title_id = sfo.get("TITLE_ID", "")
        info.content_id = sfo.get("CONTENT_ID", "")
        info.category = sfo.get("CATEGORY", "")
        info.version = sfo.get("VERSION", "")
        info.app_ver = sfo.get("APP_VER", "")
        info.app_type = sfo.get("APP_TYPE", "")
        info.fmt = sfo.get("FORMAT", "")
        info.parental_level = sfo.get("PARENTAL_LEVEL", "")
        info.system_ver = sfo.get("SYSTEM_VER", "")
        info.size = convert_bytes(size_bytes)

        if info.content_id:
            info.region = _REGION_BY_PREFIX.get(ord(info.content_id[0]), "UNKNOWN")

        if info.system_ver and len(info.system_ver) >= 3:
            info.sys_ver = f"{info.system_ver[0]}.{info.system_ver[1:3]}"

        langs = [v for k, v in TITLE_LANG_MAP.items()
                 if sfo.get(f"TITLE_{k}", "")]
        info.languages = ",".join(langs)

        info.ver = f"{info.app_ver}(U)" if info.category == "gp" else info.version
        return info
    except (OSError, struct.error, IndexError):
        return None


def iter_pkg_files(root: str):
    """Yield every ``.pkg`` path under *root* (recursive)."""
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if name.lower().endswith(".pkg"):
                yield os.path.join(dirpath, name)
