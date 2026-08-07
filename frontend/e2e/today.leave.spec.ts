import { test, expect, Page } from '@playwright/test'

/**
 * Real-browser click-through of the leave warn-and-allow flow (HR-to-10
 * flagship feature) built earlier today.
 *
 * LeavePage (src/pages/payroll/LeavePage.tsx) never hard-blocks an
 * overbooking on the HR-facing "Record leave" form — it flags it via the
 * app's custom confirmDialog/promptDialog (never a native window.confirm)
 * and, when the request would cross the balance into negative territory,
 * requires a mandatory reason (submitRequest's "Tier 2" branch). Ada Eze
 * (a10343ac-c491-43e8-acf8-62e1245be522) was seeded with an "Annual Leave"
 * balance of 2 available days in Browser Test Org so that a multi-week
 * request reliably crosses into negative, landing on the mandatory-reason
 * branch rather than the soft-warn branch.
 *
 * DateInput (src/components/DateInput.tsx) renders a visible DD/MM/YYYY text
 * field, not a native <input type="date"> — only a hidden sr-only date input
 * backs the calendar-icon popup. Fill the visible text field directly.
 */
test.describe.configure({ mode: 'serial' })

const EMPLOYEE_ID = 'a10343ac-c491-43e8-acf8-62e1245be522'
const ORG_ID = '550dece5-ee58-4e6b-a9f7-7f7701af5c99'

// This throwaway DB persists between local runs of this spec — nothing
// resets LeaveRequest/LeaveBalance rows automatically. Left-behind pending
// requests from a prior run silently eat into Ada Eze's balance (confirmed
// live: repeated runs drove `available_days` to -9), which then makes the
// "within accrued balance" test's own request ALSO overbook — a real,
// reproducible flake, not a product bug. Cancel any pending requests for
// this employee before the suite runs so every run starts from the same
// clean 2-day balance the seed data establishes.
test.beforeAll(async ({ request, baseURL }) => {
  const loginRes = await request.post(`${baseURL}/api/v1/auth/login/`, {
    data: { email: 'browsertest@audity.local', password: 'BrowserTest123!' },
  })
  const { access } = await loginRes.json()
  const headers = { Authorization: `Bearer ${access}`, 'X-Organisation-ID': ORG_ID }

  const listRes = await request.get(
    `${baseURL}/api/v1/payroll/leave-requests/?org=${ORG_ID}&status=pending`,
    { headers },
  )
  const body = await listRes.json()
  const pending: { id: string; employee: string }[] = Array.isArray(body) ? body : body.results ?? []
  for (const req of pending.filter((r) => r.employee === EMPLOYEE_ID)) {
    await request.post(
      `${baseURL}/api/v1/payroll/leave-requests/${req.id}/cancel/?org=${ORG_ID}`,
      { headers },
    )
  }
})

async function openRecordLeaveForm(page: Page) {
  await page.goto('/hr/leave')
  await expect(page.getByRole('heading', { name: 'Leave' })).toBeVisible({ timeout: 45_000 })
  await page.getByRole('button', { name: /Record leave/ }).click()
  await expect(page.getByRole('heading', { name: 'Record leave' })).toBeVisible()
}

// LeavePage's <label> elements have no htmlFor/id association with their
// inputs (verified by reading src/pages/payroll/LeavePage.tsx), so
// getByLabel() cannot be used — select by the field's wrapping container
// (the label's own parent <div>) instead. selectOption's {label} matcher only
// accepts exact strings, not regexes, so resolve the real option text first.
//
// exact:true text matching is against the WHOLE element's normalized
// textContent, not just its direct text node — the "Leave type" label wraps
// a FieldTooltip whose (visually hidden but DOM-present) tooltip text gets
// concatenated in, so an exact match on "Leave type" alone never matches.
// Match on a text *prefix* instead (^Leave type/^Employee), which is safe
// against the tooltip suffix.
async function selectByFieldLabel(page: Page, label: string, optionTextMatch: RegExp) {
  const field = page.locator('form div', { has: page.getByText(new RegExp(`^${label}`)) }).first()
  const select = field.locator('select')
  // The modal opens synchronously with the button click, but its <option>s
  // populate only once LeavePage's employees/leave-types fetch (fired on
  // page load, in-flight when the form opens) resolves — reading options
  // immediately after open is a real race, not just theoretical: it failed
  // consistently in practice. Wait for the matching option to actually exist.
  const optionLocator = select.locator('option', { hasText: optionTextMatch })
  await expect(optionLocator.first()).toBeAttached({ timeout: 15_000 })
  const optionTexts = await select.locator('option').allTextContents()
  const match = optionTexts.find((t) => optionTextMatch.test(t))
  if (!match) throw new Error(`No <option> under "${label}" matched ${optionTextMatch}. Options: ${optionTexts.join(' | ')}`)
  // selectOption's single-object form is ambiguous across Playwright
  // versions when passed a bare {label} — the array form is unambiguous.
  await select.selectOption([{ label: match }])
}

