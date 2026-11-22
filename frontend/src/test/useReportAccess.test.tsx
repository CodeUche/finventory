import { describe, it, expect, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useReportAccess } from '@/hooks/useReportAccess'
import { useAuthStore } from '@/store/authStore'

function setMember(role: string, perms: Record<string, string>, planModules: string[] | null = null) {
  useAuthStore.setState({
    memberRole: role,
    modulePermissions: perms as never,
    planModules,
    user: { is_superuser: false } as never,
  })
}

describe('useReportAccess', () => {
  beforeEach(() => {
    useAuthStore.setState({ memberRole: null, modulePermissions: {}, planModules: null, user: null })
  })

  it('a reports-only staff member can call none of the gated legacy routes', () => {
    setMember('staff', { reports: 'view' })
    const a = renderHook(() => useReportAccess()).result.current
    for (const k of [
      'arAging', 'apAging', 'vatSummary', 'expenseBreakdown', 'customerBalance', 'customerDetails',
      'productDetails', 'inventoryValuation', 'paymentsByCustomer', 'accountStatement', 'customerInvoices',
    ] as const) {
      expect(a[k], k).toBe(false)
    }
  })

  it('the matching tick opens only its own route', () => {
    setMember('staff', { reports: 'view', sales: 'view', customers: 'view' })
    const a = renderHook(() => useReportAccess()).result.current
    expect(a.arAging).toBe(true)
    expect(a.customerDetails).toBe(true)
    expect(a.paymentsByCustomer).toBe(true)
    expect(a.apAging).toBe(false)
    expect(a.expenseBreakdown).toBe(false)
  })

  it('accounting and tax reports also need the accountant role', () => {
    setMember('staff', { reports: 'view', accounting: 'edit', tax: 'edit' })
    let a = renderHook(() => useReportAccess()).result.current
    expect(a.accountStatement).toBe(false)
    expect(a.vatSummary).toBe(false)
    setMember('accountant', { reports: 'view', accounting: 'view', tax: 'view' })
    a = renderHook(() => useReportAccess()).result.current
    expect(a.accountStatement).toBe(true)
    expect(a.vatSummary).toBe(true)
  })

  it('bills ageing needs the bills plan for non-admins', () => {
    setMember('staff', { reports: 'view', bills: 'view' }, ['sales'])
    expect(renderHook(() => useReportAccess()).result.current.apAging).toBe(false)
    setMember('staff', { reports: 'view', bills: 'view' }, ['sales', 'bills'])
    expect(renderHook(() => useReportAccess()).result.current.apAging).toBe(true)
  })

  it('cost-bearing reports are owner/admin only, even with the inventory tick', () => {
    setMember('manager', { reports: 'view', inventory: 'edit' })
    let a = renderHook(() => useReportAccess()).result.current
    expect(a.productDetails).toBe(false)
    expect(a.inventoryValuation).toBe(false)
    setMember('admin', {})
    a = renderHook(() => useReportAccess()).result.current
    expect(a.productDetails).toBe(true)
    expect(a.inventoryValuation).toBe(true)
  })

  it('owners see everything regardless of plan', () => {
    setMember('owner', {}, ['sales'])
    const a = renderHook(() => useReportAccess()).result.current
    expect(a.apAging && a.accountStatement && a.vatSummary).toBe(true)
  })

  it('the Profit and Loss (ledger based: payroll, bills, depreciation) needs the Accounting tick and the accountant role', () => {
    setMember('staff', { reports: 'view' })
    expect(renderHook(() => useReportAccess()).result.current.profitLoss).toBe(false)
    setMember('staff', { reports: 'view', accounting: 'edit' })
    expect(renderHook(() => useReportAccess()).result.current.profitLoss).toBe(false)
    setMember('accountant', { reports: 'view', accounting: 'view' })
    expect(renderHook(() => useReportAccess()).result.current.profitLoss).toBe(true)
    setMember('owner', {}, ['sales'])
    expect(renderHook(() => useReportAccess()).result.current.profitLoss).toBe(true)
  })
})
