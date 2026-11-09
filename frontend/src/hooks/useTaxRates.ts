import { useEffect, useState } from 'react'
import { taxApi } from '@/services/api'
import { useAuthStore } from '@/store/authStore'

/** VAT rate per tax class, for working out a sale's total on screen. Empty when
 *  the business does not charge VAT, matching the server (SaleService.default_tax_rate). */
export function useTaxRates(): Record<string, number> {
  const chargesVat = useAuthStore((s) => s.organisation?.charges_vat) !== false
  const [rates, setRates] = useState<Record<string, number>>({})
  useEffect(() => {
    if (!chargesVat) { setRates({}); return }
    taxApi.classes().then(({ data }) => {
      const list: { id: string; rate: string }[] = data.results ?? data
      setRates(Object.fromEntries(list.map((c) => [c.id, parseFloat(c.rate) || 0])))
    }).catch(() => {})
  }, [chargesVat])
  return chargesVat ? rates : {}
}
