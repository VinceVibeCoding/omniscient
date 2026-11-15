// Assembles the unpacked extension in dist/: the manifest, the static page, the icons
// (shared with the Windows widget) and the compiled scripts.
import { cpSync, mkdirSync, readdirSync, rmSync } from "node:fs";

rmSync("dist", { recursive: true, force: true });
mkdirSync("dist/icons", { recursive: true });
cpSync("manifest.json", "dist/manifest.json");
for (const file of readdirSync("static")) cpSync(`static/${file}`, `dist/${file}`);
for (const size of ["32x32", "128x128"]) {
  cpSync(`../widget/src-tauri/icons/${size}.png`, `dist/icons/${size}.png`);
}
cpSync("build/src", "dist", { recursive: true });
console.log("extension built in dist/ (load it unpacked from chrome://extensions or edge://extensions)");
