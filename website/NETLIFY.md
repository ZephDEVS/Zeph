# Netlify Deploy Notes

This site is ready to deploy on Netlify.

## Build settings

- Base directory: `website`
- Build command: `npm install && npm run build`
- Publish directory: `dist`

These settings are also defined in `/Users/kylefernandes/Desktop/Zeph/netlify.toml`.

## Download asset

Do not ship the macOS app zip inside the Netlify deploy bundle. The current app archive is large, and Netlify's docs note that files over 10 MB are not well-supported by the CDN.

Host `Zeph.app.zip` somewhere else, such as:

- GitHub Releases
- Amazon S3
- Cloudflare R2
- another file host or CDN you control

Then set this environment variable in Netlify:

- `VITE_MAC_DOWNLOAD_URL`

Optional:

- `VITE_INSTALL_NOTES_URL`

## Suggested environment values

- `VITE_MAC_DOWNLOAD_URL=https://your-host.example.com/Zeph.app.zip`
- `VITE_INSTALL_NOTES_URL=https://your-site.example.com/downloads/INSTALL.txt`

## Netlify references

- Deploy overview: https://docs.netlify.com/deploy/deploy-overview
- Redirects and rewrites: https://docs.netlify.com/routing/redirects/
- Build troubleshooting: https://docs.netlify.com/build/configure-builds/troubleshooting-tips/
