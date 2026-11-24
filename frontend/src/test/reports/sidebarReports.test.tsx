import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('@/services/api', async (orig) => {
  const real = await orig<typeof import('@/services/api')>()
  return { ...real, reportApi: { ...real.reportApi, catalog: vi.fn() } }
})
vi.mock('@/lib/navAccess', () => ({
  useCanSeeNavItem: () => ({ canSeeItem: () => true, isOwnerOrAdmin: true }),
}))

import Sidebar from '@/components/layout/Sidebar'
import { useAuthStore } from '@/store/authStore'

describe('Sidebar Reports entry', () => {
  window.matchMedia = ((q: string) => ({ matches: true, media: q, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} })) as never
  it('is ONE flat General Reports link to /reports/all, with no sub-menu or report tree', () => {
    useAuthStore.setState({ memberRole: 'owner', modulePermissions: {}, planModules: null, user: { is_superuser: false } as never })
    render(<MemoryRouter initialEntries={['/reports/all']}><Sidebar open onClose={() => {}} /></MemoryRouter>)
    const links = screen.getAllByRole('link', { name: /General Reports/ })
    expect(links).toHaveLength(1)
    expect(links[0].getAttribute('href')).toBe('/reports/all')
    expect(links[0].className).toContain('sh-row-on')   // lit while on any /reports page
    for (const old of ['Financial Statements', 'Stock Reports', 'Sales by Product', 'Accountant Reports']) {
      expect(screen.queryByText(old)).toBeNull()
    }
    // no expand/collapse button for Reports any more
    expect(screen.queryByRole('button', { name: /General Reports/ })).toBeNull()
  })
})
