# PlayStation Studio v1.0.0 — Release Readiness Checklist

**Date:** 2026-06-07 · **Target:** v1.0.0 Initial Release

Legend: ✅ done · 🟡 recommended before publishing · ⬜ maintainer action

---

## Code & quality
- ✅ All modules byte-compile cleanly (`py_compile`).
- ✅ Application boots and loads all four tabs.
- ✅ FTP operations verified end-to-end (12/12) against a live server.
- ✅ Connection management & error handling reviewed.
- ✅ Network discovery / auto-detect (PS4 & PS5) reviewed.
- ✅ Transfer queue (cancel / pause / retry / aggregate folder jobs) reviewed.
- ✅ Large-file handling (64-bit progress, HTTP Range) reviewed.
- ✅ Drag & drop code paths reviewed.
- 🟡 Add an automated test suite + CI test step (the `pyftpdlib` harness is a good seed).

## Versioning & branding
- ✅ `__version__` = `1.0.0` (`playstation_studio/__init__.py`).
- ✅ `APP_VERSION` corrected to `1.0.0` (`interface/shell.py`).
- ✅ README updated to "Version 1.0.0 — Initial Release".
- ✅ Release notes written (`docs/RELEASE_NOTES_v1.0.0.md`).
- ⬜ **Resolve tag conflict:** tags `v1.0.0`–`v1.0.8` already exist. Either publish under a
  fresh tag (e.g. `v1.1.0`) or remove the stale tags before tagging the release.

## UI & theme
- ✅ Dark theme verified across all tabs.
- ✅ Dialog / list / multi-line-input contrast bug fixed and re-verified.
- ✅ Spacing, radii, palette consistent.
- ✅ Per-OS font stack configured (SF Pro / Segoe UI).
- ✅ High-DPI / resolution-flexible layout.
- ℹ️ Light mode intentionally not included (documented).

## Documentation
- ✅ README rewritten to professional OSS structure (18 sections + screenshots).
- ✅ Outdated / placeholder / beta references removed.
- ✅ Screenshots captured for all major tabs and features (`docs/screenshots/`).
- ✅ Code review, platform compatibility, theme validation reports added under `docs/`.
- ✅ Troubleshooting, Security Notes, Changelog, License sections present.

## Cross-platform
- ✅ macOS (Apple Silicon) runtime verified.
- 🟡 Smoke-test on Windows 10/11 (launch, connect, one transfer, dialog rendering).
- 🟡 Smoke-test on Intel macOS (or add a universal2 / second CI runner).

## Build & distribution
- ✅ CI builds macOS + Windows bundles on tag push (`.github/workflows/build.yml`).
- ✅ PyInstaller spec selects per-OS icons and bundles the MkPFS engine.
- 🟡 Code-sign + notarize (macOS) / sign (Windows) to avoid first-launch warnings.
- 🟡 Confirm release assets download, unzip and launch on a clean machine.

## Security
- ✅ Keyring-backed password storage with a clear plaintext-fallback warning.
- ✅ Local-only networking; HTTP server only active during installs.
- ✅ `requirements.txt` includes `keyring`; release builds bundle it via CI.
- ✅ Security Notes documented in the README.

---

## Go / No-Go

**Code & docs: GO.** The build is functionally verified and documented to a
production standard, with the review's findings fixed.

**Before announcing publicly**, complete the 🟡/⬜ items — most importantly:
1. Resolve the **tag conflict** (publish as a new tag or retire `v1.0.x` tags).
2. **Smoke-test Windows and Intel macOS** bundles.
3. (Recommended) **Code-sign / notarize** the distributed builds.
