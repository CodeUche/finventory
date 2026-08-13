/**
 * Connectors — one-click OAuth integrations (Slack, Google Sheets, Google
 * Drive, Google Calendar) via Nango, plus Telegram (its own shared-bot
 * linking flow — no OAuth, see backend apps.connectors.telegram's module
 * docstring). Every connector — Telegram included — returns the identical
 * { connect_link, expires_at } shape from `connect()`, so this client and
 * ConnectorsPage.tsx's poll/restore/disconnect mechanism need ZERO
 * connector-specific branching: Telegram's connect_link is simply a
 * t.me/<bot>?start=<code> URL instead of a Nango Connect URL, opened via
 * the exact same openExternal()/new-tab path.
 *
 * Replaces the technical webhooks/Zapier marketplace on the default nav (see
 * pages/settings/ConnectorsPage.tsx). The old IntegrationsPage.tsx + its API
 * client (integrationsApi.ts) are kept as-is and still routed — a real
 * paying customer (McEva International) is using webhooks today — just no
 * longer linked from anywhere in the sidebar.
 *
 * Uses the shared `api` Axios client from `./api` (JWT + org header +
 * refresh already wired there), same convention as integrationsApi.ts.
 */
import { api } from './api'

export type ConnectorKey = 'slack' | 'google_sheets' | 'google_drive' | 'google_calendar' | 'telegram'
export type ConnectorConnectionStatus = 'pending' | 'active' | 'revoked'
export type ConnectorBillingMode = 'plan_quota' | 'paid_addon'
export type BillingInterval = 'monthly' | 'annual'

export interface ConnectorConnection {
  id: string
  connector_key: ConnectorKey
  status: ConnectorConnectionStatus
  external_account_label: string
  config: Record<string, string>
  billing_mode: ConnectorBillingMode
  connected_at: string | null
  created_at: string
  updated_at: string
}

export interface ConnectorAddonSubscription {
  id: string
  connector_key: ConnectorKey
  status: 'incomplete' | 'active' | 'past_due' | 'canceled'
  interval: BillingInterval
  amount: string
  current_period_start: string | null
  current_period_end: string | null
  canceled_at: string | null
}

export interface ConnectorCatalogEntry {
  connector_key: ConnectorKey
  name: string
  description: string
  connection: ConnectorConnection | null
  addon_subscription: ConnectorAddonSubscription | null
}

export interface ConnectorQuota {
  plan_name: string | null
  used: number
  max: number
}

export interface ConnectorGalleryResponse {
  quota: ConnectorQuota
  connectors: ConnectorCatalogEntry[]
  addon_price: { monthly: string; annual: string }
}

export interface ConnectSessionResponse {
  connect_link: string
  expires_at: string | null
}

export interface AddonInitiateResponse {
  authorization_url: string
  reference: string
  access_code?: string
  public_key: string
  amount_kobo: number
  email: string
}

export const connectorsApi = {
  gallery: () => api.get<ConnectorGalleryResponse>('/connectors/'),

  /** Mints a Nango Connect session — { connect_link } is opened via openExternal()/new tab. */
  connect: (connectorKey: ConnectorKey) =>
    api.post<ConnectSessionResponse>(`/connectors/${connectorKey}/connect/`),

  /**
   * Re-checks whether the connection completed on Nango's side — no
   * parameters needed, scoped server-side to the caller's org. Used for
   * both the background poll (after opening the Connect UI) and the manual
   * "Restore access" fallback, exactly like
   * integrationsApi.restorePurchase's dual role.
   */
  restore: (connectorKey: ConnectorKey) =>
    api.post<ConnectorConnection>(`/connectors/${connectorKey}/restore/`),

  disconnect: (connectorKey: ConnectorKey) =>
    api.post<ConnectorConnection>(`/connectors/${connectorKey}/disconnect/`),

  updateConfig: (connectorKey: ConnectorKey, config: Record<string, string>) =>
    api.patch<ConnectorConnection>(`/connectors/${connectorKey}/config/`, config),

  slackChannels: () => api.get<{ channels: { id: string; name: string }[] }>('/connectors/slack/channels/'),

  /** Best-effort folder list for the Drive config picker — same "always
   *  fall back to manual entry" contract as slackChannels. */
  googleDriveFolders: () => api.get<{ folders: { id: string; name: string }[] }>('/connectors/google-drive/folders/'),

  /** Beyond-quota purchase — same Paystack-inline / openExternal handoff as subscriptions/integrations. */
  initiateAddon: (connectorKey: ConnectorKey, interval: BillingInterval) =>
    api.post<AddonInitiateResponse>(`/connectors/${connectorKey}/addon/initiate/`, { interval }),

  verifyAddonPayment: (reference: string) =>
    api.post(`/connectors/addon/verify-payment/`, { reference }),

  /** No-reference-needed restore for the add-on's Paystack payment — same
   *  role as `restore` plays for the Nango connect session, used by the
   *  poll / silent-check / manual-restore trio on the desktop checkout path. */
  restoreAddonPayment: (connectorKey: ConnectorKey) =>
    api.post(`/connectors/${connectorKey}/addon/restore/`),
}
