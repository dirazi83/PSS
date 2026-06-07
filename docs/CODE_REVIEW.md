# PlayStation Studio — Code Review Report

**Release under review:** v1.0.0 (Initial Release)
**Date:** 2026-06-07
**Reviewer environment:** macOS (Darwin, Apple Silicon), Python 3.11, PySide6
**Scope:** Full project — FTP client, payload sender, PS4 PKG manager, PS5 PFS
compressor, shared infrastructure, build & CI.

> **Honesty note:** This report distinguishes what was *verified by execution* in this
> environment from what was *reviewed statically* and from what *cannot be verified here*
> (e.g. Windows runtime, real console hardware). Claims are labelled accordingly.

---

## 1. Summary

| Area | Result |
| --- | --- |
| Byte-compile (all modules) | ✅ Pass — no syntax errors |
| Application boot (offscreen) | ✅ Pass — window + 4 tabs load |
| FTP operations (live server) | ✅ **12/12 verified** end-to-end |
| Theme / dialog rendering | ⚠️→✅ Bug found and **fixed** (see §4.1) |
| Version consistency | ⚠️→✅ `APP_VERSION` corrected to `1.0.0` |
| Copy / Move (discrete ops) | ℹ️ Not implemented as buttons — by design (see §4.3) |
| Global search | ℹ️ Type-ahead + PKG filter only (see §4.4) |
| Cross-platform runtime | ⚠️ Verified on macOS only; Win/Intel via CI build (see compat report) |

**Overall:** The codebase is clean, well-structured and production-ready for v1.0.0. One
real UI contrast bug and one version-string inconsistency were found and fixed during this
review. Remaining items are documentation/expectation notes, not defects.

---

## 2. Verification performed

### 2.1 Static / build
- `python -m py_compile` over every module in `playstation_studio/` → **clean**.
- Cold boot under `QT_QPA_PLATFORM=offscreen`: `MainWindow` constructs, all four tabs
  instantiate, background FTP service thread starts and shuts down cleanly.

### 2.2 FTP engine — end-to-end (live `pyftpdlib` server)
A throwaway FTP server was started on `127.0.0.1` and the real `FtpEngine` exercised
against it. **All 12 checks passed:**

| # | Operation | Result |
| --- | --- | --- |
| 1 | `connect` (login, passive) | ✅ |
| 2 | `mkdir` | ✅ |
| 3 | `upload` + `list_dir` (MLSD) | ✅ (500 KB, size verified) |
| 4 | `size` | ✅ |
| 5 | `download` (byte-for-byte) | ✅ |
| 6 | `rename` (RNFR/RNTO) | ✅ |
| 7 | `delete` (file) | ✅ |
| 8 | `upload_tree` (recursive folder) | ✅ (2 files, nested) |
| 9 | `download_tree` (recursive folder) | ✅ |
| 10 | `delete_recursive` | ✅ |
| 11 | `raw` command (PWD) | ✅ |
| 12 | `disconnect` | ✅ |

This validates **upload, download, delete, rename, create-folder, refresh (list),
recursive folder transfer and raw commands** at the engine level.

### 2.3 Verified by code path inspection (not runtime)
- **Drag & drop:** `FileTable` implements both drag-source (`startDrag` emits `file://`
  URLs) and drop-target (`dropEvent` → `filesDropped`) paths; wired to `_on_remote_drop`
  → `_enqueue("upload", …)`. Logic is correct; requires a desktop session to exercise
  interactively.
- **Transfer queue stability:** single serialized worker thread (`FtpService.run`) with a
  thread-safe command queue; cancel/pause use a lock + `threading.Event`; folder jobs are
  expanded inside the worker and reported as one aggregate job. Cancellation is honoured
  both between files and mid-stream (`_tick` / `should_cancel`). Design is sound.
- **Connection management & error handling:** all FTP calls are wrapped in
  `ftplib.all_errors` / `OSError` handlers that emit failure signals to the UI rather than
  crashing; `disconnect()` degrades from `quit()` → `close()` safely.
- **Network discovery:** DDP broadcast (UDP 987/9302) + bounded TCP sweep (64-worker pool,
  0.25 s timeouts) with de-duplication by IP. Correct and resource-bounded.
- **Large file transfers:** binary mode enforced (`TYPE I`); 64 KiB block size; the
  remote-install HTTP server uses `qlonglong` (64-bit) progress signals specifically to
  handle >2 GB packages and implements HTTP Range (206/416) for resumable console pulls.

---

## 3. Module-by-module notes

