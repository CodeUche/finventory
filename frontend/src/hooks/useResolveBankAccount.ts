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
}

// Resolves an account name from a 10-digit account number + bank code via Paystack.
// Mirrors the inline useEffect previously duplicated in EmployeesPage.tsx and SettingsPage.tsx.
export function useResolveBankAccount(opts: UseResolveBankAccountOptions): UseResolveBankAccountResult {
  const { resolver } = opts
  const [accountNumber, setAccountNumber] = useState('')
  const [bankCode, setBankCode] = useState('')
  const [accountName, setAccountName] = useState('')
  const [resolving, setResolving] = useState(false)

  useEffect(() => {
    if (accountNumber.length !== 10 || !bankCode) return
    let cancelled = false
    const resolve = async () => {
      setResolving(true)
      try {
        const data = await resolver(accountNumber, bankCode)
        if (!cancelled) setAccountName(data.account_name)
      } catch (err: any) {
        if (!cancelled) {
          const apiErr = err?.response?.data?.error
          const msg = typeof apiErr === 'string' ? apiErr : (apiErr?.message ?? 'Could not verify account — enter name manually')
          toast.error(msg, { duration: 4000 })
        }
      } finally {
        if (!cancelled) setResolving(false)
      }
    }
    resolve()
    return () => { cancelled = true }
  }, [accountNumber, bankCode])

  return { accountNumber, setAccountNumber, bankCode, setBankCode, accountName, setAccountName, resolving }
}
