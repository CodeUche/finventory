import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link, useLocation } from 'react-router-dom'

export interface MiniFlyoutItem {
  name: string
  to: string
  icon: React.ElementType
  active?: boolean
}

/**
 * One icon in the collapsed sidebar rail that opens a small list of the links
 * in that group. Without it, every group that was folded when the rail was
 * collapsed simply disappeared and its pages could not be reached.
 */
export default function MiniFlyout({
  icon: Icon, label, items, active,
}: { icon: React.ElementType; label: string; items: MiniFlyoutItem[]; active?: boolean }) {
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState({ top: 0, left: 0 })
  const btn = useRef<HTMLButtonElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  const { pathname, search } = useLocation()

  // A click on a link changes the route: close the list.
  useEffect(() => { setOpen(false) }, [pathname, search])

  useLayoutEffect(() => {
    if (!open || !btn.current) return
    const r = btn.current.getBoundingClientRect()
    // Keep the list on screen: if it would run off the bottom, move it up.
    const room = window.innerHeight - 16
    const est = Math.min(items.length * 40 + 52, room)
    setPos({ top: Math.max(8, Math.min(r.top, room - est)), left: r.right + 8 })
  }, [open, items.length])

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node
      if (panel.current?.contains(t) || btn.current?.contains(t)) return
      setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { setOpen(false); btn.current?.focus() }
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey) }
  }, [open])

  const light = typeof document !== 'undefined' && document.documentElement.classList.contains('light')

  return (
    <>
      <button
        ref={btn}
        type="button"
        className={`sh-row${active ? ' sh-row-on' : ''}`}
        title={label}
        aria-label={`${label} menu`}
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <Icon size={20} className="sh-ico shrink-0" />
      </button>
      {open && createPortal(
        <div
          ref={panel}
          role="menu"
          aria-label={label}
          style={{
            position: 'fixed', top: pos.top, left: pos.left, zIndex: 60, minWidth: 220, maxHeight: 'calc(100vh - 16px)',
            overflowY: 'auto', padding: 8, borderRadius: 12,
            background: light ? '#FFFFFF' : '#13244B',
            border: light ? '1.5px solid #B9B4F2' : '1.5px solid rgba(164,153,255,.35)',
            boxShadow: '0 12px 32px rgba(0,0,0,.35)',
          }}
        >
          <p style={{ margin: '4px 8px 6px', fontSize: 12, fontWeight: 700, color: light ? '#55545C' : '#A9A6C4' }}>{label}</p>
          {items.map((it) => (
            <Link
              key={it.to + it.name}
              to={it.to}
              role="menuitem"
              className="flex items-center gap-2 rounded-lg px-2 py-2 text-sm"
              style={{
                color: light ? '#1C1B1F' : '#F4F2FF',
                background: it.active ? (light ? '#D2DEFA' : 'rgba(125,140,255,.22)') : 'transparent',
                fontWeight: it.active ? 700 : 500,
              }}
            >
              <it.icon size={16} className="shrink-0" />
              <span>{it.name}</span>
            </Link>
          ))}
        </div>,
        document.body,
      )}
    </>
  )
}
