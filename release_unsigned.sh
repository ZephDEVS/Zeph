#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
VERSION_FILE="$ROOT_DIR/VERSION"
DIST_APP="$ROOT_DIR/dist/Zeph.app"
DIST_ZIP="$ROOT_DIR/dist/Zeph.app.zip"
WEBSITE_ZIP="$ROOT_DIR/website/public/downloads/Zeph.app.zip"

usage() {
  cat <<'EOF'
Usage:
  ./release_unsigned.sh [version]

Examples:
  ./release_unsigned.sh
  ./release_unsigned.sh 1.1.1

What it does:
  1. Optionally updates VERSION
  2. Builds Zeph.app
  3. Creates dist/Zeph.app.zip
  4. Copies the zip to website/public/downloads/Zeph.app.zip
  5. Rebuilds the website so latest-macos.json is refreshed
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ -n "${1:-}" ]]; then
  print -- "$1" > "$VERSION_FILE"
  echo "Updated VERSION to $(cat "$VERSION_FILE")"
else
  echo "Using VERSION $(cat "$VERSION_FILE")"
fi

echo
echo "Building Zeph.app..."
"$ROOT_DIR/build_macos_app.sh"

echo
echo "Creating macOS zip..."
rm -f "$DIST_ZIP"
ditto -c -k --sequesterRsrc --keepParent "$DIST_APP" "$DIST_ZIP"

echo
echo "Copying zip into website downloads..."
cp "$DIST_ZIP" "$WEBSITE_ZIP"

echo
echo "Rebuilding website..."
cd "$ROOT_DIR/website"
npm run build

cd "$ROOT_DIR"

echo
echo "Unsigned release ready."
echo "App:        $DIST_APP"
echo "Zip:        $DIST_ZIP"
echo "Website zip:$WEBSITE_ZIP"
echo
echo "To publish it live, run:"
echo "  cd $ROOT_DIR"
echo "  git add ."
echo "  git commit -m \"Release Zeph $(cat "$VERSION_FILE")\""
echo "  git push"
