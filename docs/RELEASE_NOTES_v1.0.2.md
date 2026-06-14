# PlayStation Studio v1.0.2 — Release Notes

**Date:** 2026-06-14 · **Headline:** PS4 remote install now works with real-world
package filenames, and reports the console's actual result.

This release fixes the PS4 **Remote PKG Installer** flow end-to-end. It was verified live
against a real PS4 (firmware-side flatz Remote PKG Installer on `:12800`).

---

## 🛠 PS4 remote install — fixed

- **Fixes _"Unable to set up prerequisites for package …"_.** Packages are now served to the
  console under an **ASCII-safe `/p/<hex>.pkg` alias**. flatz'
  [ps4_remote_pkg_installer](https://github.com/flatz/ps4_remote_pkg_installer) *unescapes*
  the URL before handing it to the console's HTTP client, so a real-world filename containing
  spaces, `()`, `{}` or `™` (e.g. `Plants-vs.-Zombies™_-Replanted-(CUSA55613)-{1.5-GB}.pkg`)
  turned into an invalid URL the PS4 couldn't even open — every such title failed **before it
  ever connected**. The hex alias survives unescaping; the HTTP server decodes it back to the
  real file on disk.
- **HTTP/1.1 package server** with keep-alive, matching the console's download client and the
  way it reads a package (header first, then ranged reads of the entry table, `param.sfo` and
  `icon0.png`).
- **Clear console error codes.** Rejected installs now decode the PS4's error code instead of
  guessing:
  - `0x80990015` → **"already installed on the PS4"** — shown as **Already installed** (a full
    bar, not a red failure). This is an expected state, not an error.
  - `0x80990004` → the base game/app isn't installed yet (an update or DLC with no base).
  - Any other code is printed in raw hex so it's diagnosable.

## ✨ PS4 Library

- **Clear** now also **unticks every selected package** across the Games / Updates / DLC lists
  and resets "Select all" — previously it only emptied the install queue.
- Ticking a game still pulls in its matching **update + DLC** automatically, grouped by Title
  ID (verified unique across the library, so it never pulls in a different title).

## 💻 Downloads

- Windows 10/11 (x64): `PlayStation-Studio-Windows.zip`
- macOS (Apple Silicon): `PlayStation-Studio-macOS.zip`

Builds are unsigned — on macOS right-click → **Open**; on Windows **More info → Run anyway**.
If your browser/AV flags the download, see the README ("download blocked" section).

## 🙏 Credits

PS4 remote-install protocol & host tool: **flatz' ps4_remote_pkg_installer**
(<https://github.com/flatz/ps4_remote_pkg_installer>). PS5 compression engine: **MkPFS 0.0.8**
by **PSBrew**. PS5 install via **etaHEN** DPI.
