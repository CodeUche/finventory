/**
 * totalAllocator — exact redistribution of an edited invoice/sale TOTAL back
 * into per-line unit prices.
 *
 * Guarantees (the "no room for errors" contract):
 *  - ALL arithmetic is integer BigInt (quantities in hundredths, unit prices in
 *    ten-thousandths, money in kobo). No floating point anywhere in the math.
 *  - Rounding replicates the backend's `round_money` exactly:
 *    ROUND_HALF_UP at 2 decimal places per line step
 *    (subtotal = round2(qty × price); discount = round2(subtotal × d%); line = sub − disc).
 *  - A candidate price is only accepted after FORWARD VERIFICATION: we recompute
 *    the line total from the candidate exactly as the backend will, and require
 *    equality. The function never *claims* the target was hit unless the
 *    verified line totals sum to it precisely.
 *  - If the exact target is mathematically unreachable at 4-dp price precision
 *    (pathological quantities), the nearest achievable total is returned and
 *    flagged (`exact: false`) so the UI can tell the user — never silently off.
 */

export interface AllocLine {
  /** Quantity (up to 2 dp) */
  quantity: number
  /** Current unit price (up to 4 dp) */
  unitPrice: number
  /** Discount percent (up to 2 dp), 0–100 */
  discountPercent: number
}

export interface AllocResult {
  /** New unit prices, one per input line, as exact 4-dp numbers */
  prices: number[]
  /** The total (2-dp number) the new lines verifiably sum to */
  achievedTotal: number
  /** True when achievedTotal === requested target exactly */
  exact: boolean
}

// ── Integer helpers ────────────────────────────────────────────────────────────

/** Half-up division for non-negative BigInts: round(n / d). */
function divHalfUp(n: bigint, d: bigint): bigint {
  return (2n * n + d) / (2n * d)
}

const toQtyC = (q: number): bigint => BigInt(Math.round(q * 100))        // hundredths
const toPriceDm = (p: number): bigint => BigInt(Math.round(p * 10000))   // ten-thousandths
const toPctC = (d: number): bigint => BigInt(Math.round(d * 100))        // hundredths of a percent
const toKobo = (v: number): bigint => BigInt(Math.round(v * 100))        // hundredths (kobo)

/**
 * Forward line computation in kobo — the single source of truth, mirroring the
 * backend: sub = round2(q·P); disc = round2(sub·d/100); line = sub − disc.
 */
function lineTotalKobo(qtyC: bigint, priceDm: bigint, pctC: bigint): bigint {
  // q·P: (qtyC/100)·(priceDm/10000) currency = qtyC·priceDm / 1e6 currency
  //     = qtyC·priceDm / 1e4 kobo → half-up to whole kobo (round2 of currency).
  const sub = divHalfUp(qtyC * priceDm, 10000n)
  // sub·d/100: sub kobo × (pctC/10000) → half-up to whole kobo.
  const disc = divHalfUp(sub * pctC, 10000n)
  return sub - disc
}

/**
 * Find a 4-dp unit price whose VERIFIED line total equals `targetKobo`.
 * Searches a small window around the analytic estimate. Returns the exact
 * price if found, else the price whose achieved total is nearest the target.
 */
