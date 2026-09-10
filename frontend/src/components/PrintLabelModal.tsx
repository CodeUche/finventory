import { Fragment, useState } from 'react'
import { X, Printer } from 'lucide-react'
import BarcodeSvg from './BarcodeSvg'
import { formatCurrency } from '@/lib/utils'
import type { Product } from '@/types'

/**
 * One barcode label: barcode + name + price + SKU, sized for a small
 * thermal label (~50mm x 30mm — the common size on the counter-top label
 * printers most retail shops already have). On a normal sheet printer the
 * browser just tiles these across the page instead of one-per-page, which
 * is a reasonable default without knowing which label sheet brand someone
 * uses.
 */
function LabelTile({ product }: { product: Product }) {
  return (
    <div className="label-tile">
      <p className="label-name">{product.name}</p>
      <BarcodeSvg value={product.barcode ?? ''} symbology={product.barcode_symbology} className="label-barcode" />
      <div className="label-footer">
        <span>{product.sku}</span>
        <span className="label-price">{formatCurrency(product.selling_price)}</span>
      </div>
    </div>
  )
}

export default function PrintLabelModal({ product, onClose }: { product: Product; onClose: () => void }) {
  const [quantity, setQuantity] = useState(1)
  const copies = Math.max(1, Math.min(200, quantity || 1))

  return (
    <Fragment>
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm print:hidden">
      <style>{`
        .label-tile {
          width: 50mm; height: 30mm; padding: 2mm;
          border: 1px solid #000; display: flex; flex-direction: column;
          align-items: center; justify-content: center; overflow: hidden;
          background: #fff; color: #000; box-sizing: border-box;
        }
        .label-name { font-size: 9px; font-weight: 600; text-align: center; width: 100%;
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-bottom: 1mm; }
        .label-barcode { width: 100%; max-height: 16mm; }
        .label-footer { display: flex; justify-content: space-between; width: 100%; font-size: 9px; margin-top: 1mm; }
        .label-price { font-weight: 700; }
        @media print {
          @page { margin: 5mm; }
          .label-print-sheet { display: flex; flex-wrap: wrap; gap: 3mm; }
        }
      `}</style>

      <div className="bg-surface-800 border border-surface-700 rounded-2xl w-full max-w-sm shadow-2xl animate-slide-up">
        <div className="flex items-center justify-between p-5 border-b border-surface-700">
          <h2 className="font-semibold text-white text-lg flex items-center gap-2">
            <Printer size={18} /> Print Label
          </h2>
          <button onClick={onClose} className="btn-ghost p-1.5"><X size={18} /></button>
        </div>

        <div className="p-5 space-y-4">
          {!product.barcode ? (
            <p className="text-sm text-amber-400">
              This product has no barcode. Save it with a barcode symbology chosen first.
            </p>
          ) : (
            <>
              <div className="flex justify-center bg-white rounded-lg p-3">
                <LabelTile product={product} />
              </div>
              <div>
                <label className="label">Number of copies</label>
                <input
                  type="number" min={1} max={200} className="input"
                  value={quantity}
                  onChange={(e) => setQuantity(parseInt(e.target.value, 10) || 1)}
                />
                <p className="text-[11px] text-slate-500 mt-1">
                  Prints one label per copy — on a thermal label printer each copy is its own label; on a regular printer they'll tile across the page.
                </p>
              </div>
            </>
          )}
        </div>

        <div className="flex gap-3 p-5 border-t border-surface-700">
          <button type="button" onClick={onClose} className="btn-secondary flex-1 justify-center">Close</button>
          <button
            type="button"
            disabled={!product.barcode}
            onClick={() => window.print()}
            className="btn-primary flex-1 justify-center disabled:opacity-50"
          >
            <Printer size={16} /> Print
          </button>
        </div>
      </div>
    </div>

    {/*
      Print-only content — deliberately a SIBLING of the modal backdrop above,
      not a child of it: the backdrop is print:hidden (display:none when
      printing), and a display:none ancestor collapses its entire subtree to
      nothing no matter what display value a descendant sets on itself. This
      has to live outside that subtree or it would never actually print.
    */}
    {product.barcode && (
      <div className="hidden print:block label-print-sheet">
        {Array.from({ length: copies }).map((_, i) => (
          <LabelTile key={i} product={product} />
        ))}
      </div>
    )}
    </Fragment>
  )
}
