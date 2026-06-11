# PlayStation Studio v1.0.1 — Release Notes

**Date:** 2026-06-11 · **Headline:** updated PS5 compression engine to **MkPFS 0.0.8**.

This release upgrades the bundled PS5 PFS compression engine from MkPFS 0.0.5 to
**0.0.8**, pulling in several important upstream fixes and performance gains, and surfaces
the engine version inside the app.

---

## 🧩 MkPFS engine: 0.0.5 → 0.0.8

Highlights from the upstream MkPFS releases now bundled:

- **Fixes corrupted PFS images on large game folders** (0.0.7) — wrong inode mapping after
  `flat_path_table` collisions. This is the most important fix; it affects big dumps with
  thousands of files (e.g. Minecraft).
- **Streaming pack by default** (0.0.8) — packs directly to the image with far less
  temporary-disk usage; helpful when working off a near-full disk or a network share.
- **Faster post-pack verification** (0.0.8).
- **Better special-character / non-ASCII filename handling** (0.0.6–0.0.8), including
  automatic inner-image renaming.
- **More stability on remote/network volumes**, with clearer warnings.
- Skips compression for executables and very small files where it doesn't help.

Verified end-to-end on a real 22,328-file Minecraft dump with this build's exact pack
command: **0 errors, 0 warnings**, and notably faster than 0.0.5 (~16 s vs ~27 s).

> Note: MkPFS 0.0.8 also advises that some consoles can misread *compressed* PFS images. If
> a compressed image doesn't mount, try packing with PFSC compression off.

## ✨ Improvements

- **Bundled engine version is shown in the app** — the PS5 tab footer and the About box now
  read "MkPFS 0.0.8 by PSBrew", so you always know which engine you're running.

## ↩️ Also included since 1.0.0

- No more UI freezing: async game scanning in the compressor and non-blocking FTP folder
  drops.
- Windows: output filenames are sanitised (titles with `:` etc. no longer fail the pack).
- Antivirus / SmartScreen false-positive mitigations (version resource, no UPX) + published
  SHA-256 checksums.
- ShadowMountPlus-compatible pack option, and Compress All / Compress Selected.

## 💻 Downloads

- Windows 10/11 (x64): `PlayStation-Studio-Windows.zip`
- macOS (Apple Silicon): `PlayStation-Studio-macOS.zip`
- `SHA256SUMS.txt` — verify your download

Builds are unsigned — on macOS right-click → **Open**; on Windows **More info → Run
anyway**. If your browser/AV flags the download, see the README ("download blocked" section).

## 🙏 Credits

PS5 compression engine: **MkPFS 0.0.8** by **PSBrew**. Inspired by **PS5-FFPFSC-PRO** by
**KINGDKAK**. PS5 install via **etaHEN** DPI. Output is **ShadowMountPlus**-compatible.