function solveLinePrice(
  qtyC: bigint, pctC: bigint, targetKobo: bigint,
): { priceDm: bigint; achievedKobo: bigint; exact: boolean } {
  if (qtyC <= 0n) return { priceDm: 0n, achievedKobo: 0n, exact: targetKobo === 0n }
  if (targetKobo <= 0n) return { priceDm: 0n, achievedKobo: 0n, exact: targetKobo === 0n }

  const netFactor = 10000n - pctC // (1 − d/100) in 1e-4 units; pctC ≤ 10000
  if (netFactor <= 0n) return { priceDm: 0n, achievedKobo: 0n, exact: targetKobo === 0n }

  // target ≈ qtyC·P·netFactor / 1e8 (kobo)  →  P ≈ target·1e8 / (qtyC·netFactor)
  const est = divHalfUp(targetKobo * 100000000n, qtyC * netFactor)

  let bestPrice = 0n
  let bestAchieved = -1n
  let bestDiff = -1n
  // ±80 ten-thousandths is far wider than any rounding drift the estimate can have.
  for (let step = 0n; step <= 80n; step++) {
    for (const delta of step === 0n ? [0n] : [step, -step]) {
      const cand = est + delta
      if (cand < 0n) continue
      const achieved = lineTotalKobo(qtyC, cand, pctC)
      const diff = achieved > targetKobo ? achieved - targetKobo : targetKobo - achieved
      if (diff === 0n) return { priceDm: cand, achievedKobo: achieved, exact: true }
      if (bestDiff === -1n || diff < bestDiff) {
        bestDiff = diff; bestPrice = cand; bestAchieved = achieved
      }
    }
  }
  return { priceDm: bestPrice, achievedKobo: bestAchieved, exact: false }
}

/**
 * Redistribute `newTotal` across the lines, proportional to each line's current
 * (verified) contribution, adjusting UNIT PRICES only. Quantities and discount
 * percentages are preserved exactly as entered.
 */
export function allocateTotal(lines: AllocLine[], newTotal: number): AllocResult | null {
  if (!lines.length || !(newTotal >= 0) || !isFinite(newTotal)) return null

  const qtyCs = lines.map((l) => toQtyC(l.quantity))
  const pctCs = lines.map((l) => toPctC(Math.min(100, Math.max(0, l.discountPercent))))
  const targetKobo = toKobo(newTotal)

  // Weights: current verified line totals; fall back to quantities when the
  // current total is zero (all prices blank) so allocation still works.
  let weights = lines.map((l, i) => lineTotalKobo(qtyCs[i], toPriceDm(l.unitPrice), pctCs[i]))
  let weightSum = weights.reduce((a, b) => a + b, 0n)
  if (weightSum <= 0n) {
    weights = [...qtyCs]
    weightSum = weights.reduce((a, b) => a + b, 0n)
    if (weightSum <= 0n) return null
  }

  // Sequential proportional allocation (remainder-carrying so per-line targets
  // always sum to EXACTLY targetKobo before solving).
  const prices: bigint[] = new Array(lines.length).fill(0n)
  const achieved: bigint[] = new Array(lines.length).fill(0n)
  let remainingTarget = targetKobo
  let remainingWeight = weightSum
  for (let i = 0; i < lines.length; i++) {
    const t = i === lines.length - 1
      ? remainingTarget
      : divHalfUp(remainingTarget * weights[i], remainingWeight)
    const solved = solveLinePrice(qtyCs[i], pctCs[i], t)
    prices[i] = solved.priceDm
    achieved[i] = solved.achievedKobo
    remainingTarget -= solved.achievedKobo
    remainingWeight -= weights[i]
  }

  // Residual pass: if any line missed its target (coarse qty granularity), try
  // to absorb the leftover kobo on each other line until the sum is exact.
  let residual = targetKobo - achieved.reduce((a, b) => a + b, 0n)
  if (residual !== 0n) {
    for (let i = 0; i < lines.length && residual !== 0n; i++) {
      const solved = solveLinePrice(qtyCs[i], pctCs[i], achieved[i] + residual)
      if (solved.exact) {
        prices[i] = solved.priceDm
        achieved[i] = solved.achievedKobo
        residual = 0n
      }
    }
  }

  // FINAL INDEPENDENT VERIFICATION — recompute everything from the result.
  const finalTotal = prices.reduce((sum, p, i) => sum + lineTotalKobo(qtyCs[i], p, pctCs[i]), 0n)

  return {
    prices: prices.map((p) => Number(p) / 10000),
    achievedTotal: Number(finalTotal) / 100,
    exact: finalTotal === targetKobo,
  }
}
