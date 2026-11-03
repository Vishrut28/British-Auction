import { useEffect, useRef, useState } from 'react'
import type { AuctionStatus, TriggerType } from './api'

// --- Server clock ---------------------------------------------------------------------
// The server decides when an auction closes. Each response carries server_time;
// we keep the offset between it and the local clock, so the countdown is right
// even when the viewer's clock is not.

let serverOffsetMs = 0

export function syncServerClock(serverTime: string) {
  serverOffsetMs = new Date(serverTime).getTime() - Date.now()
}

export function serverNow(): number {
  return Date.now() + serverOffsetMs
}

/** Re-renders every second with the current server time (ms). */
export function useServerNow(): number {
  const [now, setNow] = useState(serverNow)
  useEffect(() => {
    const id = setInterval(() => setNow(serverNow()), 1000)
    return () => clearInterval(id)
  }, [])
  return now
}

/**
 * Calls `load` now, then every `ms` while the tab is visible, and again as
 * soon as the tab becomes visible. A hidden tab stops polling, but the first
 * load always runs, so a page opened in a background tab is never left empty.
 */
export function usePolling(load: () => Promise<void> | void, ms: number) {
  const loadRef = useRef(load)
  loadRef.current = load
  useEffect(() => {
    const tick = () => {
      if (document.visibilityState === 'visible') void loadRef.current()
    }
    void loadRef.current()
    const id = setInterval(tick, ms)
    document.addEventListener('visibilitychange', tick)
    return () => {
      clearInterval(id)
      document.removeEventListener('visibilitychange', tick)
    }
  }, [ms])
}

// --- Formatting -----------------------------------------------------------------------

const dateTimeFmt = new Intl.DateTimeFormat(undefined, {
  day: 'numeric',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
})
const dateFmt = new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
const timeFmt = new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' })

export const fmtDateTime = (iso: string) => dateTimeFmt.format(new Date(iso))
export const fmtTime = (iso: string) => timeFmt.format(new Date(iso))
// A plain date ("2026-11-10") is a calendar day, not an instant: don't shift it by time zone.
export const fmtDate = (ymd: string) => dateFmt.format(new Date(`${ymd}T00:00:00`))

export function fmtMoney(value: string | null | undefined): string {
  if (value == null) return '—'
  return Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export function fmtCountdown(ms: number): string {
  if (ms <= 0) return '00:00'
  const total = Math.floor(ms / 1000)
  const d = Math.floor(total / 86400)
  const h = Math.floor((total % 86400) / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const pad = (n: number) => String(n).padStart(2, '0')
  if (d) return `${d}d ${pad(h)}:${pad(m)}:${pad(s)}`
  if (h) return `${h}:${pad(m)}:${pad(s)}`
  return `${pad(m)}:${pad(s)}`
}

/** "5 min", "45 s", "2 min 30 s". */
export function fmtDurationBetween(fromIso: string, toIso: string): string {
  const total = Math.round((new Date(toIso).getTime() - new Date(fromIso).getTime()) / 1000)
  const m = Math.floor(total / 60)
  const s = total % 60
  if (!s) return `${m} min`
  return m ? `${m} min ${s} s` : `${s} s`
}

export const STATUS_LABEL: Record<AuctionStatus, string> = {
  SCHEDULED: 'Scheduled',
  ACTIVE: 'Active',
  CLOSED: 'Closed',
  FORCE_CLOSED: 'Force Closed',
}

export const TRIGGER_LABEL: Record<TriggerType, string> = {
  BID_RECEIVED: 'Bid received in the last X min',
  ANY_RANK_CHANGE: 'Any supplier rank change in the last X min',
  L1_CHANGE: 'Lowest bidder (L1) change in the last X min',
}

export const TRIGGER_SHORT: Record<TriggerType, string> = {
  BID_RECEIVED: 'Any bid',
  ANY_RANK_CHANGE: 'Rank change',
  L1_CHANGE: 'L1 change',
}

/** Status computed on the client between polls, using the same rules as the server. */
export function liveStatus(
  r: { bid_start_at: string; current_close_at: string; forced_close_at: string },
  now: number,
): AuctionStatus {
  if (now < new Date(r.bid_start_at).getTime()) return 'SCHEDULED'
  const close = new Date(r.current_close_at).getTime()
  if (now < close) return 'ACTIVE'
  return close >= new Date(r.forced_close_at).getTime() ? 'FORCE_CLOSED' : 'CLOSED'
}
