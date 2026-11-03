// Typed client for the FastAPI backend. Types mirror backend/app/schemas.py.

export type TriggerType = 'BID_RECEIVED' | 'ANY_RANK_CHANGE' | 'L1_CHANGE'
export type AuctionStatus = 'SCHEDULED' | 'ACTIVE' | 'CLOSED' | 'FORCE_CLOSED'
export type EventType =
  | 'RFQ_CREATED'
  | 'BID_PLACED'
  | 'TIME_EXTENDED'
  | 'EXTENSION_BLOCKED'
  | 'AUCTION_CLOSED'
  | 'AUCTION_FORCE_CLOSED'

// Money arrives as a decimal string ("1234.50") so no precision is lost.
export type Money = string

export interface Supplier {
  id: number
  name: string
  email: string
}

export interface RfqSummary {
  id: number
  reference_id: string
  name: string
  pickup_date: string
  bid_start_at: string
  bid_close_at: string
  current_close_at: string
  forced_close_at: string
  status: AuctionStatus
  lowest_bid: Money | null
  bid_count: number
  supplier_count: number
  extension_count: number
  is_british_auction: boolean
  trigger_type: TriggerType | null
}

export interface Bid {
  id: number
  supplier_id: number
  supplier_name: string
  carrier_name: string
  freight_charges: Money
  origin_charges: Money
  destination_charges: Money
  total_amount: Money
  transit_time_days: number
  quote_valid_until: string
  created_at: string
}

export interface RankedBid extends Bid {
  rank: number
}

export interface AuctionEvent {
  id: number
  event_type: EventType
  bid_id: number | null
  supplier_id: number | null
  previous_close_at: string | null
  new_close_at: string | null
  reason: string
  details: Record<string, unknown> | null
  created_at: string
}

export interface RfqDetail extends RfqSummary {
  server_time: string
  config: {
    is_british_auction: boolean
    // null when the British auction option is off
    trigger_window_minutes: number | null
    extension_minutes: number | null
    trigger_type: TriggerType | null
  }
  ranking: RankedBid[]
  bids: Bid[]
  events: AuctionEvent[]
}

export interface RfqCreate {
  reference_id: string
  name: string
  pickup_date: string
  bid_start_at: string
  bid_close_at: string
  forced_close_at: string
  is_british_auction: boolean
  trigger_window_minutes?: number
  extension_minutes?: number
  trigger_type?: TriggerType
}

export interface BidCreate {
  supplier_id: number
  carrier_name: string
  freight_charges: string
  origin_charges: string
  destination_charges: string
  transit_time_days: number
  quote_valid_until: string
}

export interface BidResult {
  bid: Bid
  rank: number
  extended: boolean
  extension_blocked: boolean
  previous_close_at: string
  current_close_at: string
  reason: string | null
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

// FastAPI returns {detail: "..."} for our own errors, and
// {detail: [{loc, msg}, ...]} for request validation errors.
export function errorMessage(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((d: { loc?: unknown[]; msg?: string }) => {
        const field = d.loc?.filter((p) => p !== 'body').join('.')
        const msg = (d.msg ?? 'Invalid value').replace(/^Value error, /, '')
        return field ? `${field}: ${msg}` : msg
      })
      .join(' · ')
  }
  return `Request failed (${status})`
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  const body = res.status === 204 ? null : await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, errorMessage(body, res.status))
  return body as T
}

export const api = {
  listRfqs: () => request<{ server_time: string; items: RfqSummary[] }>('/rfqs'),
  getRfq: (id: number) => request<RfqDetail>(`/rfqs/${id}`),
  createRfq: (data: RfqCreate) => request<RfqDetail>('/rfqs', { method: 'POST', body: JSON.stringify(data) }),
  placeBid: (rfqId: number, data: BidCreate) =>
    request<BidResult>(`/rfqs/${rfqId}/bids`, { method: 'POST', body: JSON.stringify(data) }),
  listSuppliers: () => request<Supplier[]>('/suppliers'),
  createSupplier: (data: { name: string; email: string }) =>
    request<Supplier>('/suppliers', { method: 'POST', body: JSON.stringify(data) }),
}
