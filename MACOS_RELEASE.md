# Zeph macOS Release

If people download Zeph from the web and macOS says it might be malware, the real fix is:

1. Sign the app with a valid Apple Developer ID certificate.
2. Notarize the app with Apple.
3. Staple the notarization ticket to the app.

Unsigned local builds will often trigger Gatekeeper warnings after download, even when the app is safe.

## What Zeph now includes

- `build_macos_app.sh`
  Builds the app bundle.
- `Zeph.entitlements`
  Entitlements used during hardened-runtime signing.
- `release_macos_notarized.sh`
  Builds, signs, notarizes, staples, and validates the app.

## What you need

- An active Apple Developer account
- A Developer ID Application certificate installed in your keychain
- An app-specific password for notarization

## Required environment variables

```bash
export APPLE_DEVELOPER_ID="Developer ID Application: Your Name (TEAMID)"
export APPLE_ID="you@example.com"
export APPLE_TEAM_ID="TEAMID"
export APPLE_APP_SPECIFIC_PASSWORD="xxxx-xxxx-xxxx-xxxx"
```

## Release command

```bash
cd /Users/kylefernandes/Desktop/Zeph
./release_macos_notarized.sh
```

## Publishing the newest version to the website

1. Update `/Users/kylefernandes/Desktop/Zeph/VERSION`
2. Run the notarized release build
3. Copy the new zip into the website downloads folder
4. Push to GitHub so Vercel redeploys

```bash
cd /Users/kylefernandes/Desktop/Zeph
./release_macos_notarized.sh
cp dist/Zeph.app.zip website/public/downloads/Zeph.app.zip
git add .
git commit -m "Release Zeph $(cat VERSION)"
git push
```

The website build writes `/downloads/latest-macos.json`, and the Zeph app uses that file to check for newer versions.

## Output

After a successful run, you will have:

- `dist/Zeph.app`
- `dist/Zeph.app.zip`

The zipped app is the one you should upload to your website.

## Important note

This workflow removes the normal Gatekeeper malware warning for downloaded builds only if the Apple signing and notarization steps succeed with your real Apple Developer credentials.
