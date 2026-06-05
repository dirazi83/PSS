#!/usr/bin/env bash
# Build a standalone PlayStation Studio app (no Python needed to run it).
set -euo pipefail
cd "$(dirname "$0")"

PY=.venv/bin/python
if [ ! -x "$PY" ]; then
  echo "Run ./run.sh once first to create the .venv" >&2
  exit 1
fi

echo "→ installing build tooling (PyInstaller)…"
"$PY" -m pip install --quiet --upgrade pyinstaller

echo "→ refreshing icons…"
"$PY" -m playstation_studio.assets.build_icons >/dev/null

echo "→ cleaning previous build output…"
chmod -R u+w build dist 2>/dev/null || true
rm -rf build dist

echo "→ building… (first run downloads/bundles Qt; takes a few minutes)"
"$PY" -m PyInstaller --noconfirm playstation_studio.spec

case "$(uname -s)" in
  Darwin) echo "✓ Done → dist/PlayStation Studio.app  (drag to /Applications)";;
  *)      echo "✓ Done → dist/PlayStation Studio/  (run the executable inside)";;
esac
