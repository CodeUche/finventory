import { Info } from 'lucide-react'

/**
 * Small info icon with a plain-language tooltip explaining what a form field does.
 * Written for business owners with no bookkeeping background.
 *
 * Usage:
 *   <label className="label">
 *     Selling Price <FieldTooltip text="The price you charge customers. This is what appears on invoices." />
 *   </label>
 */
export function FieldTooltip({ text }: { text: string }) {
  return (
    <span className="relative inline-flex items-center group/tip ml-1 align-middle">
      <Info
        size={13}
        className="text-slate-500 hover:text-brand-400 cursor-help transition-colors shrink-0"
      />
      {/* Tooltip bubble */}
      <span
        className={[
          'pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-2',
          'w-60 rounded-xl bg-surface-800 border border-surface-600',
          'px-3 py-2.5 text-xs text-slate-300 leading-relaxed',
          'opacity-0 group-hover/tip:opacity-100 transition-opacity duration-150',
          'z-[9999] shadow-xl',
        ].join(' ')}
        role="tooltip"
      >
        {text}
        {/* Arrow */}
        <span className="absolute top-full left-1/2 -translate-x-1/2 border-[5px] border-transparent border-t-surface-600" />
      </span>
    </span>
  )
}
