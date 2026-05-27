/**
 * Excel + PDF export buttons for report views.
 *
 * Calls the backend ?format=excel|pdf endpoint, downloads the file via
 * saveBlobFile (native Save-As on Tauri, anchor-download in browser).
 */

import { useState } from 'react'
import { FileSpreadsheet, FileText, Loader2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '@/services/api'
import { saveBlobFile } from '@/lib/saveBlobFile'

interface Props {
  /** e.g. '/reports/pnl/' */
  endpoint: string
  /** Params already applied to the JSON fetch — period, date_from, etc. */
  params: Record<string, string | number | boolean | undefined>
  /** Base filename without extension, e.g. 'profit_and_loss' */
  filenameBase: string
  className?: string
}

type Fmt = 'excel' | 'pdf'

const MIME: Record<Fmt, string> = {
  excel: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  pdf:   'application/pdf',
}

const EXT: Record<Fmt, string> = {
  excel: 'xlsx',
  pdf:   'pdf',
}

export default function ExportBar({ endpoint, params, filenameBase, className = '' }: Props) {
  const [loading, setLoading] = useState<Fmt | null>(null)

  const download = async (fmt: Fmt) => {
    setLoading(fmt)
    try {
      const resp = await api.get(endpoint, {
        params: { ...params, format: fmt },
        responseType: 'blob',
      })
      const blob = new Blob([resp.data as BlobPart], { type: MIME[fmt] })
      const today = new Date().toISOString().slice(0, 10)
      await saveBlobFile(blob, `${filenameBase}_${today}.${EXT[fmt]}`)
    } catch {
      toast.error(`Export failed. Please try again.`)
    } finally {
      setLoading(null)
    }
  }

  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <button
        onClick={() => download('excel')}
        disabled={loading !== null}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-surface-800 border border-surface-700 text-xs text-slate-300 hover:border-emerald-500 hover:text-emerald-400 transition-colors disabled:opacity-50"
        title="Export as Excel"
      >
        {loading === 'excel'
          ? <Loader2 size={13} className="animate-spin" />
          : <FileSpreadsheet size={13} />
        }
        Excel
      </button>

      <button
        onClick={() => download('pdf')}
        disabled={loading !== null}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-surface-800 border border-surface-700 text-xs text-slate-300 hover:border-red-500 hover:text-red-400 transition-colors disabled:opacity-50"
        title="Export as PDF"
      >
        {loading === 'pdf'
          ? <Loader2 size={13} className="animate-spin" />
          : <FileText size={13} />
        }
        PDF
      </button>
    </div>
  )
}
