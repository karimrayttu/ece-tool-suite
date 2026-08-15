import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: the Electron main process loads http://localhost:5173.
// Prod: Electron loads dist/index.html over file://, so assets MUST use relative paths
// (base "./") — absolute "/assets/..." would resolve to the filesystem root and 404 (blank
// window). This is the setting that makes the packaged/native app actually render.
export default defineConfig({
  base: "./",
  plugins: [react()],
  server: { port: 5173, strictPort: true },
  build: { outDir: "dist" },
});
