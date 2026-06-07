"""Filesystem helpers: detect slow network mounts and free space.

Compressing a game that lives on an SMB/NFS share means reading thousands of
files over the network, which is extremely slow and makes the app look frozen.
We detect that up front and warn the user to work from a local disk.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

# Network / remote filesystem type names across platforms.
NETWORK_FSTYPES = {
    "smbfs", "cifs", "nfs", "nfs4", "afpfs", "webdav", "ftp",
    "fuse.sshfs", "fuse.smbnetfs", "fuse.davfs",
}


def free_space_bytes(path: str) -> int | None:
    """Free bytes on the volume containing *path*, or None if unknown."""
    try:
        probe = path
        while probe and not os.path.exists(probe):
            probe = os.path.dirname(probe)
        return shutil.disk_usage(probe or os.getcwd()).free
    except OSError:
        return None


def _posix_mount_fstype(path: str) -> str | None:
    """Find the filesystem type of the mount that contains *path* (POSIX)."""
    try:
        out = subprocess.run(
            ["mount"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    best_mount: str = ""
    best_fs: str | None = None
    for line in out.splitlines():
        if " on " not in line:
            continue
        after = line.split(" on ", 1)[1]
        if " type " in after:                       # Linux: "... on /mnt type ext4 (..)"
            mount_point = after.split(" type ", 1)[0].strip()
            fstype: str | None = after.split(" type ", 1)[1].split(" ", 1)[0]
        elif " (" in after:                         # macOS: "... on /mnt (smbfs, ..)"
            mount_point = after.split(" (", 1)[0].strip()
            fstype = after.split("(", 1)[1].split(",", 1)[0].split(")", 1)[0].strip()
        else:
            continue
        if path == mount_point or path.startswith(mount_point.rstrip("/") + "/"):
            if len(mount_point) >= len(best_mount):
                best_mount, best_fs = mount_point, fstype
    return best_fs


def _windows_is_remote(path: str) -> bool:
    abspath = os.path.abspath(path)
    if abspath.startswith("\\\\") or abspath.startswith("//"):   # UNC path
        return True
    drive = os.path.splitdrive(abspath)[0]
    if not drive:
        return False
    try:
        import ctypes
        DRIVE_REMOTE = 4
        return ctypes.windll.kernel32.GetDriveTypeW(drive + "\\") == DRIVE_REMOTE
    except (OSError, AttributeError, ValueError):
        return False


def is_network_path(path: str) -> bool:
    """True if *path* lives on a network / remote mount (SMB, NFS, …)."""
    try:
        real = os.path.realpath(path)
    except OSError:
        real = path
    if sys.platform.startswith("win"):
        return _windows_is_remote(real)
    return (_posix_mount_fstype(real) or "").lower() in NETWORK_FSTYPES


# macOS "dataless" (evicted to iCloud) file flag. A file with this flag has no
# local data, reading it forces an on-demand download.
_SF_DATALESS = 0x40000000


def _icloud_desktop_documents_enabled() -> bool:
    """True when macOS 'Desktop & Documents' iCloud sync appears enabled."""
    base = (os.path.expanduser("~") +
            "/Library/Mobile Documents/com~apple~CloudDocs")
    return os.path.isdir(base + "/Desktop") or os.path.isdir(base + "/Documents")


def is_cloud_synced_path(path: str) -> bool:
    """True if *path* lives in an iCloud-synced location (macOS).

    Covers iCloud Drive itself and the 'Desktop & Documents' sync feature, where
    files are downloaded on demand and can be evicted under disk pressure, making
    bulk reads extremely slow or causing them to fail outright.
    """
    if not sys.platform == "darwin":
        return False
    try:
        real = os.path.realpath(path)
    except OSError:
        real = path
    if "/Library/Mobile Documents/" in real or "com~apple~CloudDocs" in real:
        return True
    if _icloud_desktop_documents_enabled():
        home = os.path.realpath(os.path.expanduser("~"))
        for sub in ("Desktop", "Documents"):
            d = os.path.join(home, sub)
            if real == d or real.startswith(d + os.sep):
                return True
    return False


def count_dataless_files(path: str, sample_limit: int = 4000) -> int:
    """Count iCloud-evicted (dataless) files under *path*, sampling up to a cap.

    Returns the number of dataless files found in the first *sample_limit* files.
    Uses ``lstat`` so it never triggers a download just to check.
    """
    found = 0
    checked = 0
    for dirpath, _dirs, files in os.walk(path):
        for f in files:
            try:
                st = os.lstat(os.path.join(dirpath, f))
                if getattr(st, "st_flags", 0) & _SF_DATALESS:
                    found += 1
            except OSError:
                pass
            checked += 1
            if checked >= sample_limit:
                return found
    return found
