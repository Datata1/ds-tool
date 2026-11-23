import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

// Tauri expects a fixed port in dev; the Python API runs separately (see README).
export default defineConfig({
  plugins: [svelte()],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    // Browser dev without Tauri: proxy /api to `uv run ap-planner-server --port 8765 --no-token`
    proxy: { "/api": "http://127.0.0.1:8765" },
  },
  build: { target: "es2021", outDir: "dist" },
});
