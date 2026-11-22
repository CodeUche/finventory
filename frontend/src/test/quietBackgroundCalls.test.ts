import { describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

// A cashier who may not read tax classes or warehouses must not see a red toast for the
// register's own background look-ups. Those calls must ask the API layer to stay quiet.
const read = (p: string) => readFileSync(resolve(__dirname, '..', p), 'utf8')

describe('register background calls are quiet', () => {
  it('tax rates load with silentErrors', () => {
    expect(read('hooks/useTaxRates.ts')).toMatch(/taxApi\.classes\(\{ silentErrors: true \}\)/)
  })
  it('the warehouse look-up on the register is silent', () => {
    expect(read('pages/pos/PosRegisterPage.tsx')).toMatch(/inventoryApi\.warehouses\(\{ silentErrors: true \}\)/)
  })
  it('the warm-up calls for credits and locations are silent', () => {
    const src = read('lib/cacheWarm.ts')
    expect(src).toMatch(/creditApi\.list\(undefined, SILENT\)/)
    expect(src).toMatch(/locationApi\.list\(undefined, SILENT\)/)
    vi.restoreAllMocks()
  })
})
