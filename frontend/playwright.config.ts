import { defineConfig } from '@playwright/test'

// Relative to the config's directory (the project is ESM, so no __dirname).
const STORAGE_STATE = './e2e/.auth/user.json'

// Browser E2E against the running dev app (Vite :3000 proxies /api → Django :8000).
export default defineConfig({
  testDir: './e2e',
  timeout: 90_000,
  expect: { timeout: 20_000 },
  retries: 0,
  workers: 1,
  reporter: [['line']],
  use: {
    baseURL: 'http://localhost:3000',
    headless: true,
    actionTimeout: 20_000,
    navigationTimeout: 45_000,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  projects: [
    // Logs in once and saves the session. The backend throttles login at
    // 20/min per IP, so a per-spec form login rate-limits a full-suite run
    // and surfaces as misleading "element not found" failures.
    { name: 'setup', testMatch: /auth\.setup\.ts/ },
    {
      name: 'e2e',
      testIgnore: /auth\.setup\.ts/,
      dependencies: ['setup'],
      use: { storageState: STORAGE_STATE },
    },
  ],
})
