/**
 * Hard re-acceptance gate. Blocks the app when the signed-in user hasn't
 * accepted the CURRENT legal version (Terms / Privacy / DPA) — e.g. after the
 * documents are updated, or for accounts created before clickwrap existed.
 *
 * The backend returns `current_terms_version` (required) and the user's
 * `terms_accepted_version` on the profile; when they differ, this modal must be
 * resolved before continuing. Accept records acceptance; Reject signs out.
 * Superusers (internal admins) are exempt.
 */
import { useEffect, useState } from 'react'
import { confirmDialog } from '@/lib/dialog'
import { Loader2, ShieldCheck } from 'lucide-react'
import toast from 'react-hot-toast'
import { authApi } from '@/services/api'
import { useAuthStore } from '@/store/authStore'

export default function TermsGateModal() {
  const user = useAuthStore((s) => s.user)
  const updateUser = useAuthStore((s) => s.updateUser)
  const logout = useAuthStore((s) => s.logout)
  const [show, setShow] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!user || user.is_superuser) return
    let active = true
    // Refresh the profile so the version fields are current (older sessions may
    // predate these fields). Non-fatal: a failure just leaves the gate closed.
    authApi.profile().then(({ data }) => {
      if (!active) return
      updateUser(data)
      const current = data.current_terms_version
      const accepted = data.terms_accepted_version
      if (current && accepted !== current) setShow(true)
    }).catch(() => {})
    return () => { active = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id])

  if (!show || !user || user.is_superuser) return null

  const accept = async () => {
    setBusy(true)
    try {
      const { data } = await authApi.acceptTerms()
      updateUser(data)
      setShow(false)
    } catch {
      toast.error('Could not record your acceptance. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  const reject = async () => {
    if ((await confirmDialog('You must accept the updated terms to continue using Audity. Reject and sign out?'))) {
      logout()
    }
  }

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/75 backdrop-blur-sm" />
      <div className="relative card w-full max-w-lg p-7 space-y-5">
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 rounded-xl bg-brand-500/15 flex items-center justify-center shrink-0">
            <ShieldCheck size={22} className="text-brand-400" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-white">We&apos;ve updated our terms</h2>
            <p className="text-xs text-slate-400">Please review and accept to continue.</p>
          </div>
        </div>

        <p className="text-sm text-slate-300 leading-relaxed">
          To keep using Audity, please review and accept our{' '}
          <a href="/legal/terms" target="_blank" rel="noopener" className="text-brand-400 hover:text-brand-300 font-medium">Terms &amp; Conditions</a>,{' '}
          <a href="/legal/privacy" target="_blank" rel="noopener" className="text-brand-400 hover:text-brand-300 font-medium">Privacy Policy</a>, and{' '}
          <a href="/legal/dpa" target="_blank" rel="noopener" className="text-brand-400 hover:text-brand-300 font-medium">Data Processing Agreement</a>.
        </p>

        <div className="flex flex-col-reverse sm:flex-row gap-3 pt-1">
          <button
            onClick={reject}
            disabled={busy}
            className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white hover:border-surface-500 transition-colors text-sm disabled:opacity-50"
          >
            Reject &amp; sign out
          </button>
          <button
            onClick={accept}
            disabled={busy}
            className="btn-primary flex-1 py-2.5 justify-center disabled:opacity-50"
          >
            {busy ? <Loader2 size={16} className="animate-spin" /> : 'I agree — continue'}
          </button>
        </div>
      </div>
    </div>
  )
}
