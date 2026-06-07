"""Generate the PlayStation Studio icon set.

Authors a cohesive SVG for the app and each tab (a rounded "squircle" badge
with a per-app hue and a white glyph), then renders each to PNG at every size
needed for desktop and mobile/app-store use.

Run:  python -m playstation_studio.assets.build_icons
Re-runnable; overwrites assets/svg/*.svg and assets/icons/*.png.
"""

from __future__ import annotations

import os

HERE = os.path.dirname(os.path.abspath(__file__))
SVG_DIR = os.path.join(HERE, "svg")
ICON_DIR = os.path.join(HERE, "icons")
SIZES = [16, 24, 32, 48, 64, 128, 256, 512, 1024]

# Optional raster source for the *app* icon. When present, the app icon is
# rendered from this image instead of the generated SVG (the SVG stays as a
# fallback). Drop a square-ish PNG here to brand the app with custom artwork.
SOURCE_ICON = os.path.join(HERE, "source_icon.png")

# Per-icon hue (top → bottom gradient). Shared squircle + white glyph keep the
# set cohesive; the hue makes each tab instantly distinguishable.
PALETTE = {
    "app":     ("#818cf8", "#4338ca"),   # indigo (brand)
    "ps4":     ("#60a5fa", "#1d4ed8"),   # blue
    "ps5":     ("#a78bfa", "#6d28d9"),   # violet
    "payload": ("#22d3ee", "#0e7490"),   # cyan
    "ftp":     ("#34d399", "#047857"),   # emerald
}

# White glyphs, drawn inside a 512×512 viewBox, centered ~(256,256).
GLYPHS = {
    # brand: a faceted diamond emblem
    "app": """
      <path d="M256 104 L408 256 L256 408 L104 256 Z"
            fill="none" stroke="white" stroke-width="34" stroke-linejoin="round"/>
      <path d="M256 192 L320 256 L256 320 L192 256 Z" fill="white"/>
    """,
    # PKG manager: an archive / package box with a lid label
    "ps4": """
      <rect x="148" y="170" width="216" height="192" rx="26"
            fill="none" stroke="white" stroke-width="32"/>
      <line x1="148" y1="232" x2="364" y2="232" stroke="white" stroke-width="30"/>
      <rect x="222" y="170" width="68" height="62" rx="6" fill="white"/>
    """,
    # PFS compressor: two arrows pressing inward (compress)
    "ps5": """
      <path d="M150 256 L228 256 M198 222 L230 256 L198 290" fill="none"
            stroke="white" stroke-width="28" stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M362 256 L284 256 M314 222 L282 256 L314 290" fill="none"
            stroke="white" stroke-width="28" stroke-linecap="round" stroke-linejoin="round"/>
      <line x1="256" y1="196" x2="256" y2="316" stroke="white"
            stroke-width="22" stroke-linecap="round" stroke-opacity="0.55"/>
    """,
    # payload sender: a paper-plane "send" dart
    "payload": """
      <path d="M404 256 L116 138 L186 256 L116 374 Z" fill="white"/>
      <path d="M186 256 L404 256" stroke="white" stroke-width="0"/>
    """,
    # FTP client: up / down transfer arrows
    "ftp": """
      <path d="M198 360 L198 166 M166 202 L198 166 L230 202" fill="none"
            stroke="white" stroke-width="30" stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M314 152 L314 346 M282 310 L314 346 L346 310" fill="none"
            stroke="white" stroke-width="30" stroke-linecap="round" stroke-linejoin="round"/>
    """,
}

SVG_TEMPLATE = """<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{c1}"/>
      <stop offset="1" stop-color="{c2}"/>
    </linearGradient>
    <linearGradient id="sheen" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="white" stop-opacity="0.22"/>
      <stop offset="0.55" stop-color="white" stop-opacity="0"/>
    </linearGradient>
  </defs>
  <rect x="32" y="32" width="448" height="448" rx="112" fill="url(#bg)"/>
  <rect x="32" y="32" width="448" height="448" rx="112" fill="url(#sheen)"/>
  <rect x="33.5" y="33.5" width="445" height="445" rx="110"
        fill="none" stroke="white" stroke-opacity="0.18" stroke-width="3"/>
  {glyph}
</svg>
"""


def _extruded(letter, x, y, size, front, side, depth=16, font="Arial",
              dx=1.4, dy=1.4) -> str:
    """A bold letter with a faked 3-D extrusion (offset copies in *side*)."""
    common = (f'font-family="{font}" font-weight="900" font-size="{size}" '
              f'text-anchor="middle"')
    parts = [f'<text x="{x + k * dx:.1f}" y="{y + k * dy:.1f}" {common} '
             f'fill="{side}">{letter}</text>' for k in range(depth, 0, -1)]
    parts.append(f'<text x="{x}" y="{y}" {common} fill="{front}">{letter}</text>')
    return "\n".join(parts)


