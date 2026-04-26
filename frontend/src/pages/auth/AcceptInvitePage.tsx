/**
 * AcceptInvitePage — handles invitation accept/reject flows from emailed links.
 *
 * Routes:
 *   /accept-invite/:token  — prompts the user to accept
 *   /reject-invite/:token  — auto-rejects and shows confirmation
 */

import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { CheckCircle, XCircle, Loader2, Mail } from 'lucide-react'
import { orgApi } from '@/services/api'
import { useAuthStore } from '@/store/authStore'
import toast from 'react-hot-toast'

type InviteData = {
  token: string
  email: string
  role: string
  org_name: string
  status: string
  invited_by_name: string
  expires_at: string
}

type PageMode = 'accept' | 'reject'

export default function AcceptInvitePage({ mode }: { mode: PageMode }) {
  const { token } = useParams<{ token: string }>()
  const navigate = useNavigate()
  const { isAuthenticated } = useAuthStore()

  const [invite, setInvite] = useState<InviteData | null>(null)
  const [loading, setLoading] = useState(true)
  const [acting, setActing] = useState(false)
  const [done, setDone] = useState<'accepted' | 'rejected' | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!token) return
    orgApi.previewInvitation(token)
      .then(({ data }) => setInvite(data))
      .catch(() => setError('This invitation link is invalid or has expired.'))
      .finally(() => setLoading(false))
  }, [token])

  // Auto-reject mode: reject immediately on page load
  useEffect(() => {
    if (mode === 'reject' && invite && invite.status === 'pending') {
      handleReject()
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [invite])

  const handleAccept = async () => {
    if (!isAuthenticated) {
      // Redirect to login, then come back
      navigate(`/login?next=/accept-invite/${token}`)
      return
    }
    setActing(true)
    try {
      await orgApi.acceptInvitation(token!)
      setDone('accepted')
      toast.success(`Joined ${invite?.org_name}!`)
      // Give a moment for the user to read the success state, then redirect
      setTimeout(() => navigate('/dashboard'), 2000)
    } catch (err: any) {
      const msg = err?.response?.data?.error?.message ?? err?.response?.data?.error ?? 'Could not accept invitation.'
      toast.error(msg)
    } finally {
      setActing(false)
    }
  }

  const handleReject = async () => {
    setActing(true)
    try {
      await orgApi.rejectInvitation(token!)
      setDone('rejected')
    } catch {
      setDone('rejected') // reject silently either way
    } finally {
      setActing(false)
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-surface-950 flex items-center justify-center">
        <Loader2 size={32} className="animate-spin text-brand-500" />
      </div>
    )
  }

  if (error || !invite) {
    return (
      <div className="min-h-screen bg-surface-950 flex items-center justify-center p-6">
        <div className="bg-surface-800 border border-surface-700 rounded-2xl p-8 max-w-md w-full text-center space-y-4">
          <XCircle size={40} className="mx-auto text-red-400" />
          <h1 className="text-xl font-semibold text-white">Invalid Invitation</h1>
          <p className="text-slate-400 text-sm">{error || 'This invitation link is invalid or has already been used.'}</p>
          <button onClick={() => navigate('/login')} className="btn-primary mx-auto">Go to Login</button>
        </div>
      </div>
    )
  }

  if (done === 'accepted') {
    return (
      <div className="min-h-screen bg-surface-950 flex items-center justify-center p-6">
        <div className="bg-surface-800 border border-surface-700 rounded-2xl p-8 max-w-md w-full text-center space-y-4">
          <CheckCircle size={40} className="mx-auto text-emerald-400" />
          <h1 className="text-xl font-semibold text-white">You're in!</h1>
          <p className="text-slate-400 text-sm">You've joined <strong className="text-white">{invite.org_name}</strong> as <strong className="text-white">{invite.role}</strong>.</p>
          <p className="text-slate-500 text-xs">Redirecting to dashboard…</p>
        </div>
      </div>
    )
  }

  if (done === 'rejected') {
    return (
      <div className="min-h-screen bg-surface-950 flex items-center justify-center p-6">
        <div className="bg-surface-800 border border-surface-700 rounded-2xl p-8 max-w-md w-full text-center space-y-4">
          <XCircle size={40} className="mx-auto text-slate-400" />
          <h1 className="text-xl font-semibold text-white">Invitation Declined</h1>
          <p className="text-slate-400 text-sm">You've declined the invitation to join <strong className="text-white">{invite.org_name}</strong>.</p>
          <button onClick={() => navigate('/login')} className="btn-secondary mx-auto">Back to Login</button>
        </div>
      </div>
    )
  }

  const isExpiredOrUsed = invite.status !== 'pending'

  return (
    <div className="min-h-screen bg-surface-950 flex items-center justify-center p-6">
      <div className="bg-surface-800 border border-surface-700 rounded-2xl p-8 max-w-md w-full space-y-6">
        <div className="text-center space-y-1">
          <div className="w-12 h-12 rounded-full bg-brand-500/20 flex items-center justify-center mx-auto mb-3">
            <Mail size={22} className="text-brand-400" />
          </div>
          <h1 className="text-xl font-semibold text-white">You've been invited</h1>
          <p className="text-slate-400 text-sm">
            <strong className="text-white">{invite.invited_by_name}</strong> has invited you to join
          </p>
        </div>

        <div className="bg-surface-700/50 rounded-xl p-4 space-y-2">
          <p className="text-white font-semibold text-lg">{invite.org_name}</p>
          <p className="text-slate-400 text-sm">Role: <span className="text-white capitalize">{invite.role}</span></p>
          <p className="text-slate-400 text-sm">Sent to: <span className="text-white">{invite.email}</span></p>
        </div>

        {isExpiredOrUsed ? (
          <div className="text-center space-y-2">
            <p className="text-amber-400 text-sm">This invitation has already been {invite.status}.</p>
            <button onClick={() => navigate('/login')} className="btn-secondary mx-auto">Go to Login</button>
          </div>
        ) : (
          <div className="flex gap-3">
            <button
              onClick={handleReject}
              disabled={acting}
              className="btn-secondary flex-1 justify-center"
            >
              Decline
            </button>
            <button
              onClick={handleAccept}
              disabled={acting}
              className="btn-primary flex-1 justify-center"
            >
              {acting ? <Loader2 size={16} className="animate-spin" /> : 'Accept & Join'}
            </button>
          </div>
        )}

        {!isAuthenticated && !isExpiredOrUsed && (
          <p className="text-slate-500 text-xs text-center">
            You'll need to log in or create an account to accept.
          </p>
        )}
      </div>
    </div>
  )
}
