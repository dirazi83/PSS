# PlayStation Studio v1.0.0 — Release Notes

**Initial Release** · 2026-06-07

PlayStation Studio is an all-in-one desktop toolkit for PS4 / PS5 homebrew, combining a
dual-pane FTP client, a network payload sender, a PKG library manager, and a PS5 PFS
compressor in one modern, dark-themed window. Built with Python and PySide6, it ships as a
standalone app for Windows and macOS — no Python install required.

---

## ✨ Highlights

- **Dual-pane FTP client** with a full transfer queue, drag & drop, and a secure Site
  Manager.
- **One-click console detection** over the LAN (Sony DDP + TCP sweep) — add your PS4/PS5
  as a ready-to-connect FTP site automatically.
- **Payload sender** for `.elf` / `.bin` / `.jar` and more, with batch sending and
  per-file status.
- **PKG manager** with metadata, cover art, bulk rename, Excel export and remote
  install.
- **PS5 PFS compressor** with pre-flight size estimates, auto block-sizing and a history
  viewer.
- **Unified dark theme** across every tab and dialog.

---

## 📦 What's included

### FTP Client
- Local ⇄ remote dual-pane browser with back/forward/up history and an editable path bar.
- Upload & download of files **and** folders (recursive) over one reliable control
  connection.
- New Folder, Rename, Delete, Refresh — toolbar and right-click menus, multi-select.
- Transfer queue: per-item progress, speed, ETA; pause/resume, cancel, retry, clear.
- Drag & drop from the local pane or directly from Finder / Explorer.
- Site Manager with favorites, notes, and OS-keyring password storage.
- **Detect PS4 / PS5** — scans the LAN, probes console FTP ports (1337 / 2121 / 21), and
  adds sites in one click.
- MLSD listings with automatic LIST fallback; sortable columns; keyboard type-ahead.
- Advanced mode: raw FTP command bar, `chmod`, hidden files, recursive delete.

### Payload Sender
- Send `.elf` / `.bin` / `.jar` / `.self` / `.prx` / `.sprx` plus custom extensions over TCP.
- Add files, drag & drop, or recursively scan a folder; send one, selected, or all.
- Per-payload status, quick port presets, and console auto-detect.

### PKG Manager
- Scan folders of `.pkg` files, sorted into Games / Updates / DLC from `param.sfo`.
- Cover art, full metadata, live filter, bulk rename by template, Excel export.
- Remote install via the Remote PKG Installer (PS4) and etaHEN DPI v1/v2 (PS5), with
  progress and HTTP Range support for resumable console downloads.

### PS5 PFS Compressor
- Batch compression via the bundled MkPFS engine, with per-game progress and ratings.
- **Compress All** or **Compress Selected** — pack the whole queue or just the picked games.
- **ShadowMountPlus compatible** by default — images use a >= 32 KiB block so they mount
  cleanly under ShadowMountPlus; toggle off for the smallest image on tiny-file games.
- Pre-flight size estimate, auto block-sizing for small-file games, persistent history.
- Configurable temp folder; warnings for slow sources (network shares, iCloud).

### Application
- Persistent settings (`~/.playstation_studio/config.json`) restored on launch.
- Automatic creation of `payloads/`, `host/` and `temp/` working folders.
- Standalone Windows & macOS builds via GitHub Actions.

---

## 🛠️ Fixes & polish in this release

- **Theme:** fixed dialog, list and multi-line-input contrast so every window renders
  correctly in the dark theme.
- **Version:** unified the in-app version string to `1.0.0`.
- **Payload sender:** improved socket timeout handling and connection reliability.

---

## 💻 Supported platforms

- Windows 10 / 11 (x64)
- macOS — Apple Silicon (M1–M4) and Intel

See [`docs/PLATFORM_COMPATIBILITY.md`](PLATFORM_COMPATIBILITY.md) for the detailed matrix.

---

## 📥 Installation

Download the build for your platform from the Releases page, unzip, and launch. Builds are
unsigned — on macOS right-click → **Open**; on Windows choose **More info → Run anyway**.

To run from source: `./run.sh` (creates a venv, installs deps + the MkPFS engine, and
launches). Requires Python 3.8+.

---

## ⚠️ Known limitations

- **Dark theme only** — no light mode / theme switcher in v1.0.0.
- **No discrete Copy/Move buttons** — use upload/download (drag & drop) and remote rename.
- **No global cross-tab search** — file lists offer type-ahead; the PKG library has a live
  filter.
- **Unsigned builds** — first launch may be blocked by Gatekeeper / SmartScreen.

---

## 🙏 Credits

- PS5 compression engine: **MkPFS** by **PSBrew** (GPLv3, bundled).
- Inspired by **PS5-FFPFSC-PRO** by **KINGDKAK**.
- PS5 install via **etaHEN** DPI; PS4 via the **Remote PKG Installer**.
