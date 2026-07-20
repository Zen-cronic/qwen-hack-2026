import { defineConfig } from "@playwright/test";

// Drives the REAL demo runtime (DAILIES_DEMO=1) on synthetic clips. The cold DATA_DIR per
// run is load-bearing: a warm cache flattens the frontier chart the suite asserts on.
export default defineConfig({
  testDir: "./e2e",
  timeout: 180_000,
  retries: 0,
  use: { baseURL: "http://127.0.0.1:8137", viewport: { width: 1280, height: 900 } },
  webServer: {
    command:
      // CATALOG_ENABLED=0 so the suite never depends on the Postgres sidecar or on .env.
      "bash -c 'cd .. && rm -rf data/e2e && DAILIES_DEMO=1 CATALOG_ENABLED=0 DATA_DIR=data/e2e SPA_DIST=web/dist .venv/bin/uvicorn server.app:create_production_app --factory --host 127.0.0.1 --port 8137'",
    url: "http://127.0.0.1:8137/api/packs",
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