| Module | Assessment |
| --- | --- |
| `ftp_client/ftp_engine.py` | Clean ftplib wrapper; correct MLSD→LIST fallback; recursive walks are iterative (no recursion-depth risk). ✅ |
| `ftp_client/ftp_tab.py` | Well-organised UI; drag/drop, context menus, sorting, queue rendering all coherent. ✅ |
| `ftp_client/sites.py` | Sensible keyring abstraction with graceful fallback; passwords kept out of `asdict()`. ✅ |
| `ftp_client/site_dialog.py` / `ftp_detect.py` | Clear dialogs; detection greys out FTP-less consoles. ✅ |
| `shared/discovery.py` | Robust scanner; bounded threads; safe socket handling. ✅ |
| `shared/config.py` | Atomic write via temp file + `os.replace`; thread-locked save. ✅ |
| `shared/theme.py` | Central palette; **dialog/list contrast bug fixed** (see §4.1). ✅ |
| `shared/paths.py` | Clear temp-folder policy with fallback to system temp. ✅ |
| `payload_sender/sender.py` | Improved connect/stream timeout split; graceful ACK handling. ✅ (minor: missing trailing newline — cosmetic) |
| `payload_sender/sender_tab.py` | Solid batch sending with per-row status; drag/drop of files & folders. ✅ |
| `ps4_manager/remote_install.py` | Stdlib HTTP server with Range support; uses `ast.literal_eval` (safe) for RPI responses; handles DPI v1/v2. ✅ |
| `interface/shell.py` | Menu/nav/status wiring; **version string corrected**. ✅ |

---

## 4. Findings

### 4.1 [Fixed] Dialogs rendered light-on-light (contrast bug) — **High**
**Symptom:** Every `QDialog` (Site Manager, Detect dialogs, rename / new-folder / chmod
input dialogs, delete confirmations, About box) inherited Fusion's near-white window
background (`#efefef`) while the global stylesheet forced text to light `#e6e8ef`, making
`QLabel` text effectively invisible.
**Root cause:** the stylesheet styled `QWidget#Root` and specific widgets but never set a
background for top-level `QDialog` / `QMessageBox`, nor for `QListWidget` / multi-line
inputs.
**Fix (`shared/theme.py`):** added dark backgrounds and explicit text colors for
`QDialog`, `QMessageBox`, `QInputDialog` labels; added a full `QListWidget` / `QListView`
style; folded `QPlainTextEdit` / `QTextEdit` into the input styling. Verified by
re-rendering the Site Manager and detection dialogs — labels and lists now read correctly.

### 4.2 [Fixed] Version string inconsistency — **Low**
`interface/shell.py` had `APP_VERSION = "1.0"` while `__init__.py` declared
`__version__ = "1.0.0"`. Corrected `APP_VERSION` to `"1.0.0"` so the About box matches the
release.

### 4.3 [Note] Copy / Move are not discrete operations — **By design**
There is no dedicated "Copy" or "Move" button. Local↔console moves/copies are achieved via
the upload/download transfer engine (drag & drop or the toolbar), and remote rename
(`RNFR`/`RNTO`) can relocate items server-side. The README documents this accurately. A
one-click server-side copy is a reasonable future enhancement.

### 4.4 [Note] No global search — **By design**
File lists support keyboard type-ahead, and the PS4 PKG Manager has a live filter box.
There is no cross-tab global search in v1.0.0. Documented as such.

### 4.5 [Environment] `keyring` absent in the current dev virtualenv — **Low**
`requirements.txt` lists `keyring>=24`, and `run.sh` / CI install it, but the existing
local `.venv` did not have it, so password storage would fall back to plaintext config in
that venv. Not a code defect; ensure end-user builds include keyring (CI installs from
`requirements.txt`, so release bundles are fine). The Site Manager already warns the user
when keyring is unavailable.

### 4.6 [Release hygiene] Pre-existing tags `v1.0.0`–`v1.0.8` — **Action for maintainer**
The repository already has tags through `v1.0.8`. Presenting this build as the "v1.0.0
Initial Release" conflicts with those tags. **Recommendation:** either cut the public
release under a fresh tag (e.g. `v1.1.0`) while keeping "Initial public release" framing,
or delete/retire the stale tags before publishing. This is a maintainer decision, not a
code change.

---

## 5. Recommendations (non-blocking, future)

1. Add a one-click **server-side copy** and an explicit **Move** action in the FTP panes.
2. Add a small **automated test suite** (the `pyftpdlib` harness used here is a good seed)
   and wire it into CI alongside the build.
3. Add a trailing newline to `payload_sender/sender.py` (cosmetic).
4. Consider an optional **light theme** + switcher (currently dark-only).
5. Consider **code-signing / notarization** for distributed builds to avoid OS warnings.

---

## 6. Conclusion

The project is **approved for a v1.0.0 release** from a code-quality standpoint. The FTP
feature set — the core of this release — was verified working end-to-end. The one
user-facing defect found (dialog contrast) has been fixed, and the version string
corrected. Remaining items are documentation notes and optional future enhancements.
