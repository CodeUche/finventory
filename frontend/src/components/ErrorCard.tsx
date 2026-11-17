import { AlertTriangle } from 'lucide-react'

/**
 * The "something went wrong" card. Uses the kit colour tokens, so it reads
 * correctly in both the dark and light theme. Used inside the app (the sidebar
 * and top bar stay) and full screen as the last resort.
 */
export default function ErrorCard({
  message, onDashboard, onReload, fullScreen = false,
}: {
  message?: string
  onDashboard: () => void
  onReload: () => void
  fullScreen?: boolean
}) {
  return (
    <div
      role="alert"
      className="flex items-center justify-center p-6"
      style={fullScreen ? { minHeight: '100vh', background: 'var(--ds-row, transparent)' } : { minHeight: '60vh' }}
    >
      <div
        className="w-full max-w-md text-center"
        style={{
          background: 'var(--ds-card)', border: '1.5px solid var(--ds-card-bd)', borderRadius: 16,
          padding: 32, boxShadow: 'var(--ds-shadow)', color: 'var(--ds-ink)',
        }}
      >
        <div
          className="mx-auto mb-4 flex items-center justify-center"
          style={{ width: 48, height: 48, borderRadius: 999, background: 'var(--ds-pill-red-bg)', color: 'var(--ds-pill-red-tx)' }}
        >
          <AlertTriangle size={24} aria-hidden="true" />
        </div>
        <h2 style={{ color: 'var(--ds-title)', fontSize: 20, fontWeight: 700, margin: '0 0 8px' }}>Something went wrong</h2>
        <p style={{ color: 'var(--ds-ink)', fontSize: 14, margin: '0 0 6px' }}>
          This page hit a problem. Your data is safe. Try again, or go back to the dashboard.
        </p>
        {message ? (
          <p style={{ color: 'var(--ds-muted)', fontSize: 12, wordBreak: 'break-word', margin: '0 0 20px' }}>{message}</p>
        ) : <div style={{ height: 14 }} />}
        <div className="flex flex-wrap items-center justify-center gap-3">
          <button type="button" className="btn-primary" onClick={onDashboard}>Go to dashboard</button>
          <button type="button" className="btn-secondary" onClick={onReload}>Reload</button>
        </div>
      </div>
    </div>
  )
}
