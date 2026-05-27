import { useRef, useState } from 'react'
import { api } from '@/services/api'
import { Upload, Download, CheckCircle, XCircle, AlertTriangle, FileText, Users, BookOpen, Loader2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { importApi } from '@/services/api'

type Entity = 'products' | 'customers' | 'accounts'
type ImportError = { row: number; field: string; message: string }
type ImportResult = { created: number; updated: number; errors: ImportError[]; total_rows: number }

const ENTITIES: { key: Entity; label: string; icon: React.ReactNode; description: string; columns: string }[] = [
  {
    key: 'products',
    label: 'Products',
    icon: <FileText size={20} />,
    description: 'Bulk import your product catalogue with pricing and stock settings.',
    columns: 'sku*, name*, selling_price*, cost_price*, product_type, category, brand, unit_of_measure, reorder_level, barcode, description',
  },
  {
    key: 'customers',
    label: 'Customers',
    icon: <Users size={20} />,
    description: 'Import your customer list with contact details and credit settings.',
    columns: 'code*, name*, customer_type, email, phone, address, contact_person, credit_limit, payment_terms_days, notes',
  },
  {
    key: 'accounts',
    label: 'Chart of Accounts',
    icon: <BookOpen size={20} />,
    description: 'Import additional GL accounts into your chart of accounts.',
    columns: 'code*, name*, account_type*, description',
  },
]

export default function ImportPage() {
  const [entity, setEntity] = useState<Entity>('products')
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<string[][] | null>(null)
  const [previewHeaders, setPreviewHeaders] = useState<string[]>([])
  const [importing, setImporting] = useState(false)
  const [result, setResult] = useState<ImportResult | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const selected = ENTITIES.find(e => e.key === entity)!

  function handleEntityChange(e: Entity) {
    setEntity(e)
    setFile(null)
    setPreview(null)
    setPreviewHeaders([])
    setResult(null)
    if (fileRef.current) fileRef.current.value = ''
  }

  function handleFile(f: File | undefined) {
    if (!f) return
    setFile(f)
    setResult(null)
    const reader = new FileReader()
    reader.onload = (ev) => {
      const text = ev.target?.result as string
      const lines = text.split(/\r?\n/).filter(Boolean)
      const parsed = lines.slice(0, 6).map(l => l.split(',').map(c => c.replace(/^"|"$/g, '').trim()))
      setPreviewHeaders(parsed[0] ?? [])
      setPreview(parsed.slice(1))
    }
    reader.readAsText(f)
  }

  async function handleImport() {
    if (!file) return
    setImporting(true)
    try {
      const { data } = await importApi[entity](file)
      setResult(data)
      if (data.errors.length === 0) {
        toast.success(`Import complete: ${data.created} created, ${data.updated} updated`)
      } else {
        toast(`Import done with ${data.errors.length} error(s)`, { icon: '⚠️' })
      }
    } catch (err: any) {
      const msg = err?.response?.data?.error
      toast.error(typeof msg === 'string' ? msg : 'Import failed')
    } finally {
      setImporting(false)
    }
  }

  async function downloadTemplate() {
    try {
      const resp = await api.get(importApi.templateUrl(entity), { responseType: 'blob' })
      const objectUrl = URL.createObjectURL(new Blob([resp.data], { type: 'text/csv' }))
      const a = document.createElement('a')
      a.href = objectUrl
      a.download = `${entity}_import_template.csv`
      a.click()
      URL.revokeObjectURL(objectUrl)
    } catch {
      toast.error('Failed to download template')
    }
  }

  return (
    <div className="p-6 space-y-6 max-w-5xl mx-auto">
      <div>
        <h1 className="text-xl font-semibold text-white">CSV Import</h1>
        <p className="text-sm text-slate-400 mt-0.5">Bulk-import records from a CSV file. Existing records are updated by their unique key (SKU / code).</p>
      </div>

      {/* Entity selector */}
      <div className="grid grid-cols-3 gap-3">
        {ENTITIES.map(e => (
          <button
            key={e.key}
            onClick={() => handleEntityChange(e.key)}
            className={`p-4 rounded-xl border text-left transition-colors ${
              entity === e.key
                ? 'border-indigo-500 bg-indigo-500/10 text-indigo-300'
                : 'border-surface-700 bg-surface-800 text-slate-300 hover:border-slate-500'
            }`}
          >
            <div className="flex items-center gap-2 font-medium mb-1">{e.icon}{e.label}</div>
            <p className="text-xs text-slate-400">{e.description}</p>
          </button>
        ))}
      </div>

      {/* Column reference + template download */}
      <div className="rounded-xl border border-surface-700 bg-surface-800 p-4 space-y-2">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-xs font-medium text-slate-400 uppercase tracking-wider mb-1">Required columns (marked *) and optional columns</p>
            <p className="text-xs text-slate-300 font-mono leading-relaxed">{selected.columns}</p>
          </div>
          <button
            onClick={downloadTemplate}
            className="flex-shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-indigo-500/50 text-indigo-300 hover:bg-indigo-500/10 text-xs font-medium transition-colors"
          >
            <Download size={13} /> Download Template
          </button>
        </div>
      </div>

      {/* File upload */}
      <div
        onClick={() => fileRef.current?.click()}
        onDragOver={ev => ev.preventDefault()}
        onDrop={ev => { ev.preventDefault(); handleFile(ev.dataTransfer.files[0]) }}
        className="rounded-xl border-2 border-dashed border-surface-600 hover:border-indigo-500/60 bg-surface-800/50 p-10 flex flex-col items-center gap-3 cursor-pointer transition-colors"
      >
        <Upload size={28} className="text-slate-500" />
        <p className="text-slate-300 font-medium">{file ? file.name : 'Click or drag a CSV file here'}</p>
        <p className="text-xs text-slate-500">CSV files only · UTF-8 encoding · Max 10 MB</p>
        <input
          ref={fileRef}
          type="file"
          accept=".csv,text/csv"
          className="hidden"
          onChange={ev => handleFile(ev.target.files?.[0])}
        />
      </div>

      {/* Preview table */}
      {preview && previewHeaders.length > 0 && (
        <div className="rounded-xl border border-surface-700 overflow-hidden">
          <div className="px-4 py-2 bg-surface-800 border-b border-surface-700">
            <p className="text-xs font-medium text-slate-400">Preview (first 5 rows)</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-surface-900">
                <tr>
                  {previewHeaders.map(h => (
                    <th key={h} className="px-3 py-2 text-left text-slate-400 font-medium whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {preview.map((row, ri) => (
                  <tr key={ri} className="border-t border-surface-700">
                    {previewHeaders.map((_, ci) => (
                      <td key={ci} className="px-3 py-1.5 text-slate-300 whitespace-nowrap max-w-[200px] truncate">{row[ci] ?? ''}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Import button */}
      {file && !result && (
        <div className="flex justify-end">
          <button
            onClick={handleImport}
            disabled={importing}
            className="btn-primary flex items-center gap-2 px-6"
          >
            {importing ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />}
            {importing ? 'Importing…' : `Import ${selected.label}`}
          </button>
        </div>
      )}

      {/* Result */}
      {result && (
        <div className="space-y-4">
          {/* Summary strip */}
          <div className="grid grid-cols-3 gap-3">
            <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-4 flex items-center gap-3">
              <CheckCircle size={20} className="text-emerald-400" />
              <div>
                <p className="text-xs text-slate-400">Created</p>
                <p className="text-xl font-bold text-emerald-400">{result.created}</p>
              </div>
            </div>
            <div className="rounded-xl border border-indigo-500/30 bg-indigo-500/10 p-4 flex items-center gap-3">
              <CheckCircle size={20} className="text-indigo-400" />
              <div>
                <p className="text-xs text-slate-400">Updated</p>
                <p className="text-xl font-bold text-indigo-400">{result.updated}</p>
              </div>
            </div>
            <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 flex items-center gap-3">
              <XCircle size={20} className="text-red-400" />
              <div>
                <p className="text-xs text-slate-400">Errors</p>
                <p className="text-xl font-bold text-red-400">{result.errors.length}</p>
              </div>
            </div>
          </div>

          {/* Error table */}
          {result.errors.length > 0 && (
            <div className="rounded-xl border border-red-500/30 overflow-hidden">
              <div className="px-4 py-2 bg-red-500/10 border-b border-red-500/20 flex items-center gap-2">
                <AlertTriangle size={14} className="text-red-400" />
                <p className="text-xs font-medium text-red-300">Row errors — fix these in your CSV and re-import</p>
              </div>
              <table className="w-full text-xs">
                <thead className="bg-surface-900">
                  <tr>
                    <th className="px-4 py-2 text-left text-slate-400 font-medium">Row</th>
                    <th className="px-4 py-2 text-left text-slate-400 font-medium">Field</th>
                    <th className="px-4 py-2 text-left text-slate-400 font-medium">Error</th>
                  </tr>
                </thead>
                <tbody>
                  {result.errors.map((e, i) => (
                    <tr key={i} className="border-t border-surface-700">
                      <td className="px-4 py-2 text-slate-300">{e.row}</td>
                      <td className="px-4 py-2 text-amber-300 font-mono">{e.field}</td>
                      <td className="px-4 py-2 text-red-300">{e.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Import again */}
          <div className="flex justify-end">
            <button
              onClick={() => { setResult(null); setFile(null); setPreview(null); if (fileRef.current) fileRef.current.value = '' }}
              className="text-xs text-indigo-400 hover:text-indigo-300"
            >
              Import another file
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
