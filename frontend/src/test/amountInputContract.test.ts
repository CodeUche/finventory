import { describe, it, expect } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'fs'
import { dirname, join, relative } from 'path'
import { fileURLToPath } from 'url'

/**
 * Guard for the AmountInput contract.
 *
 * AmountInput hands its caller a COMMA-FORMATTED string ("20,000,000") because
 * that is what the user sees. Whoever submits that value must call stripCommas
 * first. Skipping it fails in two ways, and the quiet one is the dangerous one:
 *
 *   - sent as a string  → DRF DecimalField rejects it: "A valid number is
 *     required." Loud, immediate, obvious.
 *   - via parseFloat()  → parseFloat("50,000") returns 50. It stops at the
 *     comma instead of failing, so a wrong number is saved with NO error.
 *
 * Both shipped: the Customers credit-limit field hit the first, and three
 * Payroll fields (voluntary pension, life assurance, PAYE amount paid) hit the
 * second. This test makes the whole-file omission that caused them fail in CI.
 *
 * Limits, stated honestly: this is an import-level check, not a dataflow one.
 * It catches "this page uses AmountInput and never strips anywhere", which is
 * exactly the bug that occurred twice. It cannot catch a page that strips four
 * fields and forgets a fifth. Treat it as a floor, not a proof.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')

/**
 * Files allowed to reference AmountInput without stripCommas.
 * Add an entry only with a reason — a bare addition to silence CI is the very
 * failure this guard exists to catch.
 */
const EXEMPT: Record<string, string> = {
  'components/AmountInput.tsx':
    'The component itself. Owns formatAmountInput and does its own inline comma strip in handleFocus.',
}

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) walk(full, out)
    else if (entry.endsWith('.tsx')) out.push(full)
  }
  return out
}

describe('AmountInput comma-stripping contract', () => {
  const files = walk(SRC)

  it('finds source files to check', () => {
    // Guards against a path change silently reducing this suite to a no-op.
    expect(files.length).toBeGreaterThan(20)
  })

  it('every file using AmountInput also strips commas before submitting', () => {
    const offenders: string[] = []

    for (const file of files) {
      const src = readFileSync(file, 'utf8')
      if (!src.includes('AmountInput')) continue

      const rel = relative(SRC, file).replace(/\\/g, '/')
      if (rel in EXEMPT) continue
      if (!src.includes('stripCommas')) offenders.push(rel)
    }

    expect(
      offenders,
      `These files render AmountInput but never call stripCommas, so their ` +
        `comma-formatted values reach the API unstripped:\n` +
        offenders.map((o) => `  - ${o}`).join('\n') +
        `\n\nFix: wrap the value in stripCommas() at the submit site. If the ` +
        `value genuinely never reaches an API, add it to EXEMPT with a reason.`
    ).toEqual([])
  })

  it('parseFloat on an unstripped amount is silently wrong — the reason this guard exists', () => {
    // Documents the failure mode so the next reader understands the stakes.
    expect(parseFloat('50,000')).toBe(50)
    expect(parseFloat('20,000,000')).toBe(20)
  })
})
