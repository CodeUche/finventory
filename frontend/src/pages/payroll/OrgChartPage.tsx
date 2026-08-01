import { useCallback, useEffect, useState } from 'react'
import { ChevronDown, ChevronRight, GitBranch, Loader2 } from 'lucide-react'
import toast from 'react-hot-toast'

import { payrollApi } from '@/services/api'
import type { OrgChartNode } from '@/types'

function initials(name: string) {
  return name.split(' ').filter(Boolean).slice(0, 2).map((p) => p[0]).join('').toUpperCase()
}

function Node({ node, depth }: { node: OrgChartNode; depth: number }) {
  const [open, setOpen] = useState(depth < 2)
  const hasChildren = node.children.length > 0

  return (
    <div className="relative">
      <div
        className="flex items-center gap-2.5 py-1.5"
        style={{ paddingLeft: depth * 22 }}
      >
        {hasChildren ? (
          <button
            onClick={() => setOpen((o) => !o)}
            className="p-0.5 rounded hover:bg-white/5 text-slate-400 shrink-0"
            aria-label={open ? 'Collapse' : 'Expand'}
          >
            {open ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
          </button>
        ) : (
          <span className="w-5 shrink-0" />
        )}

        <div className="flex items-center gap-2.5 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 min-w-0 flex-1">
          <div className="w-8 h-8 rounded-full bg-brand-500/15 text-brand-400 grid place-items-center text-[11px] font-bold shrink-0">
            {initials(node.name)}
          </div>
          <div className="min-w-0">
            <p className="text-sm text-white font-medium truncate">{node.name}</p>
            <p className="text-[11px] text-slate-400 font-mono truncate">
              {node.job_title}{node.department ? ` · ${node.department}` : ''}
            </p>
          </div>
          {hasChildren && (
            <span className="ml-auto text-[10px] font-mono px-1.5 py-0.5 rounded bg-white/5 text-slate-400 shrink-0">
              {node.children.length} report{node.children.length === 1 ? '' : 's'}
            </span>
          )}
        </div>
      </div>

      {open && hasChildren && (
        <div>
          {node.children.map((child) => (
            <Node key={child.id} node={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
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
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <GitBranch className="w-6 h-6 text-brand-400" />
          Org chart
        </h1>
        <p className="text-sm text-slate-400 mt-0.5">
          {total} active employee{total === 1 ? '' : 's'} · built from the reporting line on each
          employee record
        </p>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="w-6 h-6 animate-spin text-brand-400" />
        </div>
      ) : roots.length === 0 ? (
        <div className="card p-10 text-center">
          <p className="text-sm text-slate-400">
            No employees yet. Add employees and set a manager on each to build the chart.
          </p>
        </div>
      ) : (
        <div className="card p-4">
          {roots.length > 1 && (
            <p className="text-[11px] text-slate-500 mb-3">
              {roots.length} employees have no manager set — they appear as separate roots.
            </p>
          )}
          {roots.map((node) => (
            <Node key={node.id} node={node} depth={0} />
          ))}
        </div>
      )}
    </div>
  )
}
