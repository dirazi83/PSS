# PlayStation Studio v1.0.3 — Release Notes

**Date:** 2026-06-15 · **Headline:** safer one-at-a-time PS4 installs, selective
install controls, and a modern macOS look.

---

## 🛠 PS4 install — one at a time

- **Strictly sequential installs.** The next package is queued only after the
  previous one finishes, with a short settle pause between packages. Firing
  installs back-to-back is what makes the PS4's Remote PKG Installer crash —
  one-at-a-time avoids it.
- **Concurrency guard** — a second install run can't start while one is active
  (all install buttons disable for the duration), so two streams never hit the
  console at once.
- **Cancellable** — closing the app mid-install stops the loop cleanly instead
  of leaving a thread hammering the console.

## ✨ Install controls

- **Install Selected** — install only the rows you highlight (multi-select with
  Shift / Cmd). Progress maps back to the correct queue rows.
- **Remove Selected** — drop the highlighted rows from the queue and untick
  their source packages.
- These sit alongside the existing **Install All** and **Clear**.

## 🔄 In-app updater

- **Help → Check for Updates** compares your running version against the latest
  GitHub release. On packaged builds it can **download and install** the new
  version in place (with a progress bar) and relaunch — no manual re-download.
- macOS swaps the `.app` bundle with `ditto` (preserving symlinks + the exec
  bit); Windows mirrors the app folder and relaunches.
- The repo is public, so no token is embedded. From source it points you at
  `git pull` instead.

## 🎨 Modern macOS look

- On **macOS**, the app now uses a "Liquid Glass" theme: translucent glass
  surfaces over a dark window gradient, the **SF Pro** system font, the macOS
  **system-blue** accent, hairline separators and rounder corners.
- **Windows and Linux are unchanged** — they keep the existing dark theme.
- This is a styled (simulated) glass look; it does not require any extra native
  dependencies.

## 💻 Downloads

- Windows 10/11 (x64): `PlayStation-Studio-Windows.zip`
- macOS (Apple Silicon): `PlayStation-Studio-macOS.zip`

Builds are unsigned — on macOS right-click → **Open**; on Windows **More info →
Run anyway**. If your browser/AV flags the download, see the README ("download
blocked" section).

## 🙏 Credits

PS4 remote-install protocol & host tool: **flatz' ps4_remote_pkg_installer**
(<https://github.com/flatz/ps4_remote_pkg_installer>). PS5 compression engine:
**MkPFS 0.0.8** by **PSBrew**. PS5 install via **etaHEN** DPI.
