import { defineConfig, devices } from "@playwright/test";
import os from "node:os";
import path from "node:path";

// The suite runs its own backend so it never touches var/, real email or a real model:
// a fresh SQLite db each run, LLM_PROVIDER=fake, EMAIL_PROVIDER=file.
const API_PORT = 8100;
const WEB_PORT = 5180;
const DATA_DIR = path.join(os.tmpdir(), "request-runner-e2e");

export default defineConfig({
  testDir: "e2e",
  // one shared backend with a global demo clock: run in order
  workers: 1,
  fullyParallel: false,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `rm -rf "${DATA_DIR}" && uv run rr seed && uv run uvicorn app.main:app --port ${API_PORT}`,
      cwd: "../backend",
      url: `http://localhost:${API_PORT}/healthz`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        APP_ENV: "development",
        DATA_DIR,
        DATABASE_URL: "",
        APP_BASE_URL: `http://localhost:${WEB_PORT}`,
        LLM_PROVIDER: "fake",
        EMAIL_PROVIDER: "file",
        OPENAI_API_KEY: "",
        ANTHROPIC_API_KEY: "",
        GMAIL_ADDRESS: "",
        GMAIL_APP_PASSWORD: "",
        SEED_USERS: "",
      },
    },
    {
      command: `npx vite --port ${WEB_PORT} --strictPort`,
      url: `http://localhost:${WEB_PORT}`,
      reuseExistingServer: false,
      env: { BACKEND_URL: `http://localhost:${API_PORT}` },
    },
  ],
});
