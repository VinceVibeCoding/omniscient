import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";
import { defineConfig } from "vite";

const { version } = JSON.parse(readFileSync("package.json", "utf-8")) as { version: string };

// Tauri expects a fixed dev port and serves the built files from dist/.
// Two pages (paths relative to this folder, where `npm run build` runs): the OSD / panel (index.html) and its right-click menu (menu.html).
export default defineConfig({
  plugins: [react()],
  define: { __APP_VERSION__: JSON.stringify(version) },
  clearScreen: false,
  server: { port: 1420, strictPort: true },
  envPrefix: ["VITE_", "TAURI_ENV_"],
  build: {
    target: "es2022",
    outDir: "dist",
    sourcemap: false,
    rolldownOptions: {
      input: {
        main: "index.html",
        menu: "menu.html",
        highlight: "highlight.html",
      },
    },
  },
});
