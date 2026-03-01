import { useEffect, useState } from 'react'
import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'
import TopBar from './TopBar'
import { useInactivityTimeout } from '@/hooks/useInactivityTimeout'
import { useAuthStore } from '@/store/authStore'
import { setActiveCurrency } from '@/lib/utils'

export default function AppLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  useInactivityTimeout()
  const organisation = useAuthStore((s) => s.organisation)

  // Keep formatCurrency in sync with the org's currency setting
  useEffect(() => {
    if (organisation?.currency) setActiveCurrency(organisation.currency)
  }, [organisation?.currency])

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
        <main className="flex-1 overflow-y-auto p-4 lg:p-6 animate-fade-in">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
