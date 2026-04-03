#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d ".venv" ]; then
  echo "Zeph virtual environment was not found in $SCRIPT_DIR/.venv"
  exit 1
fi

exec "$SCRIPT_DIR/.venv/bin/python" -m daia.main --gui
