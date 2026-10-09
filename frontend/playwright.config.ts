import { defineConfig } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const home = mkdtempSync(join(tmpdir(), "rates-e2e-"));
const port = 8791;

// End-to-end against the REAL Python server and engine (no mock): the server is started on a private port with a private history directory.
export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  workers: 1,
  use: { baseURL: `http://127.0.0.1:${port}`, viewport: { width: 1480, height: 900 } },
  webServer: {
    command: `npm run build && ../trainer ui --port ${port} --no-browser`,
    url: `http://127.0.0.1:${port}/api/health`,
    reuseExistingServer: false,
    env: { RATES_TRAINER_HOME: home },
    timeout: 120_000,
  },
});
