import { useEffect, useState, useCallback } from 'react'
import { RefreshCw, CheckCircle, XCircle, AlertTriangle, Clock, RotateCcw } from 'lucide-react'
import { accountingApi } from '@/services/api'
import toast from 'react-hot-toast'

interface GLSummary {
  posted: number
  failed: number
  not_configured: number
  pending: number
}

interface GLFailure {
  model: string
  id: string
  number: string
  error: string
  date: string
  amount: string
}

interface GLHealth {
  summary: GLSummary
  failures: GLFailure[]
}

const STATUS_META: Record<string, { label: string; icon: React.ElementType; color: string; bg: string }> = {
  posted:        { label: 'Posted',        icon: CheckCircle,   color: 'text-green-400',  bg: 'bg-green-900/30' },
  failed:        { label: 'Failed',        icon: XCircle,       color: 'text-red-400',    bg: 'bg-red-900/30' },
  not_configured:{ label: 'Not Configured',icon: AlertTriangle, color: 'text-amber-400',  bg: 'bg-amber-900/30' },
  pending:       { label: 'Pending',       icon: Clock,         color: 'text-slate-400',  bg: 'bg-slate-700/30' },
}

const MODEL_LABELS: Record<string, string> = {
  invoice: 'Invoice',
  bill: 'Bill',
  expense: 'Expense',
  payroll: 'Payroll Run',
}

export default function GLHealthPage() {
  const [data, setData] = useState<GLHealth | null>(null)
  const [loading, setLoading] = useState(true)
  const [retrying, setRetrying] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await accountingApi.glHealth()
      setData(res.data)
    } catch {
      toast.error('Failed to load GL health data')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleRetry = async (failure: GLFailure) => {
    setRetrying(failure.id)
    try {
      await accountingApi.glRetry(failure.model, failure.id)
      toast.success('GL entry posted successfully')
      load()
    } catch (err: any) {
      const msg = err?.response?.data?.error ?? 'Retry failed'
      toast.error(typeof msg === 'string' ? msg : 'Retry failed')
    } finally {
      setRetrying(null)
    }
  }

  const summary = data?.summary ?? { posted: 0, failed: 0, not_configured: 0, pending: 0 }
  const total = Object.values(summary).reduce((a, b) => a + b, 0)
  const healthPct = total > 0 ? Math.round((summary.posted / total) * 100) : 100

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-white">GL Health</h1>
          <p className="text-sm text-slate-400 mt-0.5">Monitor and retry failed journal auto-postings</p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-700 text-slate-200 text-sm hover:bg-slate-600 disabled:opacity-50"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {/* Summary tiles */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {Object.entries(STATUS_META).map(([key, meta]) => {
          const Icon = meta.icon
          const count = summary[key as keyof GLSummary] ?? 0
          return (
            <div key={key} className={`rounded-xl p-4 ${meta.bg} border border-slate-700/50`}>
              <div className="flex items-center gap-2 mb-1">
                <Icon size={16} className={meta.color} />
                <span className="text-xs text-slate-400">{meta.label}</span>
              </div>
              <p className={`text-2xl font-bold ${meta.color}`}>{count}</p>
            </div>
          )
        })}
      </div>

      {/* Health bar */}
      {total > 0 && (
        <div className="rounded-xl bg-slate-800 border border-slate-700 p-4">
          <div className="flex justify-between text-sm text-slate-400 mb-2">
            <span>GL Posting Health</span>
            <span className={healthPct >= 90 ? 'text-green-400' : healthPct >= 70 ? 'text-amber-400' : 'text-red-400'}>
              {healthPct}%
            </span>
          </div>
          <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${healthPct >= 90 ? 'bg-green-500' : healthPct >= 70 ? 'bg-amber-500' : 'bg-red-500'}`}
              style={{ width: `${healthPct}%` }}
            />
          </div>
          <p className="text-xs text-slate-500 mt-2">{summary.posted} of {total} entries successfully posted to the GL</p>
        </div>
      )}

      {/* Failures table */}
      {(data?.failures?.length ?? 0) > 0 ? (
        <div className="rounded-xl bg-slate-800 border border-slate-700 overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-700">
            <h2 className="text-sm font-medium text-white">Failures &amp; Missing Configurations</h2>
            <p className="text-xs text-slate-400 mt-0.5">Click Retry to re-attempt posting after fixing the account mapping</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-700 text-slate-400 text-xs uppercase">
                  <th className="text-left px-4 py-2">Type</th>
                  <th className="text-left px-4 py-2">Reference</th>
                  <th className="text-left px-4 py-2">Date</th>
                  <th className="text-left px-4 py-2">Amount</th>
                  <th className="text-left px-4 py-2">Error</th>
                  <th className="text-right px-4 py-2">Action</th>
                </tr>
              </thead>
              <tbody>
                {data!.failures.map((f) => (
                  <tr key={f.id} className="border-b border-slate-700/50 hover:bg-slate-700/20">
                    <td className="px-4 py-3">
                      <span className="px-2 py-0.5 rounded text-xs bg-slate-700 text-slate-300">
                        {MODEL_LABELS[f.model] ?? f.model}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-white font-mono text-xs">{f.number || f.id.slice(0, 8)}</td>
                    <td className="px-4 py-3 text-slate-400">{f.date}</td>
                    <td className="px-4 py-3 text-slate-300">{f.amount ? `₦${Number(f.amount).toLocaleString()}` : '—'}</td>
                    <td className="px-4 py-3 text-red-400 text-xs max-w-xs truncate" title={f.error}>{f.error}</td>
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={() => handleRetry(f)}
                        disabled={retrying === f.id}
                        className="flex items-center gap-1 ml-auto px-2.5 py-1 rounded bg-indigo-600 hover:bg-indigo-500 text-white text-xs disabled:opacity-50"
                      >
                        <RotateCcw size={12} className={retrying === f.id ? 'animate-spin' : ''} />
                        Retry
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : !loading && (
        <div className="rounded-xl bg-slate-800 border border-slate-700 p-8 text-center">
          <CheckCircle size={40} className="text-green-400 mx-auto mb-3" />
          <p className="text-white font-medium">All GL entries posted successfully</p>
          <p className="text-slate-400 text-sm mt-1">No failed or misconfigured postings</p>
        </div>
      )}
    </div>
  )
}
