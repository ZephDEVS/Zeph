import { copyFileSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { execFileSync } from "node:child_process";

const websiteRoot = resolve(import.meta.dirname, "..");
const projectRoot = resolve(websiteRoot, "..");
const publicDownloadsDir = resolve(websiteRoot, "public", "downloads");
const version = readFileSync(resolve(projectRoot, "VERSION"), "utf8").trim();
const targetZip = resolve(publicDownloadsDir, "Zeph.app.zip");
const builtZip = resolve(projectRoot, "dist", "Zeph.app.zip");
const builtApp = resolve(projectRoot, "dist", "Zeph.app");
const siteUrl = (process.env.ZEPH_WEBSITE_URL || process.env.VITE_SITE_URL || "https://zeph-lake.vercel.app").replace(/\/$/, "");

mkdirSync(publicDownloadsDir, { recursive: true });

if (existsSync(builtZip)) {
  copyFileSync(builtZip, targetZip);
  console.log(`Copied ${builtZip} -> ${targetZip}`);
} else if (existsSync(builtApp) && process.platform === "darwin") {
  rmSync(targetZip, { force: true });
  execFileSync("ditto", ["-c", "-k", "--sequesterRsrc", "--keepParent", builtApp, targetZip], {
    stdio: "inherit",
    cwd: dirname(builtApp),
  });
  console.log(`Archived ${builtApp} -> ${targetZip}`);
} else {
  if (existsSync(targetZip)) {
    console.log(`Keeping checked-in download asset at ${targetZip}`);
  } else {
    console.log("No local Zeph.app bundle found. Leaving download link to use configured external URL if provided.");
  }
}

const manifestPath = resolve(publicDownloadsDir, "latest-macos.json");
writeFileSync(
  manifestPath,
  JSON.stringify(
    {
      version,
      title: `Zeph ${version}`,
      summary: "Latest Zeph desktop release for macOS.",
      download_url: `${siteUrl}/downloads/Zeph.app.zip`,
      notes_url: `${siteUrl}/downloads/INSTALL.txt`,
      published_at: new Date().toISOString(),
    },
    null,
    2,
  ) + "\n",
  "utf8",
);
console.log(`Wrote update manifest to ${manifestPath}`);
