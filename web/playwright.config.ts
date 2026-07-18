import { defineConfig } from "@playwright/test";

// The e2e drives the REAL demo runtime (DAILIES_DEMO=1): the genuine pipeline thread,
// real Tier-A CV and real ffmpeg on synthetic clips, zero video quota. A cold DATA_DIR
// per run keeps the cost axis honest — cached replays cost 0, and a warm cache would
// flatten the frontier chart the suite asserts on.
export default defineConfig({
  testDir: "./e2e",
  timeout: 180_000,
  retries: 0,
  use: { baseURL: "http://127.0.0.1:8137", viewport: { width: 1280, height: 900 } },
  webServer: {
    command:
      "bash -c 'cd .. && rm -rf data/e2e && DAILIES_DEMO=1 DATA_DIR=data/e2e SPA_DIST=web/dist .venv/bin/uvicorn server.app:create_production_app --factory --host 127.0.0.1 --port 8137'",
    url: "http://127.0.0.1:8137/api/packs",
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
