/**
 * Stress-verification of the exact total allocator.
 *
 * Contract under test ("no room for errors"):
 *  1. allocateTotal's achievedTotal ALWAYS equals the independently recomputed
 *     sum of its output lines (self-consistency — never lies).
 *  2. When it reports exact=true, achievedTotal === the requested target.
 *  3. For realistic retail scenarios (integer quantities ≤ 100), the target is
 *     hit exactly, every time.
 */
import { describe, it, expect } from 'vitest'
import { allocateTotal, type AllocLine } from '@/lib/totalAllocator'

// Independent forward computation (deliberately re-implemented, not imported
// internals) mirroring backend round_money: ROUND_HALF_UP at 2dp per step.
function halfUp(n: bigint, d: bigint): bigint { return (2n * n + d) / (2n * d) }
function lineKobo(q: number, p: number, d: number): bigint {
  const qc = BigInt(Math.round(q * 100))
  const pdm = BigInt(Math.round(p * 10000))
  const dc = BigInt(Math.round(d * 100))
  const sub = halfUp(qc * pdm, 10000n)
  const disc = halfUp(sub * dc, 10000n)
  return sub - disc
}
function totalKobo(lines: AllocLine[], prices: number[]): bigint {
  return lines.reduce((s, l, i) => s + lineKobo(l.quantity, prices[i], l.discountPercent), 0n)
}

function mulberry32(seed: number) {
  return () => {
    seed |= 0; seed = (seed + 0x6D2B79F5) | 0
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

describe('allocateTotal — exactness stress test', () => {
  it('10,000 random realistic scenarios: always self-consistent, always exact for integer quantities', () => {
    const rand = mulberry32(20260714)
    let exactCount = 0
    const N = 10000
    for (let iter = 0; iter < N; iter++) {
      const nLines = 1 + Math.floor(rand() * 6)
      const lines: AllocLine[] = Array.from({ length: nLines }, () => ({
        quantity: 1 + Math.floor(rand() * 100),                       // 1..100 integer qty
        unitPrice: Math.round(rand() * 5_000_000_00) / 100,           // ₦0 .. ₦5,000,000 (2dp)
        discountPercent: rand() < 0.3 ? Math.round(rand() * 5000) / 100 : 0, // 0..50%
      }))
      // Current total, then perturb it to a new target (± up to 20%, ≥ ₦1)
      const current = Number(totalKobo(lines, lines.map((l) => l.unitPrice))) / 100
      const target = Math.max(1, Math.round(current * (0.8 + rand() * 0.4) * 100) / 100)

      const res = allocateTotal(lines, target)
      expect(res).not.toBeNull()
      // (1) self-consistency: reported achievedTotal matches independent recompute
      const recomputed = Number(totalKobo(lines, res!.prices)) / 100
      expect(recomputed).toBe(res!.achievedTotal)
      // (2) exact flag honesty
      if (res!.exact) {
        expect(res!.achievedTotal).toBe(target)
        exactCount++
      }
      // prices are non-negative, 4dp-representable
      for (const p of res!.prices) {
        expect(p).toBeGreaterThanOrEqual(0)
        expect(Math.round(p * 10000) / 10000).toBe(p)
      }
    }
    // (3) realistic scenarios must hit the exact target every single time
    expect(exactCount).toBe(N)
  })

  it('fractional quantities: never lies about exactness', () => {
    const rand = mulberry32(99)
    for (let iter = 0; iter < 2000; iter++) {
      const lines: AllocLine[] = Array.from({ length: 1 + Math.floor(rand() * 4) }, () => ({
        quantity: Math.max(0.01, Math.round(rand() * 50000) / 100),   // fractional qty up to 500.00
        unitPrice: Math.round(rand() * 100_000_00) / 100,
        discountPercent: 0,
      }))
      const current = Number(totalKobo(lines, lines.map((l) => l.unitPrice))) / 100
      const target = Math.max(1, Math.round(current * (0.9 + rand() * 0.2) * 100) / 100)
      const res = allocateTotal(lines, target)
      expect(res).not.toBeNull()
      const recomputed = Number(totalKobo(lines, res!.prices)) / 100
      expect(recomputed).toBe(res!.achievedTotal)
      if (res!.exact) expect(res!.achievedTotal).toBe(target)
      else expect(Math.abs(res!.achievedTotal - target)).toBeLessThan(1) // within ₦1 worst case
    }
  })

  it('screenshot scenario: 9 × 380,000 + 6 × 160,000 → edit total to 4,000,000', () => {
    const lines: AllocLine[] = [
      { quantity: 9, unitPrice: 380000, discountPercent: 0 },
      { quantity: 6, unitPrice: 160000, discountPercent: 0 },
    ]
    const res = allocateTotal(lines, 4_000_000)!
    expect(res.exact).toBe(true)
    expect(res.achievedTotal).toBe(4_000_000)
    expect(Number(totalKobo(lines, res.prices)) / 100).toBe(4_000_000)
  })

  it('rejects invalid input', () => {
    expect(allocateTotal([], 100)).toBeNull()
    expect(allocateTotal([{ quantity: 1, unitPrice: 10, discountPercent: 0 }], NaN)).toBeNull()
    expect(allocateTotal([{ quantity: 1, unitPrice: 10, discountPercent: 0 }], -5)).toBeNull()
  })
})
