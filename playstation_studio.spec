# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for PlayStation Studio.

Build:  ./build_app.sh        (or: pyinstaller --noconfirm playstation_studio.spec)
Output: dist/PlayStation Studio.app  (macOS)  /  dist/PlayStation Studio/  (Win/Linux)
"""

import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

PKG = "playstation_studio"

# --- bundled data: icons, svg sources, exploit-host site -------------------
datas = [
    (f"{PKG}/assets/icons", f"{PKG}/assets/icons"),
    (f"{PKG}/assets/svg", f"{PKG}/assets/svg"),
    (f"{PKG}/ps4_manager/exploit_host", f"{PKG}/ps4_manager/exploit_host"),
    ("README.md", "."),
]
datas += collect_data_files("mkpfs")          # the PS5 engine's data files

# --- imports PyInstaller can't see automatically ---------------------------
hiddenimports = collect_submodules("mkpfs") + ["PySide6.QtSvg", "openpyxl"]
for optional in ("keyring",):                 # only if installed
    try:
        __import__(optional)
        hiddenimports += collect_submodules(optional)
    except Exception:
        pass

block_cipher = None

# platform-specific app icon
ICON = f"{PKG}/assets/app.ico" if sys.platform.startswith("win") else f"{PKG}/assets/app.icns"

# Windows version resource (CompanyName/ProductName/etc.). Embedding real
# metadata makes an unsigned PyInstaller exe look like legitimate software and
# clears many antivirus / SmartScreen false positives. Windows-only.
VERSION_FILE = f"{PKG}/version_info.txt" if sys.platform.startswith("win") else None

# Do NOT pack with UPX: UPX-compressed PyInstaller binaries are flagged as
# malware far more often (packers are associated with malware), which is a
# major cause of the "this download may be a virus" block.
USE_UPX = False

a = Analysis(
    ["pyi_entry.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "pyftpdlib"],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="PlayStation Studio",
    console=False,                            # GUI app — no terminal window
    disable_windowed_traceback=False,
    upx=USE_UPX,                              # never UPX-pack (AV false positives)
    icon=ICON,
    version=VERSION_FILE,                     # Windows metadata (reduces AV flags)
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    upx=USE_UPX,
    name="PlayStation Studio",
)

# macOS: wrap into a double-clickable .app bundle
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="PlayStation Studio.app",
        icon=f"{PKG}/assets/app.icns",
        bundle_identifier="com.playstationstudio.app",
        info_plist={
            "CFBundleName": "PlayStation Studio",
            "CFBundleShortVersionString": "1.0.1",
            "NSHighResolutionCapable": True,
        },
    )
