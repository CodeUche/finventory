/**
 * GLAccountSelect — optional per-party GL control account override.
 *
 * Used on the customer, supplier and product forms. Leaving it blank means the
 * party posts to the organisation's mapped control account (Settings → GL
 * Mapping), which is what every existing record does.
 */

import { useEffect, useState } from 'react'
import { accountingApi } from '@/services/api'
import type { Account } from '@/types'

interface GLAccountSelectProps {
  value: string
  onChange: (accountId: string) => void
  /** Account the party falls back to when nothing is selected, e.g. "1100 Accounts Receivable". */
  fallbackLabel?: string
  className?: string
  disabled?: boolean
}

export default function GLAccountSelect({
  value, onChange, fallbackLabel, className = 'input', disabled,
}: GLAccountSelectProps) {
  const [accounts, setAccounts] = useState<Account[]>([])

  useEffect(() => {
    accountingApi.accounts()
      .then(({ data }) => setAccounts((data.results ?? data) as Account[]))
      .catch(() => setAccounts([]))
  }, [])

  return (
    <select className={className} value={value} disabled={disabled}
      onChange={(e) => onChange(e.target.value)}>
      <option value="">
        {fallbackLabel ? `Organisation default (${fallbackLabel})` : 'Organisation default'}
      </option>
      {accounts.map((a) => (
        <option key={a.id} value={a.id}>{a.code} — {a.name}</option>
      ))}
    </select>
  )
}
