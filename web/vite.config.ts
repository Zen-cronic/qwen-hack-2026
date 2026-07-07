import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies /api to the FastAPI backend; build emits static dist/ for
// nginx (prod) or the FastAPI StaticFiles mount (single-origin local run).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8099" },
  },
  build: { outDir: "dist" },
});
