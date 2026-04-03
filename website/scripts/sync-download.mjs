import { copyFileSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { execFileSync } from "node:child_process";

const websiteRoot = resolve(import.meta.dirname, "..");
const projectRoot = resolve(websiteRoot, "..");
const publicDownloadsDir = resolve(websiteRoot, "public", "downloads");
const targetZip = resolve(publicDownloadsDir, "Zeph.app.zip");
const builtZip = resolve(projectRoot, "dist", "Zeph.app.zip");
const builtApp = resolve(projectRoot, "dist", "Zeph.app");

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
  rmSync(targetZip, { force: true });
  console.log("No local Zeph.app bundle found. Leaving download link to use configured external URL if provided.");
}
