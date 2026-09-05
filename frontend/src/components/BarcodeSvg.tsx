import { useEffect, useRef } from 'react'
import JsBarcode from 'jsbarcode'

// Mirrors Product.BarcodeSymbology on the backend.
const FORMAT_MAP: Record<string, string> = {
  code128: 'CODE128',
  code39: 'CODE39',
  ean8: 'EAN8',
  ean13: 'EAN13',
  upc: 'UPC',
}

/**
 * Renders one scannable barcode image (SVG) for a value + symbology.
 * Format numbers (EAN-8/13, UPC) fail loudly via JsBarcode's `valid` callback
 * if the value doesn't have a correct check digit — Audity's own
 * auto-generated barcodes always do, but a manually-typed one might not, so
 * this surfaces that instead of silently rendering nothing useful.
 */
export default function BarcodeSvg({
  value,
  symbology = 'code128',
  className,
}: {
  value: string
  symbology?: string
  className?: string
}) {
  const ref = useRef<SVGSVGElement>(null)
  const isValidRef = useRef(true)

  useEffect(() => {
    if (!ref.current || !value) return
    const format = FORMAT_MAP[symbology] ?? 'CODE128'
    try {
      JsBarcode(ref.current, value, {
        format,
        displayValue: true,
        fontSize: 14,
        height: 50,
        margin: 4,
        valid: (ok) => { isValidRef.current = ok },
      })
    } catch {
      isValidRef.current = false
    }
  }, [value, symbology])

  if (!value) {
    return <p className="text-xs text-slate-500">No barcode set for this product.</p>
  }

  return <svg ref={ref} className={className} />
}
