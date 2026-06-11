import { useRef, useState } from 'react'
import { api } from '@/services/api'
import { Upload, Download, CheckCircle, XCircle, AlertTriangle, FileText, Users, BookOpen, Loader2, Maximize2, X, Sparkles, ChevronDown, ChevronUp } from 'lucide-react'
import toast from 'react-hot-toast'
import { importApi } from '@/services/api'
import { save } from '@tauri-apps/plugin-dialog'
import { writeFile } from '@tauri-apps/plugin-fs'

/** Parse a full CSV text and return [headerRow, ...dataRows] with smart header detection.
 *  Handles exported spreadsheets that have title/blank rows before the actual header.
 *  Empty header columns are stripped; sparse rows (< 2 non-empty cells) are skipped. */
function parseCSV(text: string): string[][] {
  // Step 1: full CSV parse into raw rows
  const allRows: string[][] = []
  let row: string[] = []
  let cell = ''
  let inQuote = false
  for (let i = 0; i < text.length; i++) {
    const ch = text[i]
    if (inQuote) {
      if (ch === '"' && text[i + 1] === '"') { cell += '"'; i++ }
      else if (ch === '"') { inQuote = false }
      else { cell += ch }
    } else {
      if (ch === '"') { inQuote = true }
      else if (ch === ',') { row.push(cell.trim()); cell = '' }
      else if (ch === '\n' || (ch === '\r' && text[i + 1] === '\n')) {
        if (ch === '\r') i++
        row.push(cell.trim()); cell = ''
        if (row.some(Boolean)) allRows.push(row)
        row = []
      } else { cell += ch }
    }
  }
  if (cell || row.length) { row.push(cell.trim()); if (row.some(Boolean)) allRows.push(row) }

  if (allRows.length === 0) return []

  // Step 2: find the real header row — first row with 3+ non-empty cells
  let headerIdx = 0
  for (let i = 0; i < allRows.length; i++) {
    if (allRows[i].filter(c => c.trim()).length >= 3) { headerIdx = i; break }
  }

  // Step 3: collect non-empty, non-duplicate header columns and their indices
  const headerRow = allRows[headerIdx]
  const colIndices: number[] = []
  const cleanHeaders: string[] = []
  const seen = new Set<string>()
  headerRow.forEach((h, idx) => {
    const clean = h.trim()
    if (clean && !seen.has(clean.toLowerCase())) {
      colIndices.push(idx)
      cleanHeaders.push(clean)
      seen.add(clean.toLowerCase())
    }
  })

  // Step 4: data rows — only keep rows with 2+ non-empty cells, use only detected column indices
  const dataRows = allRows.slice(headerIdx + 1)
    .filter(r => r.filter(c => c.trim()).length >= 2)
    .map(r => colIndices.map(idx => r[idx]?.trim() ?? ''))

  return [cleanHeaders, ...dataRows]
}

type Entity = 'products' | 'customers' | 'accounts'
type ImportError = { row: number; field: string; message: string }
type ImportResult = { created: number; updated: number; errors: ImportError[]; total_rows: number; warehouses_created?: number; stock_assigned?: number }

// All product fields with human-readable labels
const PRODUCT_FIELD_LABELS: Record<string, string> = {
  sku: 'SKU / Product Code',
  name: 'Product Name',
  selling_price: 'Selling Price',
  cost_price: 'Cost Price',
  wholesale_price: 'Wholesale Price',
  product_type: 'Product Type',
  category: 'Category',
  brand: 'Brand',
  unit_of_measure: 'Unit of Measure',
  reorder_level: 'Reorder Level',
  barcode: 'Barcode',
  description: 'Description',
  warehouse: 'Warehouse',
  opening_stock: 'Opening Stock Qty',
}

const PRODUCT_KEY_FIELDS = ['sku', 'name', 'selling_price', 'cost_price', 'wholesale_price']
const PRODUCT_EXTRA_FIELDS = Object.keys(PRODUCT_FIELD_LABELS).filter(f => !PRODUCT_KEY_FIELDS.includes(f))

