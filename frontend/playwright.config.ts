import { defineConfig } from '@playwright/test'

// Relative to the config's directory (the project is ESM, so no __dirname).
const STORAGE_STATE = './e2e/.auth/user.json'
const PAYMENTS_STORAGE_STATE = './e2e/.auth/payments.json'
// The payments stack runs on its own ports so it can point at a throwaway
// database without disturbing whatever is already using :3000/:8000.
const PAYMENTS_URL = process.env.E2E_PAYMENTS_URL || 'http://localhost:3010'

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
      testIgnore: /(auth|payments)\.setup\.ts|payments\.spec\.ts/,
      dependencies: ['setup'],
      use: { storageState: STORAGE_STATE },
    },

    // Payments run against their own isolated stack and their own user, so they
    // get a separate login. Point at it with:
    //   E2E_BASE_URL=http://localhost:3010 npx playwright test --project=payments
    { name: 'payments-setup', testMatch: /payments\.setup\.ts/, use: { baseURL: PAYMENTS_URL } },
    {
      name: 'payments',
      testMatch: /payments\.spec\.ts/,
      dependencies: ['payments-setup'],
      use: { storageState: PAYMENTS_STORAGE_STATE, baseURL: PAYMENTS_URL },
    },
  ],
})
