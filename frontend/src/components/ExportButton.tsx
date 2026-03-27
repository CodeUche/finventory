import { useState } from 'react'
import { Download, ChevronDown } from 'lucide-react'
import { api } from '@/services/api'
import toast from 'react-hot-toast'

interface ExportButtonProps {
  endpoint: string       // e.g. '/sales/invoices/'
  filename: string       // e.g. 'invoices'
  params?: Record<string, string | number | boolean | undefined>
}

// Detect whether we're running inside Tauri
const isTauri = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window

export default function ExportButton({ endpoint, filename, params }: ExportButtonProps) {
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState<'csv' | 'xlsx' | null>(null)

  const doExport = async (fmt: 'csv' | 'xlsx') => {
    setOpen(false)
    setLoading(fmt)
    try {
      const response = await api.get(endpoint, {
        params: { ...params, dl: fmt },
        responseType: 'blob',
      })
      const blob = response.data as Blob

      if (isTauri) {
        // ── Tauri desktop: show native Save-As dialog ────────────────────────
        const { save } = await import('@tauri-apps/plugin-dialog')
        const { writeFile } = await import('@tauri-apps/plugin-fs')

        const defaultName = `${filename}_${new Date().toISOString().slice(0, 10)}.${fmt}`
        const filters = fmt === 'csv'
          ? [{ name: 'CSV Files', extensions: ['csv'] }]
          : [{ name: 'Excel Files', extensions: ['xlsx'] }]

        const savePath = await save({ defaultPath: defaultName, filters })
        if (!savePath) return // user cancelled

        const arrayBuffer = await blob.arrayBuffer()
        await writeFile(savePath, new Uint8Array(arrayBuffer))
        toast.success(`Saved to ${savePath.split(/[\\/]/).pop()}`)
      } else {
        // ── Browser: standard anchor-download approach ───────────────────────
        const mimeType = fmt === 'csv'
          ? 'text/csv'
          : 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        const blobWithType = new Blob([blob], { type: mimeType })
        const url = URL.createObjectURL(blobWithType)
        const a = document.createElement('a')
        a.href = url
        a.download = `${filename}_${new Date().toISOString().slice(0, 10)}.${fmt}`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        setTimeout(() => URL.revokeObjectURL(url), 2000)
      }
    } catch (err: unknown) {
      const msg = (err as { message?: string })?.message
      if (msg && !msg.includes('cancelled')) {
        toast.error(`Export failed: ${msg}`)
      }
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
          <div className="absolute right-0 top-full mt-1 z-50 bg-surface-800 border border-surface-700 rounded-xl shadow-xl overflow-hidden w-40">
            <button
              onClick={() => doExport('csv')}
              className="w-full px-4 py-2.5 text-sm text-left text-slate-300 hover:bg-surface-700 transition-colors"
            >
              Export as CSV
            </button>
            <button
              onClick={() => doExport('xlsx')}
              className="w-full px-4 py-2.5 text-sm text-left text-slate-300 hover:bg-surface-700 transition-colors border-t border-surface-700"
            >
              Export as Excel
            </button>
          </div>
        </>
      )}
    </div>
  )
}
