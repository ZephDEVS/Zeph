#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

if [ ! -x "$ROOT_DIR/.venv/bin/python" ]; then
  echo "Missing virtual environment at $ROOT_DIR/.venv"
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required to build the React frontend."
  exit 1
fi

echo "Building React frontend..."
cd "$ROOT_DIR/frontend"
npm install
npm run build

cd "$ROOT_DIR"

if ! "$ROOT_DIR/.venv/bin/python" -c "import PyInstaller" >/dev/null 2>&1; then
  echo "Installing PyInstaller into the virtual environment..."
  "$ROOT_DIR/.venv/bin/pip" install pyinstaller
fi

echo "Building Zeph.app..."
"$ROOT_DIR/.venv/bin/python" -m PyInstaller --noconfirm "$ROOT_DIR/Zeph.spec"

echo
echo "Build complete:"
echo "  $ROOT_DIR/dist/Zeph.app"
