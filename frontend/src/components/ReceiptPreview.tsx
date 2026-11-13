import { useEffect, useMemo, useRef, useState } from 'react'
import {
  buildReceiptHtml,
  toMonoDataUrl,
  type ReceiptData,
  type ReceiptTemplate,
} from '@/lib/receipt'

/**
 * The 80mm paper is about 302 CSS pixels wide. The preview draws the real
 * receipt page at that size and shrinks it to fit the card, so what the user
 * sees is exactly what will print.
 */
const PAPER_PX = 302

/** Made-up sale used only for previews. Business details are real; amounts are not. */
export const SAMPLE_SALE: Pick<
  ReceiptData,
  'invoiceNumber' | 'date' | 'time' | 'cashier' | 'lines' | 'subtotal' | 'discount' | 'tax' | 'total' | 'payments' | 'amountTendered' | 'change'
> = {
  invoiceNumber: 'INV-0001',
  date: '24/09/2026',
  time: '14:30',
  cashier: 'Sample Cashier',
  lines: [
    { name: 'Sample item A', qty: 1, unit_price: '4000.00', line_total: '4000.00', gross_total: '4000.00' },
    { name: 'Sample item B', qty: 1, unit_price: '4000.00', line_total: '3500.00', gross_total: '4000.00', discount: '500.00' },
  ],
  subtotal: '8000.00',
  discount: '500.00',
  tax: '0.00',
  total: '7500.00',
  payments: [{ method: 'cash', amount: '7500.00' }],
  amountTendered: '8000.00',
  change: '500.00',
}

interface Props {
  template: ReceiptTemplate
  /** Business name, address, phone, TIN, logo — the real profile. */
  business: Partial<ReceiptData> & Pick<ReceiptData, 'merchant'>
  /** Width of the card the preview sits in, in pixels. */
  width?: number
}

export default function ReceiptPreview({ template, business, width = 190 }: Props) {
  const [mono, setMono] = useState<string | null>(null)
  const [height, setHeight] = useState(520)
  const frame = useRef<HTMLIFrameElement>(null)

  // Same black-and-white conversion the printer path uses.
  useEffect(() => {
    let cancelled = false
    setMono(null)
    if (business.logoDataUrl) {
      void toMonoDataUrl(business.logoDataUrl).then((m) => { if (!cancelled) setMono(m) })
    }
    return () => { cancelled = true }
  }, [business.logoDataUrl])

  const html = useMemo(
    () => buildReceiptHtml({ ...SAMPLE_SALE, ...business, logoDataUrl: mono, template }),
    [business, mono, template],
  )

  const scale = width / PAPER_PX

  return (
    <div
      className="bg-white mx-auto overflow-hidden rounded-sm shadow-sm"
      style={{ width, height: Math.round(height * scale) }}
    >
      {/* No scripts are allowed in here; same-origin only so we can measure the page. */}
      <iframe
        ref={frame}
        title={`${template} receipt preview`}
        srcDoc={html}
        sandbox="allow-same-origin"
        tabIndex={-1}
        aria-hidden="true"
        onLoad={() => {
          const h = frame.current?.contentDocument?.documentElement?.scrollHeight
          if (h) setHeight(h)
        }}
        style={{
          width: PAPER_PX, height, border: 0, background: '#fff', pointerEvents: 'none',
          transform: `scale(${scale})`, transformOrigin: 'top left',
        }}
      />
    </div>
  )
}
