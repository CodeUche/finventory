import { useState } from 'react'
import { Download, ChevronDown } from 'lucide-react'
import { api } from '@/services/api'

interface ExportButtonProps {
  endpoint: string       // e.g. '/sales/invoices/'
  filename: string       // e.g. 'invoices'
  params?: Record<string, string | number | boolean | undefined>
}

export default function ExportButton({ endpoint, filename, params }: ExportButtonProps) {
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState<'csv' | 'xlsx' | null>(null)

  const doExport = async (fmt: 'csv' | 'xlsx') => {
    setOpen(false)
    setLoading(fmt)
    try {
      const response = await api.get(endpoint, {
        params: { ...params, format: fmt },
        responseType: 'blob',
      })
      const blob = new Blob([response.data], {
        type: fmt === 'csv' ? 'text/csv' : 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${filename}.${fmt}`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      // toast is handled by the Axios interceptor
    } finally {
      setLoading(null)
    }
  }

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        disabled={loading !== null}
        className="btn-ghost text-sm px-3 flex items-center gap-1.5 disabled:opacity-50"
      >
        <Download size={14} />
        {loading ? `Exporting ${loading.toUpperCase()}…` : 'Export'}
        <ChevronDown size={12} />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full mt-1 z-50 bg-surface-800 border border-surface-700 rounded-xl shadow-xl overflow-hidden w-36">
            <button
              onClick={() => doExport('csv')}
              className="w-full px-4 py-2.5 text-sm text-left text-slate-300 hover:bg-surface-700 transition-colors"
            >
              Export CSV
            </button>
            <button
              onClick={() => doExport('xlsx')}
              className="w-full px-4 py-2.5 text-sm text-left text-slate-300 hover:bg-surface-700 transition-colors border-t border-surface-700"
            >
              Export Excel
            </button>
          </div>
        </>
      )}
    </div>
  )
}
