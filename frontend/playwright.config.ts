import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests run against a running stack:
 *   backend:  uvicorn app.main:app --port 8000   (use a fresh database)
 *   frontend: npm run dev                         (http://localhost:5173)
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  workers: 1,
  fullyParallel: false,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:5173",
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
});
