#!/usr/bin/env bash
# Launch PFS Studio using the project virtual environment.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  echo "Creating virtual environment…"
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
  .venv/bin/python -m pip install ./MkPFS
fi

exec .venv/bin/python -m playstation_studio "$@"
