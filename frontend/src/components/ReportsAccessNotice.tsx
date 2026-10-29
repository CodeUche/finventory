import { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import { teamApi } from '@/services/api'
import { useAuthStore } from '@/store/authStore'

interface Member { id: string; name: string; role: string }

/** Reports became a per-person tick and nobody was granted it automatically.
 *  This tells the owner who cannot open Reports and lets them fix it in one tap.
 *  "Not now" is remembered per business, on this device only. */
export default function ReportsAccessNotice() {
  const { organisation, memberRole } = useAuthStore()
  const isManager = memberRole === 'owner' || memberRole === 'admin'
  const dismissKey = `audity-reports-notice-${organisation?.id ?? 'none'}`
  const [members, setMembers] = useState<Member[]>([])
  const [busy, setBusy] = useState(false)
  const [hidden, setHidden] = useState(() => {
    try { return localStorage.getItem(dismissKey) === '1' } catch { return false }
  })

  useEffect(() => {
    if (!isManager || hidden) return
    teamApi.reportsAccessGap().then(({ data }) => setMembers(data.members ?? [])).catch(() => {})
  }, [isManager, hidden])

  if (!isManager || hidden || members.length === 0) return null

  const grant = async () => {
    setBusy(true)
    try {
      const { data } = await teamApi.grantReports(members.map((m) => m.id))
      toast.success(`Reports access given to ${data.granted} ${data.granted === 1 ? 'person' : 'people'}`)
      setMembers([])
    } catch {
      toast.error('Could not give Reports access. Try again, or use Settings > Team.')
    } finally { setBusy(false) }
  }
  const dismiss = () => {
    try { localStorage.setItem(dismissKey, '1') } catch { /* private window: it just comes back next time */ }
    setHidden(true)
  }

  return (
    <div className="card p-4 flex flex-col sm:flex-row sm:items-center gap-3" role="status">
      <div className="flex-1 min-w-0">
        <p className="text-sm font-semibold text-white">
          {members.length} {members.length === 1 ? 'person on your team cannot' : 'people on your team cannot'} open Reports
        </p>
        <p className="text-xs text-slate-400 mt-0.5 truncate">
          {members.map((m) => m.name).join(', ')}. Reports access is now given person by person.
        </p>
      </div>
      <div className="flex gap-2 shrink-0">
        <button className="btn-primary text-sm" disabled={busy} onClick={grant}>Give them Reports access</button>
        <button className="btn-secondary text-sm" disabled={busy} onClick={dismiss}>Not now</button>
      </div>
    </div>
  )
}
