/**
 * HubPage — landing page for one sidebar group: a grid of big tiles, one per
 * page in the group that the signed-in user is allowed to open.
 */
import { Link, Navigate, useParams } from 'react-router-dom'
import { navGroups } from '@/components/layout/Sidebar'
import { useCanSeeNavItem } from '@/lib/navAccess'
import { hubBySlug, HUB_TILES } from './hubConfig'
import '@/styles/ds.css'
import '@/styles/hub.css'

export default function HubPage() {
  const { slug } = useParams()
  const hub = hubBySlug(slug)
  const { canSeeItem } = useCanSeeNavItem()
  if (!hub) return <Navigate to="/dashboard" replace />

  const group = navGroups.find((g) => g.label === hub.label)
  const visible = (group?.items ?? []).filter((i) => canSeeItem(i.module, i.ownerOnly, i.partnerOnly, i.businessType))
  // Designer's order and wording where the designer drew this hub; anything else follows, with its menu name.
  const drawn = HUB_TILES[hub.slug] ?? []
  const items = [
    ...drawn.flatMap((d) => {
      const m = visible.find((v) => v.href === d.href)
      return m ? [{ href: m.href, name: d.label }] : []
    }),
    ...visible.filter((v) => !drawn.some((d) => d.href === v.href)).map((v) => ({ href: v.href, name: v.name })),
  ]

  return (
    <div className="ds ds-hubpage">
      <header className="ds-head">
        <div>
          <h1>{hub.title}</h1>
        </div>
      </header>

      {items.length === 0 ? (
        <div className="ds-empty"><p>Nothing here is available on your plan or role yet.</p></div>
      ) : (
        <nav className="ds-hub ds-hub-panel" aria-label={`${hub.title} pages`}>
          {items.map((item) => (
            <Link key={item.href} to={item.href} className="ds-hub-tile">
              <span>{item.name}</span>
            </Link>
          ))}
        </nav>
      )}
    </div>
  )
}
