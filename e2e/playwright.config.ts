import { defineConfig } from '@playwright/test'

// Runs against a running stack: `docker compose up -d --build` on an EMPTY database
// (the suite performs first-run setup through the UI, like a new shop owner would).
export default defineConfig({
  testDir: './tests',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: process.env.BASE_URL ?? 'http://localhost:5173',
    viewport: { width: 1280, height: 1000 },
    acceptDownloads: true,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  // The full Chromium (not the headless shell) has the PDF viewer, which the invoice test needs.
  projects: [{ name: 'chromium', use: { channel: 'chromium' } }],
})
