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
    icon=ICON,
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
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
            "CFBundleShortVersionString": "1.0",
            "NSHighResolutionCapable": True,
        },
    )
