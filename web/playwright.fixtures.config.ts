import { defineConfig } from "@playwright/test";

// Screenshot-only config for the real-video fixtures runtime. Must NOT wipe DATA_DIR — it
// replays the warm cache (scripts/warm_fixtures.py); also needs a live QWEN_API_KEY.
export default defineConfig({
  testDir: "./e2e-fixtures",
  timeout: 900_000,
  retries: 0,
  use: { baseURL: "http://127.0.0.1:8138", viewport: { width: 1280, height: 900 } },
  webServer: {
    command:
      "bash -c 'cd .. && DAILIES_FIXTURES=1 DATA_DIR=data SPA_DIST=web/dist .venv/bin/uvicorn server.app:create_production_app --factory --host 127.0.0.1 --port 8138'",
    url: "http://127.0.0.1:8138/api/packs",
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
