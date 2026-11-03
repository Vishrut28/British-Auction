import type { AuctionEvent, EventType } from '../api'
import { fmtDateTime, fmtTime } from '../format'

const LABEL: Record<EventType, string> = {
  RFQ_CREATED: 'RFQ created',
  BID_PLACED: 'Bid submitted',
  TIME_EXTENDED: 'Time extended',
  EXTENSION_BLOCKED: 'Extension blocked',
  AUCTION_CLOSED: 'Auction closed',
  AUCTION_FORCE_CLOSED: 'Force closed',
}

/** Newest first. Extensions show the reason and the close time before and after. */
export function ActivityLog({ events }: { events: AuctionEvent[] }) {
  if (events.length === 0) return <p className="muted">No activity yet.</p>
  const newestFirst = [...events].reverse()
  return (
    <ol className="log">
      {newestFirst.map((e) => (
        <li key={e.id} className={`log-item log-${e.event_type.toLowerCase()}`}>
          <span className="log-dot" aria-hidden />
          <div className="log-body">
            <div className="log-head">
              <span className="log-type">{LABEL[e.event_type]}</span>
              <time className="muted small" dateTime={e.created_at}>
                {fmtDateTime(e.created_at)}
              </time>
            </div>
            <p className="log-reason">{e.reason}</p>
            {e.event_type === 'TIME_EXTENDED' && e.previous_close_at && e.new_close_at && (
              <p className="log-change">
                Close time {fmtTime(e.previous_close_at)} → <strong>{fmtTime(e.new_close_at)}</strong>
              </p>
            )}
          </div>
        </li>
      ))}
    </ol>
  )
}
