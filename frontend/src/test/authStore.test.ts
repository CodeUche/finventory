import { describe, it, expect, beforeEach } from 'vitest'
import { useAuthStore } from '@/store/authStore'

// Reset store state between tests
beforeEach(() => {
  useAuthStore.setState({
    user: null,
    tokens: null,
    organisation: null,
    organisations: [],
    isAuthenticated: false,
    rememberMe: false,
    memberRole: null,
    modulePermissions: {},
  })
})

describe('authStore', () => {
  it('starts unauthenticated', () => {
    expect(useAuthStore.getState().isAuthenticated).toBe(false)
    expect(useAuthStore.getState().user).toBeNull()
  })

  it('setAuth marks user as authenticated', () => {
    const user = {
      id: '1', email: 'test@test.com', first_name: 'Test', last_name: 'User',
      is_superuser: false, is_staff: false,
    } as any
    const tokens = { access: 'acc', refresh: 'ref' }
    useAuthStore.getState().setRememberMe(false)
    useAuthStore.getState().setAuth(user, tokens)

    const state = useAuthStore.getState()
    expect(state.isAuthenticated).toBe(true)
    expect(state.user?.email).toBe('test@test.com')
    expect(state.tokens?.access).toBe('acc')
  })

  it('logout clears all auth state', () => {
    const user = { id: '1', email: 'a@b.com', first_name: 'A', last_name: 'B', is_superuser: false, is_staff: false } as any
    useAuthStore.getState().setRememberMe(false)
    useAuthStore.getState().setAuth(user, { access: 'acc', refresh: 'ref' })
    useAuthStore.getState().logout()

    const state = useAuthStore.getState()
    expect(state.isAuthenticated).toBe(false)
    expect(state.user).toBeNull()
    expect(state.tokens).toBeNull()
  })

  it('setMembership stores role and permissions', () => {
    useAuthStore.getState().setMembership('manager', { sales: 'edit', bills: 'view' })
    const state = useAuthStore.getState()
    expect(state.memberRole).toBe('manager')
    expect(state.modulePermissions.sales).toBe('edit')
    expect(state.modulePermissions.bills).toBe('view')
  })

  it('updateUser merges partial user data', () => {
    const user = { id: '1', email: 'a@b.com', first_name: 'Old', last_name: 'Name', is_superuser: false, is_staff: false } as any
    useAuthStore.getState().setRememberMe(false)
    useAuthStore.getState().setAuth(user, { access: 'a', refresh: 'r' })
    useAuthStore.getState().updateUser({ first_name: 'New' })
    expect(useAuthStore.getState().user?.first_name).toBe('New')
  })
})