const ENTITIES: { key: Entity; label: string; icon: React.ReactNode; description: string; columns: string }[] = [
  {
    key: 'products',
    label: 'Products',
    icon: <FileText size={20} />,
    description: 'Bulk import your product catalogue. All fields are optional — AI maps your columns automatically.',
    columns: 'sku, name, selling_price, cost_price, wholesale_price, product_type, category, brand, unit_of_measure, reorder_level, barcode, description, warehouse, opening_stock',
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
  const [allRows, setAllRows] = useState<string[][]>([])
  const [previewHeaders, setPreviewHeaders] = useState<string[]>([])
  const [importing, setImporting] = useState(false)
  const [result, setResult] = useState<ImportResult | null>(null)
  const [expanded, setExpanded] = useState(false)

  // Column mapping state (for products): { ourField: csvColumn }
  const [mapping, setMapping] = useState<Record<string, string>>({})
  const [mappingLoading, setMappingLoading] = useState(false)
  const [mappingMethod, setMappingMethod] = useState<string>('')
  const [showExtraFields, setShowExtraFields] = useState(false)

  const fileRef = useRef<HTMLInputElement>(null)

  const selected = ENTITIES.find(e => e.key === entity)!
  const previewRows = allRows.slice(0, 5)

  function handleEntityChange(e: Entity) {
    setEntity(e)
    setFile(null)
    setAllRows([])
    setPreviewHeaders([])
    setResult(null)
    setExpanded(false)
    setMapping({})
    setMappingLoading(false)
    setMappingMethod('')
    if (fileRef.current) fileRef.current.value = ''
  }

  async function suggestMapping(headers: string[]) {
    setMappingLoading(true)
    setMappingMethod('')
    try {
      const { data } = await importApi.suggestMapping(entity, headers)
      // data.mapping = { ourField: "CSV Column Header" }
      setMapping(data.mapping || {})
      setMappingMethod(data.method || 'rules')
    } catch {
      // silent — user can set manually
      setMapping({})
    } finally {
      setMappingLoading(false)
    }
  }

  function handleFile(f: File | undefined) {
    if (!f) return
    setFile(f)
    setResult(null)
    setExpanded(false)
    setMapping({})
    setMappingMethod('')
    const reader = new FileReader()
    reader.onload = (ev) => {
      const parsed = parseCSV(ev.target?.result as string)
      const headers = parsed[0] ?? []
      setPreviewHeaders(headers)
      setAllRows(parsed.slice(1).filter(r => r.some(Boolean)))
      if (entity === 'products' && headers.length > 0) {
        suggestMapping(headers)
      }
    }
    reader.readAsText(f)
  }

  async function handleImport() {
    if (!file) return
    setImporting(true)
    try {
      const importMapping = entity === 'products' ? mapping : undefined
      const { data } = await importApi[entity](file as any, importMapping as any)
      setResult(data)
      if (data.errors.length === 0) {
        const stockMsg = data.stock_assigned ? `, ${data.stock_assigned} stocked` : ''
        const whMsg = data.warehouses_created ? `, ${data.warehouses_created} warehouse(s) created` : ''
        toast.success(`Import complete: ${data.created} created, ${data.updated} updated${stockMsg}${whMsg}`)
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
      const resp = await api.get(importApi.templateUrl(entity), { responseType: 'arraybuffer' })
      const defaultName = `${entity}_import_template.csv`
      const filePath = await save({
        defaultPath: defaultName,
        filters: [{ name: 'CSV', extensions: ['csv'] }],
      })
      if (!filePath) return
      await writeFile(filePath, new Uint8Array(resp.data))
      toast.success(`Template saved to ${filePath.split(/[\\/]/).pop()}`)
    } catch {
      toast.error('Failed to download template')
    }
  }

  function MappingRow({ field }: { field: string }) {
    const label = PRODUCT_FIELD_LABELS[field] || field
    const isKey = PRODUCT_KEY_FIELDS.includes(field)
    const currentVal = mapping[field] || ''
    const unmatched = isKey && !currentVal

    return (
      <div className={`flex items-center gap-2 py-1.5 border-b last:border-0 ${unmatched ? 'border-amber-500/20' : 'border-surface-700/50'}`}>
        <div className="w-44 shrink-0">
          <span className={`text-xs ${unmatched ? 'text-amber-300' : 'text-slate-300'}`}>{label}</span>
          {isKey && !currentVal && (
            <span className="ml-1.5 text-[10px] text-amber-400 bg-amber-500/10 px-1 rounded">select column</span>
          )}
          {isKey && currentVal && (
            <span className="ml-1.5 text-[10px] text-indigo-400 bg-indigo-500/10 px-1 rounded">key</span>
          )}
        </div>
        <select
          value={currentVal}
          onChange={e => setMapping(prev => ({ ...prev, [field]: e.target.value }))}
          style={{ colorScheme: 'dark' }}
          className={`flex-1 border rounded-lg px-2 py-1 text-xs focus:outline-none ${
            unmatched
              ? 'bg-amber-500/5 border-amber-500/40 text-amber-200 focus:border-amber-400'
              : 'bg-surface-700 border-surface-600 text-slate-300 focus:border-indigo-500'
          }`}
        >
          <option value="">— Skip / Not in CSV —</option>
          {previewHeaders.map(h => (
            <option key={h} value={h}>{h}</option>
          ))}
        </select>
        {currentVal && (
          <span className="text-[10px] text-emerald-400 shrink-0">✓</span>
        )}
      </div>
    )
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
            <p className="text-xs font-medium text-slate-400 uppercase tracking-wider mb-1">
              {entity === 'products' ? 'Available columns (all optional — AI maps your headers automatically)' : 'Required columns (marked *) and optional columns'}
            </p>
            <p className="text-xs text-slate-300 font-mono leading-relaxed">{selected.columns}</p>
            {entity === 'products' && (
              <p className="text-xs text-indigo-400/80 mt-1.5">
                <Sparkles size={11} className="inline mr-1" />
                Your CSV can use any column names — AI will match "Retail Price" → selling_price, "Product Name" → name, etc.
              </p>
            )}
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
        className="rounded-xl border-2 border-dashed border-surface-600 hover:border-indigo-500/60 bg-surface-800/50 px-5 py-4 flex items-center gap-4 cursor-pointer transition-colors"
      >
        <Upload size={20} className="text-slate-500 shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-slate-300 truncate">{file ? file.name : 'Click or drag a CSV file here'}</p>
          <p className="text-xs text-slate-500 mt-0.5">CSV · UTF-8 · Max 10 MB</p>
        </div>
        {file && (
          <button
            onClick={e => { e.stopPropagation(); setFile(null); setAllRows([]); setPreviewHeaders([]); setMapping({}); if (fileRef.current) fileRef.current.value = '' }}
            className="shrink-0 p-1 text-slate-500 hover:text-slate-300 transition-colors"
          >
            <X size={14} />
          </button>
        )}
        <input ref={fileRef} type="file" accept=".csv,text/csv" className="hidden" onChange={ev => handleFile(ev.target.files?.[0])} />
      </div>

      {/* Preview table */}
      {previewHeaders.length > 0 && (
        <div className="rounded-xl border border-surface-700 overflow-hidden">
          <div className="px-4 py-2 bg-surface-800 border-b border-surface-700 flex items-center justify-between">
            <p className="text-xs font-medium text-slate-400">
              Preview · {allRows.length} row{allRows.length !== 1 ? 's' : ''} total (showing first 5)
            </p>
            <button
              onClick={() => setExpanded(true)}
              className="flex items-center gap-1.5 text-xs text-indigo-400 hover:text-indigo-300 transition-colors"
              title="Expand full view"
            >
              <Maximize2 size={13} /> Full view
            </button>
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
                {previewRows.map((row, ri) => (
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

      {/* AI Column Mapping (products only) */}
      {entity === 'products' && previewHeaders.length > 0 && (
        <div className="rounded-xl border border-indigo-500/30 bg-surface-800 overflow-hidden">
          <div className="px-4 py-3 bg-indigo-500/10 border-b border-indigo-500/20 flex items-center gap-2">
            <Sparkles size={14} className="text-indigo-400" />
            <p className="text-sm font-semibold text-indigo-300">AI Column Mapping</p>
            {mappingLoading && (
              <span className="flex items-center gap-1 text-xs text-slate-400 ml-auto">
                <Loader2 size={11} className="animate-spin" /> Detecting columns…
              </span>
            )}
            {!mappingLoading && mappingMethod && (
              <span className="ml-auto text-[10px] text-slate-500">
                {mappingMethod === 'ai+rules' ? '🤖 AI + rules' : '📋 Rules matched'}
              </span>
            )}
          </div>
          <div className="p-4">
            <p className="text-xs text-slate-400 mb-3">
              Review how your CSV columns map to our fields. Adjust any mismatches. Fields with no match will use default values.
            </p>

            {/* Key fields */}
            <div className="mb-1">
              <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2">Core fields</p>
              {PRODUCT_KEY_FIELDS.map(f => <MappingRow key={f} field={f} />)}
            </div>

            {/* Extra fields toggle */}
            <button
              onClick={() => setShowExtraFields(p => !p)}
              className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-300 mt-3 transition-colors"
            >
              {showExtraFields ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
              {showExtraFields ? 'Hide' : 'Show'} optional fields ({PRODUCT_EXTRA_FIELDS.length})
            </button>

            {showExtraFields && (
              <div className="mt-2">
                {PRODUCT_EXTRA_FIELDS.map(f => <MappingRow key={f} field={f} />)}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Full expand modal */}
      {expanded && previewHeaders.length > 0 && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm">
          <div className="bg-surface-800 border border-surface-700 rounded-2xl w-full max-w-6xl max-h-[90vh] flex flex-col shadow-2xl animate-slide-up">
            <div className="flex items-center justify-between px-5 py-3 border-b border-surface-700 shrink-0">
              <div>
                <p className="text-sm font-semibold text-white">{file?.name}</p>
                <p className="text-xs text-slate-400">{allRows.length} rows · {previewHeaders.length} columns</p>
              </div>
              <button onClick={() => setExpanded(false)} className="btn-ghost p-1.5"><X size={18} /></button>
            </div>
            <div className="overflow-auto flex-1">
              <table className="w-full text-xs">
                <thead className="bg-surface-900 sticky top-0 z-10">
                  <tr>
                    <th className="px-3 py-2 text-left text-slate-500 font-medium w-10">#</th>
                    {previewHeaders.map(h => (
                      <th key={h} className="px-3 py-2 text-left text-slate-400 font-medium whitespace-nowrap">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {allRows.map((row, ri) => (
                    <tr key={ri} className="border-t border-surface-700 hover:bg-surface-700/30">
                      <td className="px-3 py-1.5 text-slate-600 tabular-nums">{ri + 1}</td>
                      {previewHeaders.map((_, ci) => (
                        <td key={ci} className="px-3 py-1.5 text-slate-300 max-w-[240px] truncate" title={row[ci] ?? ''}>{row[ci] ?? ''}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* Import button */}
      {file && !result && (
        <div className="flex items-center justify-between gap-4">
          <div>
            {entity === 'products' && (() => {
              const unmatchedCount = PRODUCT_KEY_FIELDS.filter(f => !mapping[f]).length
              return unmatchedCount > 0 ? (
                <p className="text-xs text-amber-400">
                  ⚠ {unmatchedCount} key field{unmatchedCount > 1 ? 's' : ''} unmatched — those columns will use defaults. Review the mapping above.
                </p>
              ) : (
                <p className="text-xs text-emerald-400/80">All key fields mapped ✓</p>
              )
            })()}
            {entity !== 'products' && (
              <p className="text-xs text-slate-500">Existing records are matched by their unique code and updated.</p>
            )}
          </div>
          <button
            onClick={handleImport}
            disabled={importing || mappingLoading}
            className="btn-primary flex items-center gap-2 px-6 shrink-0"
          >
            {importing ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />}
            {importing ? 'Importing…' : `Import ${selected.label}`}
          </button>
        </div>
      )}

      {/* Result */}
      {result && (
        <div className="space-y-4">
          <div className={`grid gap-3 ${result.warehouses_created !== undefined ? 'grid-cols-2 sm:grid-cols-5' : 'grid-cols-3'}`}>
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
            {result.warehouses_created !== undefined && (
              <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 flex items-center gap-3">
                <CheckCircle size={20} className="text-amber-400" />
                <div>
                  <p className="text-xs text-slate-400">Warehouses</p>
                  <p className="text-xl font-bold text-amber-400">{result.warehouses_created}</p>
                </div>
              </div>
            )}
            {result.stock_assigned !== undefined && (
              <div className="rounded-xl border border-cyan-500/30 bg-cyan-500/10 p-4 flex items-center gap-3">
                <CheckCircle size={20} className="text-cyan-400" />
                <div>
                  <p className="text-xs text-slate-400">Stocked</p>
                  <p className="text-xl font-bold text-cyan-400">{result.stock_assigned}</p>
                </div>
              </div>
            )}
            <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 flex items-center gap-3">
              <XCircle size={20} className="text-red-400" />
              <div>
                <p className="text-xs text-slate-400">Errors</p>
                <p className="text-xl font-bold text-red-400">{result.errors.length}</p>
              </div>
            </div>
          </div>

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

          <div className="flex justify-end">
            <button
              onClick={() => { setResult(null); setFile(null); setAllRows([]); setPreviewHeaders([]); setExpanded(false); setMapping({}); if (fileRef.current) fileRef.current.value = '' }}
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
