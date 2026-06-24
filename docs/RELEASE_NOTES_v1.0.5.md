# PlayStation Studio v1.0.5 — Release Notes

**Headline:** a new **Fluent left-navigation UI**, PS5 output-format choice + extraction, and
a README rewritten around features.

---

## 🧭 New Fluent UI

- The app now opens with a **Fluent left-navigation rail** listing every tool — **PKG Manager,
  PS5 Compressor, Payloads, FTP Client** — with **Check for Updates / Documentation / About**
  at the bottom.
- Dark Fluent theme with the app's indigo accent. The functional tools are unchanged; only the
  navigation/chrome is new.
- **Safe fallback:** if the Fluent library isn't available, the app automatically uses the
  classic tabbed shell, so it always runs.

## 🗜 PS5 Compressor

- **Output format selector** — Compressed PFS (`.ffpfsc`) or Uncompressed PFS (`.ffpfs`).
- **PFS extraction** — unpack any `.ffpfs` / `.ffpfsc` image back to a folder (batch + log).

## 🪟 Fixes & polish

- Fixed macOS text clipping in dropdowns/inputs (point/pixel font mismatch).
- Pack Settings grouped into **Output / Performance / Advanced** in a scroll area.

## 📖 Docs

- README rewritten around features, documenting each section (PKG Manager rename/export/remote
  install, compressor format/extract, payloads, FTP).

## 📄 License

- The app is now distributed under **GPLv3** because it bundles the GPLv3
  **PySide6-Fluent-Widgets** UI library.

## 💻 Downloads

- Windows 10/11 (x64): `PlayStation-Studio-Windows.zip`
- macOS (Apple Silicon): `PlayStation-Studio-macOS.zip`

Builds are unsigned — macOS right-click → **Open**; Windows **More info → Run anyway**.

> Note: bundling the Fluent UI pulls in full PySide6, so this build is larger than previous
> releases.

## 🙏 Credits

UI: **PySide6-Fluent-Widgets** by zhiyiYo. PS5 engine: **MkPFS 0.0.8** by PSBrew. PS4 install:
**Remote PKG Installer** by flatz. PS5 install: **etaHEN** DPI.
