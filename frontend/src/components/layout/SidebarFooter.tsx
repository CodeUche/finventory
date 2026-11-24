import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import { Shield } from 'lucide-react'
import { cn } from '@/lib/utils'
import { DesignerIcon } from '@/assets/designer-icons'

export const FOOTER_KEY = 'audity-sidebar-foot-open'

function readOpen(): boolean {
  try {
    return localStorage.getItem(FOOTER_KEY) !== '0'
  } catch {
    return true // storage blocked: default = expanded
  }
}

interface Props {
  isSuperuser: boolean
  /** True when the whole sidebar is folded into the icon rail: always icons only. */
  rail: boolean
  onSignOut: () => void
}

/**
 * Bottom block of the sidebar: Platform Admin (superusers only) and Sign Out.
 * Small and quiet. A handle folds it into one row of icon buttons; the choice is
 * remembered on this device. Icon-only buttons keep their names via aria-label.
 */
export default function SidebarFooter({ isSuperuser, rail, onSignOut }: Props) {
  const [open, setOpen] = useState<boolean>(readOpen)
  const toggle = () => setOpen((v) => {
    const next = !v
    try { localStorage.setItem(FOOTER_KEY, next ? '1' : '0') } catch { /* storage blocked: still works */ }
    return next
  })
  const iconOnly = rail || !open

  return (
    <div className={cn('sh-foot', iconOnly && 'sh-foot-icons')} data-foot={iconOnly ? 'icons' : 'full'}>
      {!rail && (
        <button
          type="button"
          onClick={toggle}
          className="sh-foot-handle"
          aria-expanded={open}
          aria-label={open ? 'Collapse account actions' : 'Expand account actions'}
          title={open ? 'Collapse' : 'Expand'}
        >
          <DesignerIcon name="chevron-down" size={16} className={cn('sh-foot-chev', !open && 'sh-foot-chev-up')} />
        </button>
      )}
      <div className="sh-foot-list">
        {isSuperuser && (
          <NavLink
            to="/platform-admin"
            title="Platform admin"
            aria-label={iconOnly ? 'Platform admin' : undefined}
            className={({ isActive }) => cn('sh-foot-row', isActive && 'sh-foot-row-on')}
          >
            <Shield size={18} className="sh-ico shrink-0" />
            {!iconOnly && <span className="sh-label">Platform Admin</span>}
          </NavLink>
        )}
        <button
          type="button"
          onClick={onSignOut}
          title="Sign out"
          aria-label={iconOnly ? 'Sign out' : undefined}
          className="sh-foot-row sh-foot-danger"
        >
          <DesignerIcon name="sign-out" size={18} className="sh-ico shrink-0" />
          {!iconOnly && <span className="sh-label">Sign Out</span>}
        </button>
      </div>
    </div>
  )
}
