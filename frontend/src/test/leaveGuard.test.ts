import { describe, it, expect, afterEach } from 'vitest'
import { setLeaveGuard, canLeave } from '@/lib/leaveGuard'

describe('leave guard', () => {
  afterEach(() => setLeaveGuard(null))
  it('lets people leave when no page has set a guard', async () => {
    expect(await canLeave()).toBe(true)
  })
  it('asks the guard and follows its answer', async () => {
    setLeaveGuard(async () => false)
    expect(await canLeave()).toBe(false)
    setLeaveGuard(async () => true)
    expect(await canLeave()).toBe(true)
  })
})
