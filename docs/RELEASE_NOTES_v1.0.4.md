# PlayStation Studio v1.0.4 — Release Notes

**Date:** 2026-06-16 · **Headline:** re-scanning a different PKG folder now works,
and Documentation/About render as HTML.

---

## 🛠 Fixes

- **Re-scan re-maps the package HTTP server.** The server was created once and
  kept serving the *first* folder you scanned. After scanning a different folder,
  installs failed with _"Unable to set up prerequisites"_ because the download
  URL (built relative to the new folder) was resolved against the old directory.
  An install now retires a server bound to a different folder/port and rebinds to
  the folder you last scanned.

## ✨ Improvements

- **Help → Documentation** opens an in-app viewer that renders `README.md` as
  formatted HTML — headings, **bold**, clickable links (open in your browser),
  and the screenshots — instead of launching a text editor on the raw markdown.
  Includes an "Open on GitHub" button.
- **Help → About** is now a rich HTML panel with the app icon, version, feature
  list and clickable credit links (MkPFS, flatz, etaHEN), instead of a plain
  text box.

## 🧩 Engine

- PS5 compression engine stays on **MkPFS 0.0.8** (the latest released version).
  An unreleased 0.0.9 exists upstream but its only engine change is a parallel
  worker-count cap; the core packer is otherwise identical.

## 💻 Downloads

- Windows 10/11 (x64): `PlayStation-Studio-Windows.zip`
- macOS (Apple Silicon): `PlayStation-Studio-macOS.zip`

Builds are unsigned — on macOS right-click → **Open**; on Windows **More info →
Run anyway**.

## 🙏 Credits

PS4 remote-install protocol & host tool: **flatz' ps4_remote_pkg_installer**.
PS5 compression engine: **MkPFS 0.0.8** by **PSBrew**. PS5 install via **etaHEN**
DPI.
