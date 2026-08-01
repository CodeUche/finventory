import { test, expect, type Page } from '@playwright/test'

/**
 * HR module — operator surfaces.
 *
 * Runs with the owner's saved session (see hr.setup.ts) against a throwaway
 * database seeded by backend/seed_hr_e2e.py. Serial by design: the backend
 * throttles a user at 1000 requests/hour and an exhausted throttle degrades the
 * app silently, which looks exactly like a permissions bug.
 */
test.describe.configure({ mode: 'serial' })

/** Sidebar groups start collapsed unless they hold the active route. */
async function openHrGroup(page: Page) {
  const sidebar = page.locator('aside, nav').first()
  await expect(sidebar.getByText('ACCOUNTING & FINANCE', { exact: true }))
    .toBeVisible({ timeout: 45_000 })
  await sidebar.getByText('HR', { exact: true }).click()
  return sidebar
}

test('the sidebar HR group carries all five entries', async ({ page }) => {
  await page.goto('/dashboard')
  const sidebar = await openHrGroup(page)
  for (const item of ['Employees', 'Org Chart', 'Leave', 'Payroll Runs', 'Compliance & Remittances']) {
    await expect(sidebar.getByRole('link', { name: item })).toBeVisible()
  }
})

test('HR nav items route to the new /hr paths', async ({ page }) => {
  await page.goto('/dashboard')
  const sidebar = await openHrGroup(page)
  await sidebar.getByRole('link', { name: 'Leave' }).click()
  await expect(page).toHaveURL(/\/hr\/leave/)
})

test('the old /payroll URLs redirect to /hr', async ({ page }) => {
  await page.goto('/payroll/employees')
  await expect(page).toHaveURL(/\/hr\/employees/)
  await page.goto('/payroll/runs')
  await expect(page).toHaveURL(/\/hr\/runs/)
})

test('the employee list includes the leaver', async ({ page }) => {
  await page.goto('/hr/employees')
  await expect(page.getByText('Ada Okonkwo').first()).toBeVisible({ timeout: 45_000 })
  // The old engine dropped anyone with a termination_date; she must still be here.
  await expect(page.getByText('Bola Eze').first()).toBeVisible()
})

test('the org chart nests reports under their manager', async ({ page }) => {
  await page.goto('/hr/org-chart')
  await expect(page.getByRole('heading', { name: /org chart/i })).toBeVisible({ timeout: 45_000 })
  await expect(page.getByText('Chidi Bello').first()).toBeVisible()
  await expect(page.getByText('Ada Okonkwo').first()).toBeVisible()
  // Ada manages two people, so her node advertises its reports.
  await expect(page.getByText(/2 reports/).first()).toBeVisible()
})

test('the payroll run shows proration and per-state PAYE routing', async ({ page }) => {
  await page.goto('/hr/runs')
  await expect(page.getByText('PAY-2026-06-R1').first()).toBeVisible({ timeout: 45_000 })
  await page.getByRole('button', { name: /show payslips for PAY-2026-06-R1/i }).click()

  // Mid-month joiner
  await expect(page.getByText('Tunde Danjuma').first()).toBeVisible({ timeout: 25_000 })
  // PAYE routed to the employee's State IRS
  await expect(page.getByText(/Lagos/).first()).toBeVisible()
  // The employee with no state of residence is flagged, never silently grouped
  await expect(page.getByText('Unassigned').first()).toBeVisible()
})

test('a run offers off-cycle and 13th-month types', async ({ page }) => {
  await page.goto('/hr/runs')
  await expect(page.getByText('PAY-2026-06-R1').first()).toBeVisible({ timeout: 45_000 })
  const runTypeSelect = page.getByLabel('Run type')
  await expect(runTypeSelect).toBeVisible()
  const options = (await runTypeSelect.locator('option').allTextContents()).join('|')
  expect(options).toContain('Off-cycle')
  expect(options).toContain('13th month')
})

test('the compliance cockpit splits obligations per authority', async ({ page }) => {
  await page.goto('/hr/compliance')
  await expect(page.getByRole('heading', { name: /statutory/i })).toBeVisible({ timeout: 45_000 })

  // The obligations table loads after the heading; wait for a row before
  // counting, since locator.count() does not auto-wait.
  await expect(page.getByText('ARM Pension').first()).toBeVisible({ timeout: 30_000 })

  // PAYE split across several State IRSs — impossible before this release
  const payeRows = page.locator('tbody tr', { hasText: 'PAYE' })
  expect(await payeRows.count()).toBeGreaterThan(1)

  // Pension split per PFA
  await expect(page.getByText('Stanbic IBTC').first()).toBeVisible()

  // ITF auto-asserted once headcount reached five
  await expect(page.getByText(/Industrial Training Fund/).first()).toBeVisible()

  // The benefit premium rides the same remittance pipeline
  await expect(page.getByText('Hygeia HMO').first()).toBeVisible()

  // The liability reconciles to the ledger
  await expect(page.getByText(/matches outstanding/i)).toBeVisible()
})

test('the pension schedule groups by PFA', async ({ page }) => {
  await page.goto('/hr/compliance')
  await expect(page.getByRole('heading', { name: /statutory/i })).toBeVisible({ timeout: 45_000 })
  await page.getByRole('button', { name: /pension \(per pfa\)/i }).click()
  await expect(page.getByText(/pension filing schedule/i)).toBeVisible({ timeout: 25_000 })
  await expect(page.getByText('ARM Pension').first()).toBeVisible()
  await expect(page.getByText('Stanbic IBTC').first()).toBeVisible()
})

test('leave policies seed the Nigerian statutory defaults', async ({ page }) => {
  await page.goto('/hr/leave')
  await expect(page.getByRole('heading', { name: /^leave$/i })).toBeVisible({ timeout: 45_000 })
  await page.getByRole('button', { name: /^Policies$/ }).click()
  await expect(page.getByText('Annual Leave').first()).toBeVisible({ timeout: 25_000 })
  await expect(page.getByText('Maternity Leave').first()).toBeVisible()
  await expect(page.getByText('Unpaid Leave').first()).toBeVisible()
})

test('recording unpaid leave states its payroll consequence', async ({ page }) => {
  await page.goto('/hr/leave')
  await expect(page.getByRole('heading', { name: /^leave$/i })).toBeVisible({ timeout: 45_000 })

  await page.getByRole('button', { name: /record leave/i }).click()
  const dialog = page.locator('form').filter({ hasText: 'Record leave' })
  await expect(dialog).toBeVisible({ timeout: 20_000 })

  // Option labels carry suffixes (employee id, "(unpaid)"), so resolve the
  // value rather than matching on exact label text.
  const pick = async (select: ReturnType<typeof dialog.locator>, contains: string) => {
    const value = await select.locator('option', { hasText: contains }).first().getAttribute('value')
    expect(value, `no option containing "${contains}"`).toBeTruthy()
    await select.selectOption(value!)
  }

  await pick(dialog.locator('select').first(), 'Ada Okonkwo')
  // Pick the unpaid type so the naira consequence is asserted, not just implied.
  await pick(dialog.locator('select').nth(1), 'Unpaid Leave')

  // The form states up front that this will be deducted
  await expect(dialog.getByText(/will be deducted/i)).toBeVisible()

  await dialog.getByRole('button', { name: /record leave/i }).click()

  // It lands in the queue with the deduction shown against it
  await expect(page.getByText(/deduction/i).first()).toBeVisible({ timeout: 25_000 })
})
