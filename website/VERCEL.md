# Vercel Deploy Notes

Vercel can host static files larger than 10 MB. According to Vercel's limits docs, the static file upload limit is:

- Hobby: 100 MB
- Pro: 1 GB

Your current `Zeph.app.zip` is about 97 MB, so:

- It fits on Vercel Pro comfortably.
- It may fit on Vercel Hobby, but it is very close to the 100 MB ceiling, so deploys can be fragile once the rest of the site files are included.

Official references:

- https://vercel.com/docs/limits/overview

## Current setup

The site is configured with:

- `vercel.json` at the repo root
- a build step that can automatically package or copy `dist/Zeph.app.zip` into `website/public/downloads/Zeph.app.zip`

That means if you build Zeph locally first, then build the website locally, the download can be bundled directly into the Vercel deploy output.

## Recommended paths

### Best for reliability

Use an external download URL:

- set `VITE_MAC_DOWNLOAD_URL`

This avoids size-limit surprises.

### Best for simplicity

If you are on Vercel Pro, you can likely host the app zip directly in the site output.

## Local production build

1. Build the app bundle:
   - `/Users/kylefernandes/Desktop/Zeph/build_macos_app.sh`
2. Build the website:
   - `cd /Users/kylefernandes/Desktop/Zeph/website && npm run build`

The website prebuild script will copy or generate `website/public/downloads/Zeph.app.zip` from the local app bundle when possible.
