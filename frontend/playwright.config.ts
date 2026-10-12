import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests run against an already running stack:
 * API (uvicorn) + Celery worker + `vite preview`, with `python -m app.seed --reset`.
 * See docs/TEST_PLAN.md. No webServer block: the backend is not started from here.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:4173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
