import { useEffect, useState } from 'react'
import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'
import TopBar from './TopBar'
import { useInactivityTimeout } from '@/hooks/useInactivityTimeout'
import { useAuthStore } from '@/store/authStore'
import { setActiveCurrency } from '@/lib/utils'
import { useNetworkStatus } from '@/hooks/useNetworkStatus'
import { orgApi } from '@/services/api'
import { WifiOff } from 'lucide-react'
import type { AccessLevel, ModuleKey, ModulePermission } from '@/types'

export default function AppLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  useInactivityTimeout()
  const online = useNetworkStatus()
  const organisation = useAuthStore((s) => s.organisation)
  const setMembership = useAuthStore((s) => s.setMembership)

  // Keep formatCurrency in sync with the org's currency setting
  useEffect(() => {
    if (organisation?.currency) setActiveCurrency(organisation.currency)
  }, [organisation?.currency])

  // Load the current user's role + module permissions from the API
  useEffect(() => {
    if (!organisation?.id) return
    orgApi.myMembership(organisation.id).then(({ data }) => {
      const perms: Partial<Record<ModuleKey, AccessLevel>> = {}
      ;(data.module_permissions as ModulePermission[]).forEach((p) => {
        perms[p.module] = p.access_level
      })
      setMembership(data.role as string, perms)
    }).catch(() => { /* non-fatal — defaults to full access */ })
  }, [organisation?.id, setMembership])

  return (
    <div className="flex h-screen bg-surface-950 overflow-hidden">
      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-20 bg-black/60 backdrop-blur-sm lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />

      {/* Main content */}
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        <TopBar onMenuClick={() => setSidebarOpen(true)} />
        {/* Offline banner */}
        {!online && (
          <div className="flex items-center gap-2 px-4 py-2 bg-amber-500/15 border-b border-amber-500/30 text-amber-400 text-xs font-medium">
            <WifiOff size={13} />
            You&apos;re offline — read-only mode. Changes will be queued and synced automatically when reconnected.
          </div>
        )}
        <main className="flex-1 overflow-y-auto p-4 lg:p-6 animate-fade-in">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
