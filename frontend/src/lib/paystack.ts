/**
 * Shared Paystack inline-checkout loader — single source of truth so the
 * billing/checkout pages that trigger a Paystack payment (BillingPage,
 * IntegrationsPage, ConnectorsPage) don't each carry their own copy of the
 * script-injection + PaystackPop typing.
 */

declare global {
  interface Window {
    PaystackPop: {
      setup(opts: {
        key: string
        email: string
        amount: number
        ref: string
        accessCode?: string
        currency?: string
        onClose: () => void
        callback: (response: { reference: string }) => void
      }): { openIframe(): void }
    }
  }
}

export function loadPaystackScript(): Promise<void> {
  return new Promise((resolve, reject) => {
    if (window.PaystackPop) { resolve(); return }
    const existing = document.getElementById('paystack-inline-js')
    if (existing) { existing.addEventListener('load', () => resolve()); return }
    const script = document.createElement('script')
    script.id = 'paystack-inline-js'
    script.src = 'https://js.paystack.co/v1/inline.js'
    script.onload = () => resolve()
    script.onerror = () => reject(new Error('Failed to load Paystack script'))
    document.head.appendChild(script)
  })
}
