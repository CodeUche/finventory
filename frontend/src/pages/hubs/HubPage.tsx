/**
 * HubPage — landing page for one sidebar group: a grid of big tiles, one per
 * page in the group that the signed-in user is allowed to open.
 */
import { Link, Navigate, useParams } from 'react-router-dom'
import { navGroups } from '@/components/layout/Sidebar'
import { useCanSeeNavItem } from '@/lib/navAccess'
import { hubBySlug } from './hubConfig'
import '@/styles/ds.css'

export default function HubPage() {
  const { slug } = useParams()
  const hub = hubBySlug(slug)
  const { canSeeItem } = useCanSeeNavItem()
  if (!hub) return <Navigate to="/dashboard" replace />

  const group = navGroups.find((g) => g.label === hub.label)
  const items = (group?.items ?? []).filter((i) => canSeeItem(i.module, i.ownerOnly, i.partnerOnly, i.businessType))

  return (
    <div className="ds">
      <header className="ds-head">
        <div>
          <h1>{hub.title}</h1>
          <p>{hub.blurb}</p>
        </div>
      </header>

      {items.length === 0 ? (
        <div className="ds-empty"><p>Nothing here is available on your plan or role yet.</p></div>
      ) : (
        <nav className="ds-hub" aria-label={`${hub.title} pages`}>
          {items.map((item) => (
            <Link key={item.href} to={item.href} className="ds-hub-tile">
              <item.icon size={26} className="ds-hub-ico" />
              <span>{item.name}</span>
            </Link>
          ))}
        </nav>
      )}
    </div>
  )
}
