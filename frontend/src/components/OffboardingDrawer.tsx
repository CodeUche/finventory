import { useEffect, useState } from 'react'
import { X, Loader2, CheckCircle2, AlertTriangle, Banknote, ClipboardCheck } from 'lucide-react'
import toast from 'react-hot-toast'
import { confirmDialog } from '@/lib/dialog'
import { hrApi } from '@/services/hrApi'
import { formatDate } from '@/lib/utils'

interface ChecklistItem {
  id: string
  item_name: string
  department: string
  is_cleared: boolean
  cleared_by: string | null
  cleared_at: string | null
}

interface OffboardingCase {
  id: string
  employee: string
  employee_name: string
  reason: string
  last_working_day: string
  status: 'initiated' | 'in_progress' | 'completed' | 'cancelled'
  final_settlement_run: string | null
  checklist_items: ChecklistItem[]
  clearance_progress: { cleared: number; total: number }
  notes: string
}

const REASON_LABELS: Record<string, string> = {
  resignation: 'Resignation', dismissal_misconduct: 'Dismissal (misconduct)',
  dismissal_performance: 'Dismissal (performance)', redundancy: 'Redundancy',
  contract_end: 'Contract end', retirement: 'Retirement', death_in_service: 'Death in service',
}

const STATUS_BADGE: Record<string, string> = {
  initiated: 'badge-slate', in_progress: 'badge-orange',
  completed: 'badge-green', cancelled: 'badge-slate',
}

/**
 * Slide-in drawer for one offboarding case: clearance checklist, final
 * settlement trigger, and the explicit "complete" action that revokes portal
 * access for this org only. Mirrors AccountDrilldownDrawer's shell pattern
 * (fixed inset-0 flex justify-end, slide-in panel).
 */
