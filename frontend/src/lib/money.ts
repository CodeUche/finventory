/**
 * Exact money sums on the decimal strings the API sends. No floating point: each amount is
 * turned into a whole number of 1/10,000ths (BigInt), added, and turned back into a string.
 */
const SCALE = 4
const FACTOR = BigInt(10) ** BigInt(SCALE)

/** "1234.5" / "-12.3456" / "1,000.10" -> BigInt in 1/10,000ths. Anything unreadable counts as 0. */
export function toUnits(value: string | null | undefined): bigint {
  const raw = (value ?? '').replace(/,/g, '').trim()
  const m = /^(-?)(\d*)(?:\.(\d*))?$/.exec(raw)
  if (!m || (m[2] === '' && !m[3])) return BigInt(0)
  const whole = BigInt(m[2] || '0') * FACTOR
  const frac = BigInt(((m[3] ?? '') + '0'.repeat(SCALE)).slice(0, SCALE))
  const n = whole + frac
  return m[1] === '-' ? -n : n
}

/** BigInt in 1/10,000ths -> decimal string like "1234.5000" (kept at 4 places; formatCurrency rounds for display). */
export function fromUnits(units: bigint): string {
  const neg = units < BigInt(0)
  const abs = neg ? -units : units
  const whole = abs / FACTOR
  const frac = (abs % FACTOR).toString().padStart(SCALE, '0')
  return `${neg ? '-' : ''}${whole.toString()}.${frac}`
}

export function sumUnits(values: Array<string | null | undefined>): bigint {
  return values.reduce<bigint>((acc, v) => acc + toUnits(v), BigInt(0))
}
