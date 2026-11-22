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
}

/**
 * Draws the real receipt page, shrunk to whatever width its card gives it.
 * The width is measured (ResizeObserver) rather than guessed, and the height
 * follows the receipt's own length, so a short receipt is not padded out.
 */
export default function ReceiptPreview({ template, business }: Props) {
  const [mono, setMono] = useState<string | null>(null)
  const [height, setHeight] = useState(400)
  const [boxWidth, setBoxWidth] = useState(PAPER_PX)
  const frame = useRef<HTMLIFrameElement>(null)
  const box = useRef<HTMLDivElement>(null)

  // Same black-and-white conversion the printer path uses.
  useEffect(() => {
    let cancelled = false
    setMono(null)
    if (business.logoDataUrl) {
      void toMonoDataUrl(business.logoDataUrl).then((m) => { if (!cancelled) setMono(m) })
    }
    return () => { cancelled = true }
  }, [business.logoDataUrl])

  useEffect(() => {
    const el = box.current
    if (!el) return
    const read = () => setBoxWidth(el.clientWidth || PAPER_PX)
    read()
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(read)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const html = useMemo(
    // The preview page never scrolls: overflow is hidden so a scrollbar can never
    // eat 15px of width and cut the right edge off the receipt.
    () => buildReceiptHtml({ ...SAMPLE_SALE, ...business, logoDataUrl: mono, template })
      .replace('<html>', '<html style="overflow: hidden">')
      .replace('<body style="', '<body style="overflow: hidden; '),
    [business, mono, template],
  )

  const measure = () => {
    const h = frame.current?.contentDocument?.body?.scrollHeight
    if (h) setHeight((prev) => (Math.abs(prev - h) > 1 ? h : prev))
  }

  // Re-measure after the logo and fonts have settled, not only on the first load.
  useEffect(() => {
    const t1 = window.setTimeout(measure, 60)
    const t2 = window.setTimeout(measure, 400)
    return () => { window.clearTimeout(t1); window.clearTimeout(t2) }
  }, [html])

  const scale = boxWidth / PAPER_PX

  return (
    <div
      ref={box}
      className="bg-white w-full overflow-hidden rounded-sm shadow-sm"
      style={{ height: Math.ceil(height * scale) }}
    >
      {/* No scripts are allowed in here; same-origin only so we can measure the page. */}
      <iframe
        ref={frame}
        title={`${template} receipt preview`}
        srcDoc={html}
        sandbox="allow-same-origin"
        scrolling="no"
        tabIndex={-1}
        aria-hidden="true"
        onLoad={measure}
        style={{
          width: PAPER_PX, height, border: 0, background: '#fff', pointerEvents: 'none',
          transform: `scale(${scale})`, transformOrigin: 'top left', display: 'block',
        }}
      />
    </div>
  )
}
