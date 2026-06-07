# PlayStation Studio — Platform Compatibility Report

**Release:** v1.0.0 (Initial Release)
**Date:** 2026-06-07

> **Honesty note:** Only macOS (Apple Silicon) was available as a live runtime in this
> review environment. Other targets are assessed from the build matrix, the dependency
> stack, and platform-specific code paths. Each row states the **basis** for its rating so
> nothing is overstated.

---

## 1. Target matrix

| Platform | Architecture | Status | Basis |
| --- | --- | --- | --- |
| **macOS (Apple Silicon M1–M4)** | arm64 | ✅ **Verified** | App booted and ran in this environment; FTP engine tested live. |
| **macOS (Intel)** | x86_64 | 🟡 **Expected-compatible** | Same Python/PySide6/stdlib stack; no arch-specific code. Build via `macos-latest` CI / local `build_app.sh`. |
| **Windows 11** | x64 | 🟡 **Expected-compatible** | Built by CI (`windows-latest`); Windows-specific paths handled (see §3). Runtime not tested here. |
| **Windows 10** | x64 | 🟡 **Expected-compatible** | Same as Windows 11; PySide6 6.6+ supports Windows 10/11. |
| **Linux** | x86_64 | 🟡 **Source-compatible** | Runs from source; not an official release target. |

✅ Verified = executed here · 🟡 Expected = strong evidence, not executed here.

---

## 2. Build & distribution

The CI workflow (`.github/workflows/build.yml`) builds standalone bundles on a matrix of
`macos-latest` and `windows-latest`, using PyInstaller via `playstation_studio.spec`:

- **macOS:** `PlayStation Studio.app` → zipped with `ditto` → `PlayStation-Studio-macOS.zip`.
- **Windows:** `PlayStation Studio/PlayStation Studio.exe` → `Compress-Archive` →
  `PlayStation-Studio-Windows.zip`.

Pushing a `v*` tag publishes a GitHub Release with both artifacts attached. The spec picks
the correct icon per OS (`app.icns` / `app.ico`) and the frozen build re-invokes its own
executable to run the MkPFS engine (no system Python required).

> **Architecture caveat (macOS):** the published `.app` matches the architecture of the
> GitHub macOS runner. Users on the other Mac architecture should build locally with
> `./build_app.sh` for a native bundle, or the project can add a second runner / universal2
> build in a future release.

---

## 3. Platform-specific code review

Cross-platform correctness was checked in the source. The code consistently uses
portable abstractions:

| Concern | Handling | Portable? |
| --- | --- | --- |
| Filesystem paths | `os.path`, `pathlib.Path`, `os.sep` everywhere; remote paths use `posixpath` | ✅ |
| Config / data dir | `Path.home() / ".playstation_studio"` | ✅ (Win/mac/Linux) |
| Atomic config write | temp file + `os.replace` | ✅ |
| Open data folder | `QDesktopServices.openUrl(QUrl.fromLocalFile(...))` | ✅ |
| Keyring backend | OS keyring via `keyring` (Keychain / Credential Manager), graceful fallback | ✅ |
| Menu roles | `QAction.QuitRole` / `AboutRole` (correct placement on macOS app menu) | ✅ |
| Quit shortcut | `QKeySequence.Quit` → `Cmd+Q` on macOS, `Ctrl+Q` on Windows | ✅ |
| Menu bar styling | Explicit `QMenuBar` stylesheet (notably for Windows' in-window bar) | ✅ |
| Networking | stdlib `socket`, `ftplib`, `http.server`, `urllib` | ✅ |
| Large files | 64-bit (`qlonglong`) progress signals for >2 GB transfers | ✅ |

No hardcoded POSIX-only paths, shell-outs to platform binaries, or `os.system` calls were
found in the application code.

---

## 4. Runtime requirements

- **From bundle:** none — Python, Qt and the engine are embedded.
- **From source:** Python **3.8+**, `PySide6-Essentials>=6.6`, `openpyxl>=3.1`; optional
  `keyring>=24`.

---

## 5. Recommendations

1. **Verify on a Windows 10/11 machine** before publishing — at minimum: launch, connect to
   an FTP server, run one upload/download, and confirm dialog rendering. (All app logic is
   portable, but a real smoke test closes the loop.)
2. **Verify on an Intel Mac** (or add a CI runner / universal2 build) if Intel users are a
   target audience.
3. Consider **code-signing** (and macOS **notarization**) so Gatekeeper / SmartScreen don't
   block first launch.

---

## 6. Conclusion

PlayStation Studio is built on a fully portable Python/Qt/stdlib stack with correct
platform-specific handling, and CI produces Windows and macOS bundles automatically.
**macOS (Apple Silicon) is verified.** Windows 10/11 and Intel macOS are
expected-compatible and built by CI, but a brief manual smoke test on those targets is
recommended before the public release is announced.
