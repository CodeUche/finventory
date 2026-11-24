/**
 * Plain-English labels for report fields.
 *
 * The backend sends field names like `sales_excl_vat` or `gross_margin_pct`. This turns them into
 * words a business owner reads easily ("sales excluding VAT", "Gross margin %"). It only changes
 * how the name is SHOWN: the backend keys are never renamed or sent back.
 */

/** Words that must keep a fixed spelling. */
const WORDS: Record<string, string> = {
  vat: 'VAT', paye: 'PAYE', wht: 'WHT', gl: 'GL', id: 'ID', sku: 'SKU', ar: 'AR', ap: 'AP',
  nbv: 'NBV', cogs: 'COGS', tin: 'TIN', nhf: 'NHF', ytd: 'YTD', itc: 'ITC', pos: 'POS',
  pct: '%', percent: '%', excl: 'excluding', incl: 'including', qty: 'quantity',
}

/** Whole names that read better as a fixed phrase than word by word. */
const PHRASES: Record<string, string> = {
  cost_of_goods_sold: 'cost of goods sold',
  gross_margin_pct: 'gross margin %',
  net_margin_pct: 'net margin %',
  sales_excl_vat: 'sales excluding VAT',
  tax_collected: 'VAT collected',
  paye_payable: 'PAYE payable',
  wht_withheld: 'WHT withheld',
  net_vat_payable: 'net VAT payable',
}

/** Lower-case words with acronyms kept, e.g. "sales excluding VAT". Used after a dash. */
export function fieldLabelInline(col: string): string {
  const key = col.trim().toLowerCase()
  if (PHRASES[key]) return PHRASES[key]
  return key
    .replace(/[_\s]+/g, ' ')
    .split(' ')
    .filter(Boolean)
    .map((w) => WORDS[w] ?? w)
    .join(' ')
    .replace(/\s+%/g, ' %')
}

/** Sentence-case label for a field name: first letter capital, acronyms kept. */
export function fieldLabel(col: string): string {
  const inline = fieldLabelInline(col)
  return inline.charAt(0).toUpperCase() + inline.slice(1)
}
