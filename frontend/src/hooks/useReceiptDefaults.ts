import { useEffect } from 'react'
import { useAuthStore } from '@/store/authStore'
import { urlToDataUrl } from '@/services/api'
import type { ReceiptData, ReceiptTemplate } from '@/lib/receipt'

/**
 * Everything a receipt needs from the organisation. `merchant` is required
 * rather than optional — there is always a name to print, even if it falls back
 * to a generic one — so spreading these into a ReceiptData satisfies the type
 * without each call site re-asserting it.
 */
export type ReceiptDefaults =
  Pick<ReceiptData, 'merchant'> & Partial<Omit<ReceiptData, 'merchant'>>

/**
 * The parts of a receipt that come from the organisation rather than the sale.
 *
 * Every print site pulls these from one place so a merchant's address, logo and
 * chosen template can never drift between the till, the sales screen and a
 * re-print. Nothing here is ever typed per sale — it is the profile the
 * merchant already filled in under Settings.
 */
export function useReceiptDefaults(): ReceiptDefaults {
  const organisation = useAuthStore((s) => s.organisation)
  const logoDataUrl = useAuthStore((s) => s.logoDataUrl)
  const setLogoDataUrl = useAuthStore((s) => s.setLogoDataUrl)
  const logoUrl = organisation?.logo

  // A cashier who has never opened Settings has the logo's web address but no
  // local copy. Fetch it once here and keep it, so the print iframe never has to
  // download it (a cross-origin download would taint the canvas and the logo
  // would silently vanish from the receipt).
  useEffect(() => {
    if (logoDataUrl || !logoUrl) return
    let cancelled = false
    void urlToDataUrl(logoUrl).then((d) => { if (d && !cancelled) setLogoDataUrl(d) })
    return () => { cancelled = true }
  }, [logoDataUrl, logoUrl, setLogoDataUrl])

  return {
    merchant: organisation?.invoice_company_name || organisation?.name || 'Receipt',
    address: organisation?.address,
    phone: organisation?.phone,
    tin: organisation?.tax_id,
    rcNumber: organisation?.registration_number,
    footerNote: organisation?.receipt_footer_note,
    template: (organisation?.receipt_template as ReceiptTemplate) || 'compact',
    // Prefer the cached data URI — it is already local, so the print iframe
    // never waits on a network fetch. The remote URL is the fallback for a
    // cashier who has never opened Settings; toMonoDataUrl gives up quietly if
    // it cannot be read.
    logoDataUrl: logoDataUrl ?? logoUrl ?? null,
  }
}