async function fillDate(page: Page, label: string, iso: string) {
  const [, y, m, d] = iso.match(/^(\d{4})-(\d{2})-(\d{2})$/)!
  const display = `${d}/${m}/${y}`
  // Start date / End date sit side-by-side in a shared `grid grid-cols-2`
  // wrapper — `form div` with `has: <label text>` also matches that shared
  // grid ancestor (which contains BOTH date inputs), not just the specific
  // field's own div, so `.first()` alone is ambiguous. Scope to the div
  // whose DIRECT child is the matching label to land on the exact field.
  const field = page.locator('form > div, form div > div').filter({
    has: page.locator('> label', { hasText: label }),
  }).first()
  await field.locator('input[type="text"]').fill(display)
}

function nextMonday(): Date {
  const d = new Date()
  d.setDate(d.getDate() + ((8 - d.getDay()) % 7 || 7))
  return d
}

function isoDate(d: Date): string {
  return d.toISOString().split('T')[0]
}

// Order matters: both tests share the same seeded employee/balance in a
// serial describe block, and the second test below deliberately overbooks
// (crossing the balance negative). Run the within-balance case FIRST, while
// the balance is still the clean seeded 2 days — running it after the
// overbooking test would make its own request overbook too (the balance
// stays negative from the prior test), which is a shared-fixture ordering
// concern, not a re-test of the same product behaviour.
//
// The two tests must also book NON-OVERLAPPING date ranges: LeaveRequest
// has a real (and correct) server-side overlap guard per employee — see
// LeaveRequestSerializer.validate in apps/payroll/serializers.py — that
// rejects a second request whose [start,end] intersects an existing
// pending/approved one for the same employee with a 400. Confirmed live:
// both tests defaulting to "next Monday" collided and 400'd. Test 1 books
// a single day next Monday; test 2 starts three weeks later so its whole
// 9-working-day span never touches test 1's date.
test('a request within the accrued balance does not trigger any overbooking warning', async ({ page }) => {
  await openRecordLeaveForm(page)

  await selectByFieldLabel(page, 'Employee', /Ada Eze/)
  await selectByFieldLabel(page, 'Leave type', /Annual Leave/)

  // A single working day is well inside the freshly seeded 2-day balance.
  const monday = nextMonday()
  await fillDate(page, 'Start date', isoDate(monday))
  await fillDate(page, 'End date', isoDate(monday))

  await page.locator('form').getByRole('button', { name: 'Record leave' }).click()

  // No overbooking dialog should appear — straight to the success toast.
  await expect(page.getByText(/Leave request recorded/i)).toBeVisible({ timeout: 20_000 })
  await expect(page.getByRole('heading', { name: /Overbooking/i })).toHaveCount(0)
})

test('submitting more leave than accrued triggers the overbooking warning, not a silent block or silent allow', async ({ page }) => {
  await openRecordLeaveForm(page)

  await selectByFieldLabel(page, 'Employee', /Ada Eze/)
  await selectByFieldLabel(page, 'Leave type', /Annual Leave/)

  // Starts 3 weeks after test 1's single-day booking so the two date ranges
  // never overlap (see the file-level comment above) — this is a fresh,
  // unrelated request, not a continuation of test 1's.
  const monday = nextMonday()
  monday.setDate(monday.getDate() + 21)
  const wellBeyond = new Date(monday)
  wellBeyond.setDate(wellBeyond.getDate() + 11) // ~9 working days, well past the remaining balance
  await fillDate(page, 'Start date', isoDate(monday))
  await fillDate(page, 'End date', isoDate(wellBeyond))

  // The working-days preview must reflect the real (non-zero) span before we
  // rely on it crossing the balance.
  await expect(page.getByText(/working day\(s\) — weekends excluded/)).toBeVisible()

  await page.locator('form').getByRole('button', { name: 'Record leave' }).click()

  // Tier 2 (crosses into negative balance): a mandatory-reason prompt, not a
  // silent 400 and not a silent success.
  const dialogHeading = page.getByRole('heading', { name: /Overbooking requires a reason/i })
  await expect(dialogHeading).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText(/negative/i)).toBeVisible()

  // Confirming with no reason must not proceed — optional:false blocks it.
  await page.getByRole('dialog').getByRole('button', { name: /^Save$/ }).click()
  await expect(dialogHeading).toBeVisible()

  // A reason lets it through. Scope to the dialog (role="dialog" — see
  // src/lib/dialog.tsx) specifically: the Record-leave form behind it has
  // its OWN "Reason" input with the same "input" class, so an unscoped
  // locator can silently fill/submit the wrong field.
  const promptDialogEl = page.getByRole('dialog')
  await promptDialogEl.locator('input.input, textarea.input').fill('Approved in advance by the owner — urgent family matter.')
  await promptDialogEl.getByRole('button', { name: /^Save$/ }).click()

  await expect(page.getByText(/Leave request recorded/i)).toBeVisible({ timeout: 20_000 })

  // The new request appears in the table for Ada Eze, still pending.
  const row = page.locator('tr', { hasText: 'Ada Eze' }).first()
  await expect(row).toBeVisible({ timeout: 20_000 })
  await expect(row.getByText('pending')).toBeVisible()
})
