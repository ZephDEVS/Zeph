#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_PATH="$ROOT_DIR/dist/Zeph.app"
ZIP_PATH="$ROOT_DIR/dist/Zeph.app.zip"
ENTITLEMENTS_PATH="$ROOT_DIR/Zeph.entitlements"

required_vars=(
  APPLE_DEVELOPER_ID
  APPLE_ID
  APPLE_TEAM_ID
  APPLE_APP_SPECIFIC_PASSWORD
)

for var_name in "${required_vars[@]}"; do
  if [ -z "${(P)var_name:-}" ]; then
    echo "Missing required environment variable: $var_name"
    exit 1
  fi
done

if ! command -v xcrun >/dev/null 2>&1; then
  echo "xcrun is required to notarize Zeph."
  exit 1
fi

"$ROOT_DIR/build_macos_app.sh"

echo "Signing Zeph.app with Developer ID..."
codesign \
  --force \
  --deep \
  --options runtime \
  --timestamp \
  --entitlements "$ENTITLEMENTS_PATH" \
  --sign "$APPLE_DEVELOPER_ID" \
  "$APP_PATH"

echo "Creating notarization archive..."
rm -f "$ZIP_PATH"
ditto -c -k --sequesterRsrc --keepParent "$APP_PATH" "$ZIP_PATH"

echo "Submitting for notarization..."
xcrun notarytool submit "$ZIP_PATH" \
  --apple-id "$APPLE_ID" \
  --team-id "$APPLE_TEAM_ID" \
  --password "$APPLE_APP_SPECIFIC_PASSWORD" \
  --wait

echo "Stapling notarization ticket..."
xcrun stapler staple "$APP_PATH"

echo "Validating Gatekeeper acceptance..."
spctl --assess --type execute -vv "$APP_PATH"

echo
echo "Signed and notarized app ready:"
echo "  $APP_PATH"
echo "  $ZIP_PATH"
