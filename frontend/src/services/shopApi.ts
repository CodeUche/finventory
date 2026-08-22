/**
 * Public storefront API.
 *
 * Deliberately NOT the shared `api` client: that one attaches a bearer token
 * and an X-Organisation-ID header from the signed-in session. A customer
 * browsing a shop has neither, and sending a staff token from a public page
 * would be a real leak. This client sends nothing but the request.
 */

import axios from 'axios'

const baseURL = import.meta.env.VITE_API_BASE_URL || '/api/v1'

const shop = axios.create({ baseURL, timeout: 20000 })

export interface ShopBankAccount {
  bank_name: string
  account_number: string
  account_name: string
  instructions?: string
}

export interface ShopInfo {
  slug: string
  name: string
  logo: string
  currency: string
  headline: string
  about: string
  whatsapp: string
  delivery_note: string
  accent_colour: string
  accepts_orders: boolean
  minimum_order: string
  /** Null means no free-delivery rule is configured. */
  free_delivery_threshold: string | null
  fixed_delivery_charge: string
  payment: {
    card: boolean
    virtual_account: boolean
    bank_transfer: boolean
    bank_accounts: ShopBankAccount[]
  }
}

export interface ShopProduct {
  id: string
  name: string
  description: string
  category_name: string
  unit_of_measure: string
  selling_price: string
  image: string
  in_stock: boolean
}

export interface ShopOrderItem {
  product_name: string
  quantity: string
  unit_price: string
  line_total: string
}

export interface ShopOrder {
  reference: string
  status: 'placed' | 'confirmed' | 'ready' | 'completed' | 'cancelled'
  status_label: string
  fulfilment: 'pickup' | 'delivery' | 'table'
  customer_name: string
  delivery_address: string
  note: string
  subtotal: string
  total: string
  items: ShopOrderItem[]
  created_at: string
}

export const shopApi = {
  info: (slug: string) => shop.get<ShopInfo>(`/shop/${slug}/`),
  products: (slug: string) => shop.get<{ results: ShopProduct[] }>(`/shop/${slug}/products/`),
  placeOrder: (slug: string, data: object) => shop.post<ShopOrder>(`/shop/${slug}/orders/`, data),
  order: (slug: string, reference: string) =>
    shop.get<ShopOrder>(`/shop/${slug}/orders/${reference}/`),
}

/** Pull a readable message out of whatever the API returned. */
export function shopError(err: unknown, fallback: string): string {
  const data = (err as { response?: { data?: Record<string, unknown> } })?.response?.data
  if (!data) return fallback
  if (typeof data.error === 'string') return data.error
  const firstField = Object.values(data).find((v) => Array.isArray(v) && v.length)
  if (Array.isArray(firstField)) return String(firstField[0])
  return fallback
}
