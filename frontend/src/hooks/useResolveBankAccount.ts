import { useEffect, useState } from 'react'
import toast from 'react-hot-toast'

interface UseResolveBankAccountOptions {
  resolver: (accountNumber: string, bankCode: string) => Promise<{ account_name: string }>
}

interface UseResolveBankAccountResult {
  accountNumber: string
  setAccountNumber: (v: string) => void
  bankCode: string
  setBankCode: (v: string) => void
  accountName: string
  setAccountName: (v: string) => void
  resolving: boolean
  // Human-readable reason the last resolve attempt failed, or '' if the last
  // attempt succeeded (or none has run yet). Callers should render this next
  // to the Account Name field — a toast alone is easy to miss, especially on
  // a form with several tabs, so the failure needs a visible, persistent
  // trace in the UI itself, not just a transient notification.
  resolveError: string
}

// Resolves an account name from a 10-digit account number + bank code via Paystack
// (falling back to Flutterwave server-side — see backend/apps/core/bank_resolve.py).
// Mirrors the inline useEffect previously duplicated in EmployeesPage.tsx and SettingsPage.tsx.
export function useResolveBankAccount(opts: UseResolveBankAccountOptions): UseResolveBankAccountResult {
  const { resolver } = opts
  const [accountNumber, setAccountNumber] = useState('')
  const [bankCode, setBankCode] = useState('')
  const [accountName, setAccountName] = useState('')
  const [resolving, setResolving] = useState(false)
  const [resolveError, setResolveError] = useState('')

  useEffect(() => {
    // Only attempt a lookup once we have a full 10-digit NUBAN and a bank has
    // actually been picked (bankCode is only set by selecting an option from
    // the bank combobox, not by typing free text into the search box). Clear
    // any stale error from a previous attempt as soon as the inputs change
    // away from that fully-formed state, so an old failure message doesn't
    // linger on screen while the user is still editing.
    if (accountNumber.length !== 10 || !bankCode) {
      setResolveError('')
      return
    }
    let cancelled = false
    const resolve = async () => {
      setResolving(true)
      setResolveError('')
      try {
        const data = await resolver(accountNumber, bankCode)
        if (!cancelled) setAccountName(data.account_name)
      } catch (err: any) {
        if (!cancelled) {
          const apiErr = err?.response?.data?.error
          const msg = typeof apiErr === 'string' ? apiErr : (apiErr?.message ?? 'Could not verify account — enter name manually')
          setResolveError(msg)
          toast.error(msg, { duration: 4000 })
        }
      } finally {
        if (!cancelled) setResolving(false)
      }
    }
    resolve()
    return () => { cancelled = true }
  }, [accountNumber, bankCode])

  return { accountNumber, setAccountNumber, bankCode, setBankCode, accountName, setAccountName, resolving, resolveError }
}