def build_app_svg() -> str:
    """App icon — homage to the classic PlayStation perspective logo, reading
    "SS" (PlayStation Studio).

    Like the original "PS" mark (an upright letter in front of one laid flat in
    perspective), but as two S's: an upright 3-D blue "S" in front, and a second
    "S" lying on the floor in perspective with a yellow face and red sides.
    """
    blue = "#2230b8"
    blue_side = "#101a6e"
    yellow = "#f6c512"
    red = "#d81f2a"
    # Second "S" lying on the floor: skewed + slightly flattened, set to the
    # right and back so it reads as the trailing letter.
    s_floor = (
        '<g transform="translate(330 378) skewX(-27) scale(1.26 1.0)">'
        + _extruded("S", 0, 0, 212, yellow, red, depth=15, dx=1.1, dy=1.4)
        + "</g>"
    )
    # Front "S" stands upright on the left, in brand blue with a deep extrude.
    s_front = (
        '<g transform="translate(186 322)">'
        + _extruded("S", 0, 0, 300, blue, blue_side, depth=20, dx=1.5, dy=1.5)
        + '<text x="0" y="0" font-family="Arial" font-weight="900" '
          f'font-size="300" text-anchor="middle" fill="{blue}">S</text>'
        + "</g>"
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#ffffff"/>
      <stop offset="1" stop-color="#eef0f6"/>
    </linearGradient>
  </defs>
  <rect x="32" y="32" width="448" height="448" rx="112" fill="url(#bg)"/>
  <rect x="33.5" y="33.5" width="445" height="445" rx="110"
        fill="none" stroke="#d4d7e0" stroke-width="3"/>
  {s_floor}
  {s_front}
</svg>
"""


def build_svgs() -> dict[str, str]:
    os.makedirs(SVG_DIR, exist_ok=True)
    out = {}
    for name, (c1, c2) in PALETTE.items():
        if name == "app":
            svg = build_app_svg()
        else:
            svg = SVG_TEMPLATE.format(c1=c1, c2=c2, glyph=GLYPHS[name].strip())
        path = os.path.join(SVG_DIR, f"{name}.svg")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(svg)
        out[name] = path
    return out


def render_pngs(svgs: dict[str, str]) -> int:
    import os as _os
    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    # QSvgRenderer needs a (Gui)Application to render <text> via the font DB.
    if QGuiApplication.instance() is None:
        QGuiApplication([])

    os.makedirs(ICON_DIR, exist_ok=True)
    count = 0
    for name, svg_path in svgs.items():
        renderer = QSvgRenderer(svg_path)
        for size in SIZES:
            img = QImage(size, size, QImage.Format_ARGB32)
            img.fill(Qt.transparent)
            painter = QPainter(img)
            renderer.render(painter)
            painter.end()
            img.save(os.path.join(ICON_DIR, f"{name}_{size}.png"))
            count += 1
    return count


def render_app_raster() -> int:
    """Render the app_*.png set from SOURCE_ICON (overwrites the SVG-rendered
    app icons). The source is centered on a square canvas (padded with its
    corner color, typically black) so non-square art isn't distorted.
    """
    from PIL import Image

    os.makedirs(ICON_DIR, exist_ok=True)
    img = Image.open(SOURCE_ICON).convert("RGBA")
    w, h = img.size
    side = max(w, h)
    bg = img.getpixel((0, 0))            # match the artwork's background corner
    if len(bg) == 3:
        bg = bg + (255,)
    canvas = Image.new("RGBA", (side, side), bg)
    canvas.paste(img, ((side - w) // 2, (side - h) // 2), img)
    count = 0
    for size in SIZES:
        canvas.resize((size, size), Image.LANCZOS).save(
            os.path.join(ICON_DIR, f"app_{size}.png"))
        count += 1
    return count


def write_app_ico() -> bool:
    """Write a multi-size Windows app.ico from the rendered app PNGs.

    Needs Pillow; skipped (with a note) if it isn't installed.
    """
    try:
        from PIL import Image
    except ImportError:
        print("note: Pillow not installed — skipping app.ico (pip install pillow)")
        return False
    sizes = [256, 128, 64, 48, 32, 24, 16]
    base = Image.open(os.path.join(ICON_DIR, "app_256.png")).convert("RGBA")
    base.save(os.path.join(HERE, "app.ico"), format="ICO",
              sizes=[(s, s) for s in sizes])
    return True


def write_app_icns() -> bool:
    """Write a macOS app.icns from the rendered app PNGs (macOS only).

    Uses the system `iconutil`; skipped (with a note) off macOS or if the tool
    isn't available. Without this, the .app would keep a stale icon since the
    build only refreshes app.ico.
    """
    import shutil
    import subprocess
    import sys
    import tempfile

    if sys.platform != "darwin" or shutil.which("iconutil") is None:
        print("note: not macOS / no iconutil — skipping app.icns")
        return False
    # iconutil expects an .iconset folder with specific @1x/@2x file names.
    iconset_map = {
        "icon_16x16.png": 16, "icon_16x16@2x.png": 32,
        "icon_32x32.png": 32, "icon_32x32@2x.png": 64,
        "icon_128x128.png": 128, "icon_128x128@2x.png": 256,
        "icon_256x256.png": 256, "icon_256x256@2x.png": 512,
        "icon_512x512.png": 512, "icon_512x512@2x.png": 1024,
    }
    with tempfile.TemporaryDirectory() as tmp:
        iconset = os.path.join(tmp, "app.iconset")
        os.makedirs(iconset, exist_ok=True)
        try:
            import shutil as _sh
            for fname, size in iconset_map.items():
                src = os.path.join(ICON_DIR, f"app_{size}.png")
                _sh.copyfile(src, os.path.join(iconset, fname))
            subprocess.run(
                ["iconutil", "-c", "icns", iconset,
                 "-o", os.path.join(HERE, "app.icns")],
                check=True, capture_output=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f"note: app.icns generation failed: {exc}")
            return False
    return True


def main() -> None:
    svgs = build_svgs()
    n = render_pngs(svgs)
    raster = ""
    if os.path.isfile(SOURCE_ICON):
        render_app_raster()              # app icon from the bundled raster source
        raster = "app icon from source_icon.png, "
    ico = "app.ico, " if write_app_ico() else ""
    icns = "app.icns, " if write_app_icns() else ""
    print(f"Wrote {len(svgs)} SVGs, {n} PNGs, {raster}{ico}{icns}"
          f"to {os.path.relpath(HERE)}")


if __name__ == "__main__":
    main()
