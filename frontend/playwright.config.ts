import { defineConfig } from '@playwright/test'

// Relative to the config's directory (the project is ESM, so no __dirname).
const STORAGE_STATE = './e2e/.auth/user.json'
const PAYMENTS_STORAGE_STATE = './e2e/.auth/payments.json'
// The payments stack runs on its own ports so it can point at a throwaway
// database without disturbing whatever is already using :3000/:8000.
const PAYMENTS_URL = process.env.E2E_PAYMENTS_URL || 'http://localhost:3010'
// "today" — a real-browser click-through pass for features built in this
// session (HR-to-10, messaging, payment engine, integrations marketplace).
// Same isolated-stack pattern as `payments`: its own throwaway-DB-backed dev
// server on its own ports (:5183/:8010 rather than :3000/:8000), its own
// login/user, own storage state.
const TODAY_STORAGE_STATE = './e2e/.auth/today.json'
const TODAY_URL = process.env.E2E_TODAY_URL || 'http://localhost:5183'
// Bank Reconciliation click-through — runs against whichever stack you point it
// at (a throwaway-DB dev server locally, or a deployed environment).
const RECON_URL = process.env.E2E_RECON_URL || 'http://127.0.0.1:5183'
// POS receipt click-through — same isolated-stack pattern as bank-recon.
const RECEIPTS_URL = process.env.E2E_RECEIPTS_URL || 'http://127.0.0.1:5183'

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

    // Today's-session click-through: its own throwaway stack, own login.
    //   E2E_TODAY_URL=http://localhost:5183 npx playwright test --project=today
    { name: 'today-setup', testMatch: /today\.setup\.ts/, use: { baseURL: TODAY_URL } },
    {
      name: 'today',
      testMatch: /today\..*\.spec\.ts/,
      dependencies: ['today-setup'],
      use: { storageState: TODAY_STORAGE_STATE, baseURL: TODAY_URL },
    },

    // Bank Reconciliation click-through. Same isolated-stack pattern: point it at
    // a throwaway-DB-backed dev server and give it that stack's own login. The
    // spec signs in itself (serial, one login per file) rather than depending on
    // a shared storage state, so it can be run against any environment:
    //   E2E_RECON_URL=http://127.0.0.1:5183 \
    //   E2E_RECON_EMAIL=... E2E_RECON_PASSWORD=... \
    //   npx playwright test --project=bank-recon
    {
      name: 'bank-recon',
      testMatch: /bank-reconciliation\.spec\.ts/,
      use: { baseURL: RECON_URL },
    },

    // POS receipt click-through. Same self-signing, point-anywhere pattern as
    // bank-recon:
    //   E2E_RECEIPTS_URL=http://127.0.0.1:5183
    //   E2E_RECEIPTS_EMAIL=<email>  E2E_RECEIPTS_PASSWORD=<password>
    //   npx playwright test --project=receipts
    {
      name: 'receipts',
      testMatch: /receipts\.spec\.ts/,
      use: { baseURL: RECEIPTS_URL },
    },
  ],
})
