/**
 * Track C — paid integrations marketplace (webhooks + Zapier).
 *
 * Uses the shared `api` Axios client from `./api` (JWT + org header +
 * refresh already wired there) — this file only adds route helpers, it does
 * not touch api.ts itself.
 */
import { api } from './api'

export interface IntegrationProduct {
  id: string
  key: string
  name: string
  description: string
  price: string
  is_active: boolean
  /** Annotated per-request by the backend from the caller's org entitlements. */
  entitlement_status: 'pending' | 'active' | 'revoked' | null
}

export interface WebhookSubscription {
  id: string
  target_url: string
  event_types: string[]
  is_active: boolean
  integration_product: string | null
  created_at: string
  updated_at: string
}

export interface WebhookSubscriptionCreateResponse extends WebhookSubscription {
  /** Only ever present in the CREATE response — never returned again. */
  secret: string
}

export interface WebhookDelivery {
  id: string
  subscription: string
  event: string
  event_type: string
  status: 'pending' | 'delivered' | 'failed'
  attempt_count: number
  last_attempted_at: string | null
  last_response_code: number | null
  last_error: string
  created_at: string
}

export interface OrganisationAPIKey {
  id: string
  name: string
  key_prefix: string
  is_active: boolean
  created_at: string
  last_used_at: string | null
}

export interface OrganisationAPIKeyCreateResponse extends OrganisationAPIKey {
  /** Only ever present in the CREATE response — never returned again. */
  key: string
}

export const EVENT_TYPES: { value: string; label: string }[] = [
  { value: 'invoice.created', label: 'Invoice created' },
  { value: 'payment.received', label: 'Payment received' },
  { value: 'employee.onboarded', label: 'Employee onboarded' },
]

export const integrationsApi = {
  // ── Marketplace catalog + purchase (purchase/verify endpoints already
  // exist on apps.subscriptions — SubscriptionViewSet.purchase_integration /
  // verify_integration_payment — this only adds the frontend calls to them) ─
  products: () => api.get<IntegrationProduct[]>('/integrations/products/'),
  purchase: (productKey: string) =>
    api.post<{ authorization_url: string; reference: string; access_code?: string; public_key: string; amount_kobo: number; email: string }>(
      `/subscriptions/integrations/${productKey}/purchase/`,
    ),
  verifyPurchase: (reference: string) => api.post('/subscriptions/integrations/verify-payment/', { reference }),

  // ── Webhook subscriptions ─────────────────────────────────────────────────
  listWebhooks: () => api.get<WebhookSubscription[] | { results: WebhookSubscription[] }>('/integrations/webhooks/'),
  createWebhook: (data: { target_url: string; event_types: string[]; integration_product?: string | null }) =>
    api.post<WebhookSubscriptionCreateResponse>('/integrations/webhooks/', data),
  deleteWebhook: (id: string) => api.delete(`/integrations/webhooks/${id}/`),
  testWebhook: (id: string) => api.post(`/integrations/webhooks/${id}/test/`),
  webhookDeliveries: (id: string) => api.get<WebhookDelivery[]>(`/integrations/webhooks/${id}/deliveries/`),

  // ── API keys (Zapier) ─────────────────────────────────────────────────────
  listApiKeys: () => api.get<OrganisationAPIKey[] | { results: OrganisationAPIKey[] }>('/integrations/api-keys/'),
  createApiKey: (name: string) => api.post<OrganisationAPIKeyCreateResponse>('/integrations/api-keys/', { name }),
  revokeApiKey: (id: string) => api.delete(`/integrations/api-keys/${id}/`),
}

/** Normalises either a bare array or a DRF paginated {results} response. */
export function unwrapList<T>(data: T[] | { results: T[] } | undefined | null): T[] {
  if (!data) return []
  return Array.isArray(data) ? data : data.results ?? []
}