export default function OffboardingDrawer({
  employeeId, employeeName, existingCaseId, onClose, onChanged,
}: {
  employeeId: string
  employeeName: string
  existingCaseId?: string | null
  onClose: () => void
  onChanged: () => void
}) {
  const [loading, setLoading] = useState(true)
  const [caseData, setCaseData] = useState<OffboardingCase | null>(null)
  const [creating, setCreating] = useState(false)
  const [busy, setBusy] = useState(false)

  const [newCase, setNewCase] = useState({
    reason: 'resignation', last_working_day: new Date().toISOString().split('T')[0],
    notice_period_days: '0', notes: '',
  })

  const load = async () => {
    setLoading(true)
    try {
      if (existingCaseId) {
        const { data } = await hrApi.offboardingCase(existingCaseId)
        setCaseData(data)
      } else {
        const { data } = await hrApi.offboardingCases({ employee: employeeId })
        const rows = Array.isArray(data) ? data : (data.results ?? [])
        const open = rows.find((c: OffboardingCase) => c.status !== 'completed' && c.status !== 'cancelled')
        setCaseData(open ?? null)
      }
    } catch {
      toast.error('Could not load the offboarding case')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [employeeId, existingCaseId])

  const handleCreateCase = async () => {
    setCreating(true)
    try {
      await hrApi.createOffboardingCase({
        employee: employeeId,
        reason: newCase.reason,
        last_working_day: newCase.last_working_day,
        notice_period_days: parseInt(newCase.notice_period_days) || 0,
        notes: newCase.notes,
      })
      toast.success('Offboarding case created')
      await load()
      onChanged()
    } catch (err: unknown) {
      const apiErr = (err as { response?: { data?: { error?: unknown } } })?.response?.data?.error
      const msg = typeof apiErr === 'string' ? apiErr : ((apiErr as { message?: string })?.message ?? 'Could not create the case')
      toast.error(msg)
    } finally {
      setCreating(false)
    }
  }

  const handleClearItem = async (itemId: string) => {
    if (!caseData) return
    try {
      await hrApi.clearChecklistItem(caseData.id, itemId)
      await load()
    } catch {
      toast.error('Could not clear this item')
    }
  }

  const handleRunFinalSettlement = async () => {
    if (!caseData) return
    const ok = await confirmDialog(
      'Raise a final settlement payroll run for this employee? This includes unused-leave '
      + 'payout or recovery, and any configured gratuity.',
      { confirmText: 'Run final settlement' },
    )
    if (!ok) return
    setBusy(true)
    try {
      await hrApi.runFinalSettlement(caseData.id)
      toast.success('Final settlement run created')
      await load()
    } catch (err: unknown) {
      const apiErr = (err as { response?: { data?: { error?: unknown } } })?.response?.data?.error
      const msg = typeof apiErr === 'string' ? apiErr : ((apiErr as { message?: string })?.message ?? 'Could not run final settlement')
      toast.error(msg)
    } finally {
      setBusy(false)
    }
  }

  const handleComplete = async () => {
    if (!caseData) return
    const ok = await confirmDialog(
      `Finalize offboarding for ${employeeName}? This deactivates their portal access `
      + `for this organisation only — their user account and any other organisation `
      + `memberships are untouched. This cannot be undone from here.`,
      { danger: true, confirmText: 'Complete offboarding' },
    )
    if (!ok) return
    setBusy(true)
    try {
      await hrApi.completeOffboarding(caseData.id)
      toast.success('Offboarding completed — portal access revoked for this organisation')
      await load()
      onChanged()
    } catch {
      toast.error('Could not complete offboarding')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50" onClick={onClose}>
      <div
        className="w-full max-w-lg h-full bg-surface-900 border-l border-surface-700 overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 bg-surface-900 border-b border-surface-700 px-5 py-4 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-bold text-white">Offboard — {employeeName}</h2>
            <p className="text-xs text-slate-400">Exit workflow and clearance checklist</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white"><X size={18} /></button>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-24 text-slate-400"><Loader2 className="animate-spin" /></div>
        ) : !caseData ? (
          <div className="p-5 space-y-4">
            <p className="text-sm text-slate-400">No open offboarding case for this employee. Start one below.</p>
            <div>
              <label className="text-xs text-slate-400 mb-1 block">Reason</label>
              <select className="input" value={newCase.reason} onChange={(e) => setNewCase({ ...newCase, reason: e.target.value })}>
                {Object.entries(REASON_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs text-slate-400 mb-1 block">Last working day</label>
              <input
                type="date" className="input"
                value={newCase.last_working_day}
                onChange={(e) => setNewCase({ ...newCase, last_working_day: e.target.value })}
              />
            </div>
            <div>
              <label className="text-xs text-slate-400 mb-1 block">Notice period (days)</label>
              <input
                type="text" inputMode="numeric" className="input"
                value={newCase.notice_period_days}
                onChange={(e) => setNewCase({ ...newCase, notice_period_days: e.target.value })}
              />
            </div>
            <div>
              <label className="text-xs text-slate-400 mb-1 block">Notes</label>
              <input className="input" placeholder="Optional" value={newCase.notes} onChange={(e) => setNewCase({ ...newCase, notes: e.target.value })} />
            </div>
            <p className="text-[11px] text-slate-500">
              Creating this case does NOT revoke access — even with a future last working day,
              nothing is deactivated until you explicitly complete the case.
            </p>
            <button onClick={handleCreateCase} disabled={creating} className="btn-primary w-full justify-center flex items-center gap-2">
              {creating && <Loader2 className="w-4 h-4 animate-spin" />}
              Start offboarding
            </button>
          </div>
        ) : (
          <div className="p-5 space-y-5">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-white font-medium">{REASON_LABELS[caseData.reason] ?? caseData.reason}</p>
                <p className="text-xs text-slate-400">Last working day: {formatDate(caseData.last_working_day)}</p>
              </div>
              <span className={STATUS_BADGE[caseData.status] ?? 'badge-slate'}>{caseData.status.replace('_', ' ')}</span>
            </div>

            <div>
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                  <ClipboardCheck className="w-3.5 h-3.5" /> Clearance checklist
                </p>
                <span className="text-xs font-mono text-slate-400">
                  {caseData.clearance_progress.cleared} / {caseData.clearance_progress.total}
                </span>
              </div>
              <div className="space-y-1.5">
                {caseData.checklist_items.map((item) => (
                  <button
                    key={item.id}
                    onClick={() => !item.is_cleared && handleClearItem(item.id)}
                    disabled={item.is_cleared || caseData.status === 'completed'}
                    className={`w-full flex items-center gap-2.5 p-2.5 rounded-lg border text-left text-sm transition-colors ${
                      item.is_cleared
                        ? 'bg-emerald-500/5 border-emerald-500/20 text-emerald-300 cursor-default'
                        : 'bg-white/[0.02] border-white/5 text-slate-300 hover:bg-white/[0.05]'
                    }`}
                  >
                    {item.is_cleared
                      ? <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-400" />
                      : <span className="w-4 h-4 shrink-0 rounded-full border-2 border-slate-500" />}
                    <span className="flex-1">{item.item_name}</span>
                    {item.department && <span className="text-[10px] text-slate-500">{item.department}</span>}
                  </button>
                ))}
              </div>
            </div>

            <div className="border-t border-white/5 pt-4 space-y-2">
              <button
                onClick={handleRunFinalSettlement}
                disabled={busy || !!caseData.final_settlement_run}
                className="btn-secondary w-full justify-center flex items-center gap-2 text-sm"
              >
                <Banknote className="w-4 h-4" />
                {caseData.final_settlement_run ? 'Final settlement already raised' : 'Run final settlement'}
              </button>

              {caseData.status !== 'completed' && (
                <button
                  onClick={handleComplete}
                  disabled={busy}
                  className="w-full justify-center flex items-center gap-2 text-sm py-2.5 rounded-xl bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors"
                >
                  <AlertTriangle className="w-4 h-4" />
                  Complete offboarding (revokes portal access)
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
