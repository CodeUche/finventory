import { useCallback, useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import toast from 'react-hot-toast'

import { payrollApi } from '@/services/api'
import type { OrgChartNode } from '@/types'
import '@/styles/orgchart.css'

function initials(name: string) {
  return name.split(' ').filter(Boolean).slice(0, 2).map((p) => p[0]).join('').toUpperCase()
}

function Node({ node, depth }: { node: OrgChartNode; depth: number }) {
  const [open, setOpen] = useState(depth < 2)
  const hasChildren = node.children.length > 0
  return (
    <li>
      <div className="oc-person">
        <div className="oc-avatar" aria-hidden="true">{initials(node.name)}</div>
        <p className="oc-name">{node.name}</p>
        <p className="oc-role">{node.job_title}</p>
        {node.department && <p className="oc-dept">{node.department}</p>}
        {hasChildren && (
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            className="oc-toggle"
            aria-expanded={open}
            aria-label={`${open ? 'Hide' : 'Show'} ${node.children.length} direct report${node.children.length === 1 ? '' : 's'} of ${node.name}`}
          >
            {open ? 'Hide' : 'Show'} {node.children.length} report{node.children.length === 1 ? '' : 's'}
          </button>
        )}
      </div>
      {open && hasChildren && (
        <ul>
          {node.children.map((child) => (
            <Node key={child.id} node={child} depth={depth + 1} />
          ))}
        </ul>
      )}
    </li>
  )
}

export default function OrgChartPage() {
  const [loading, setLoading] = useState(true)
  const [roots, setRoots] = useState<OrgChartNode[]>([])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await payrollApi.orgChart()
      setRoots(Array.isArray(res.data) ? res.data : [])
    } catch {
      toast.error('Could not load the org chart')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const total = (function count(nodes: OrgChartNode[]): number {
    return nodes.reduce((sum, n) => sum + 1 + count(n.children), 0)
  })(roots)

  return (
    <div className="ds">
      <header className="ds-head">
        <div>
          <h1>Organization Chart</h1>
          <p>({total}) active employee{total === 1 ? '' : 's'}</p>
        </div>
      </header>

      {loading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="w-6 h-6 animate-spin text-brand-400" />
        </div>
      ) : roots.length === 0 ? (
        <div className="card oc-empty">
          No Employees Added
          <p className="text-sm mt-3" style={{ color: 'var(--ds-muted)' }}>
            Add employees and set a manager on each to build the chart.
          </p>
        </div>
      ) : (
        <>
          {roots.length > 1 && (
            <p className="text-xs text-slate-500 mb-3">
              {roots.length} employees have no manager set. They appear side by side at the top.
            </p>
          )}
          <div className="oc-scroll">
            <div className="oc-forest">
              {roots.map((node) => (
                <ul key={node.id} className="oc-tree">
                  <Node node={node} depth={0} />
                </ul>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
