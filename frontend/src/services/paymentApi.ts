/**
 * Integration-marketplace purchase API (Track D — Payment Engine).
 *
 * Mirrors the calling convention of `subscriptionApi` in `./api.ts`
 * (same shared `api` axios instance, same response shape expectations —
 * see BillingPage.tsx's handleSubscribe/handlePaymentSuccess for the
 * pattern this follows for Paystack initiate → verify).
 *
 * Deliberately a separate file from api.ts (hard boundary — do not edit
 * api.ts) even though it reuses the same axios instance.
 */

import { api } from './api'

export interface IntegrationPurchaseInitResponse {
  authorization_url: string
  reference: string
  access_code: string
  public_key: string
  amount_kobo: number
  email: string
}

export const paymentApi = {
  /**
   * POST /subscriptions/integrations/{product_key}/purchase/
   * Initialises a Paystack transaction for a one-time integration purchase.
   */
  purchaseIntegration: (productKey: string) =>
    api.post<IntegrationPurchaseInitResponse>(
      `/subscriptions/integrations/${productKey}/purchase/`,
    ),

  /**
   * POST /subscriptions/integrations/verify-payment/
   * Confirms the transaction and activates the entitlement.
   */
  verifyIntegrationPayment: (reference: string) =>
    api.post('/subscriptions/integrations/verify-payment/', { reference }),
}
