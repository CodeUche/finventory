import { defineConfig } from '@playwright/test'

/**
 * HR module E2E, run against an isolated stack so it never touches the dev
 * database or the ports a developer already has running:
 *
 *   docker exec finventory-db-1 psql -U finv_app -d postgres \
 *     -c "CREATE DATABASE finventory_hrtest OWNER finv_app;"
 *   DB_NAME=finventory_hrtest python manage.py migrate
 *   DB_NAME=finventory_hrtest python seed_hr_e2e.py
 *   DB_NAME=finventory_hrtest python manage.py runserver 8011 --noreload
 *   VITE_PROXY_TARGET=http://localhost:8011 npx vite --port 3011
 *   npx playwright test --config playwright.hr.config.ts
 *
 * Login is throttled at 20/minute per IP, so each persona signs in once in the
 * setup project and every spec reuses the saved session.
 */
const OWNER_STATE = './e2e/.auth/hr-owner.json'
const EMPLOYEE_STATE = './e2e/.auth/hr-employee.json'

export default defineConfig({
  testDir: './e2e',
  timeout: 120_000,
  expect: { timeout: 25_000 },
  retries: 0,
  workers: 1,
  reporter: [['line']],
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://localhost:3011',
    headless: true,
    actionTimeout: 25_000,
    navigationTimeout: 60_000,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'hr-setup', testMatch: /hr\.setup\.ts/ },
    {
      name: 'hr-operator',
      testMatch: /hr\.spec\.ts/,
      dependencies: ['hr-setup'],
      use: { storageState: OWNER_STATE },
    },
    {
      name: 'hr-ess',
      testMatch: /hr\.ess\.spec\.ts/,
      dependencies: ['hr-setup'],
      use: { storageState: EMPLOYEE_STATE },
    },
  ],
})
