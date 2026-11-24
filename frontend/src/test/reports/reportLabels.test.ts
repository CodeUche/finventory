import { describe, it, expect } from 'vitest'
import { fieldLabel, fieldLabelInline } from '@/lib/reportLabels'

describe('report field labels', () => {
  it('turns backend field names into plain words', () => {
    expect(fieldLabel('gross_margin_pct')).toBe('Gross margin %')
    expect(fieldLabel('net_margin_pct')).toBe('Net margin %')
    expect(fieldLabel('cost_of_goods_sold')).toBe('Cost of goods sold')
    expect(fieldLabel('operating_expenses')).toBe('Operating expenses')
    expect(fieldLabel('net_profit')).toBe('Net profit')
    expect(fieldLabel('wht_withheld')).toBe('WHT withheld')
    expect(fieldLabel('paye_payable')).toBe('PAYE payable')
    expect(fieldLabel('account_code')).toBe('Account code')
  })
  it('reads "Revenue — sales excluding VAT" after the dash', () => {
    expect(`Revenue — ${fieldLabelInline('sales_excl_vat')}`).toBe('Revenue — sales excluding VAT')
    expect(`VAT — ${fieldLabelInline('output_vat')}`).toBe('VAT — output VAT')
    expect(`Revenue — ${fieldLabelInline('gross_sales')}`).toBe('Revenue — gross sales')
  })
  it('never leaves the old Title Case field-name look', () => {
    for (const k of ['sales_excl_vat', 'gross_margin_pct', 'net_margin_pct', 'cost_of_goods_sold', 'input_vat']) {
      expect(fieldLabel(k)).not.toMatch(/\b(Excl|Pct|Vat|Of)\b/)
    }
  })
})
