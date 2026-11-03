import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, ApiError, type RfqDetail } from '../api'
import { ActivityLog } from '../components/ActivityLog'
import { BidForm } from '../components/BidForm'
import { StatusBadge } from '../components/StatusBadge'
import {
  fmtCountdown,
  fmtDate,
  fmtDateTime,
  fmtDurationBetween,
  fmtMoney,
  fmtTime,
  liveStatus,
  syncServerClock,
  TRIGGER_LABEL,
  usePolling,
  useServerNow,
} from '../format'

export function RfqDetailPage() {
  const id = Number(useParams().id)
  const [rfq, setRfq] = useState<RfqDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notFound, setNotFound] = useState(false)
  const now = useServerNow()

  const load = useCallback(async () => {
    try {
      const d = await api.getRfq(id)
      syncServerClock(d.server_time)
      setRfq(d)
      setError(null)
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) setNotFound(true)
      else setError((e as Error).message)
    }
  }, [id])

  usePolling(load, 2000)

  // Reload the moment the countdown reaches zero, so the close shows at once.
  const status = rfq ? liveStatus(rfq, now) : null
  const lastStatus = useRef(status)
  useEffect(() => {
    if (lastStatus.current && status !== lastStatus.current) void load()
    lastStatus.current = status
  }, [status, load])

  if (notFound)
    return (
      <p className="muted">
        RFQ not found. <Link to="/">Back to auctions</Link>
      </p>
    )
  if (!rfq || !status)
    return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>

  const closeMs = new Date(rfq.current_close_at).getTime()
  const startMs = new Date(rfq.bid_start_at).getTime()
  const { config } = rfq
  const windowMinutes = config.trigger_window_minutes
  const windowStartMs = windowMinutes === null ? null : closeMs - windowMinutes * 60000
  const inWindow = status === 'ACTIVE' && windowStartMs !== null && now >= windowStartMs
  const extended = rfq.current_close_at !== rfq.bid_close_at

  return (
    <>
      <p className="breadcrumb">
        <Link to="/">← All auctions</Link>
      </p>
      <div className="page-head">
        <div>
          <div className="title-row">
            <h1>{rfq.reference_id}</h1>
            <StatusBadge status={status} />
          </div>
          <p className="muted">
            {rfq.name} · Pickup {fmtDate(rfq.pickup_date)}
          </p>
        </div>
        <div className={`countdown ${inWindow ? 'countdown-hot' : ''}`}>
          {status === 'ACTIVE' && (
            <>
              <span className="countdown-label">
                {inWindow ? 'In trigger window, closes in' : 'Closes in'}
              </span>
              <span className="countdown-value">{fmtCountdown(closeMs - now)}</span>
            </>
          )}
          {status === 'SCHEDULED' && (
            <>
              <span className="countdown-label">Bidding opens in</span>
              <span className="countdown-value">{fmtCountdown(startMs - now)}</span>
            </>
          )}
          {(status === 'CLOSED' || status === 'FORCE_CLOSED') && (
            <>
              <span className="countdown-label">
                {status === 'FORCE_CLOSED' ? 'Force closed at' : 'Closed at'}
              </span>
              <span className="countdown-value small-value">{fmtTime(rfq.current_close_at)}</span>
            </>
          )}
        </div>
      </div>

      {error && <div className="alert alert-warn">Connection problem, showing last known data: {error}</div>}

      <div className="stats">
        <Stat
          label="Current lowest bid (L1)"
          value={fmtMoney(rfq.lowest_bid)}
          sub={rfq.ranking[0]?.supplier_name ?? 'No bids yet'}
        />
        <Stat
          label="Current bid close"
          value={fmtDateTime(rfq.current_close_at)}
          sub={
            extended
              ? `Extended ${rfq.extension_count}× (+${fmtDurationBetween(rfq.bid_close_at, rfq.current_close_at)}) from ${fmtTime(rfq.bid_close_at)}`
              : 'Not extended'
          }
        />
        <Stat
          label="Forced bid close"
          value={fmtDateTime(rfq.forced_close_at)}
          sub="Hard stop: never extended past"
        />
        <Stat
          label="Bids"
          value={String(rfq.bid_count)}
          sub={`${rfq.supplier_count} supplier${rfq.supplier_count === 1 ? '' : 's'}`}
        />
      </div>

      <div className="layout-2">
        <div className="col-main">
          <section className="card">
            <h2>Supplier ranking</h2>
            <p className="muted small">Each supplier's latest quote, lowest price first.</p>
            {rfq.ranking.length === 0 ? (
              <p className="muted">No bids yet.</p>
            ) : (
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Rank</th>
                      <th>Supplier</th>
                      <th>Carrier</th>
                      <th className="num">Freight</th>
                      <th className="num">Origin</th>
                      <th className="num">Destination</th>
                      <th className="num">Total</th>
                      <th>Transit</th>
                      <th>Valid until</th>
                      <th>Bid at</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rfq.ranking.map((b) => (
                      <tr key={b.id} className={b.rank === 1 ? 'row-l1' : ''}>
                        <td>
                          <span className={`rank rank-${Math.min(b.rank, 4)}`}>L{b.rank}</span>
                        </td>
                        <td className="strong">{b.supplier_name}</td>
                        <td>{b.carrier_name}</td>
                        <td className="num">{fmtMoney(b.freight_charges)}</td>
                        <td className="num">{fmtMoney(b.origin_charges)}</td>
                        <td className="num">{fmtMoney(b.destination_charges)}</td>
                        <td className="num strong">{fmtMoney(b.total_amount)}</td>
                        <td>{b.transit_time_days} d</td>
                        <td>{fmtDate(b.quote_valid_until)}</td>
                        <td className="muted">{fmtTime(b.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="card">
            <h2>All bids</h2>
            <p className="muted small">Every bid submitted, sorted by price.</p>
            {rfq.bids.length === 0 ? (
              <p className="muted">No bids yet.</p>
            ) : (
              <div className="table-wrap">
                <table className="table table-compact">
                  <thead>
                    <tr>
                      <th>Supplier</th>
                      <th>Carrier</th>
                      <th className="num">Freight</th>
                      <th className="num">Origin</th>
                      <th className="num">Destination</th>
                      <th className="num">Total</th>
                      <th>Transit</th>
                      <th>Valid until</th>
                      <th>Bid at</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rfq.bids.map((b) => {
                      const current = rfq.ranking.some((r) => r.id === b.id)
                      return (
                        <tr key={b.id} className={current ? '' : 'row-superseded'}>
                          <td>
                            {b.supplier_name}
                            {!current && <span className="tag">superseded</span>}
                          </td>
                          <td>{b.carrier_name}</td>
                          <td className="num">{fmtMoney(b.freight_charges)}</td>
                          <td className="num">{fmtMoney(b.origin_charges)}</td>
                          <td className="num">{fmtMoney(b.destination_charges)}</td>
                          <td className="num strong">{fmtMoney(b.total_amount)}</td>
                          <td>{b.transit_time_days} d</td>
                          <td>{fmtDate(b.quote_valid_until)}</td>
                          <td className="muted">{fmtTime(b.created_at)}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="card">
            <h2>Activity log</h2>
            <ActivityLog events={rfq.events} />
          </section>
        </div>

        <aside className="col-side">
          <section className="card">
            <h2>Submit a quote</h2>
            <BidForm rfq={rfq} status={status} onPlaced={load} />
          </section>

          <section className="card">
            <h2>Auction configuration</h2>
            <dl className="dl">
              <dt>British auction</dt>
              <dd>{config.is_british_auction ? 'Enabled' : 'Off: no extensions'}</dd>
              {config.trigger_type && (
                <>
                  <dt>Trigger window (X)</dt>
                  <dd>{config.trigger_window_minutes} min</dd>
                  <dt>Extension duration (Y)</dt>
                  <dd>{config.extension_minutes} min</dd>
                  <dt>Extension trigger</dt>
                  <dd>{TRIGGER_LABEL[config.trigger_type].replace('X', String(windowMinutes))}</dd>
                </>
              )}
              <dt>Bid start</dt>
              <dd>{fmtDateTime(rfq.bid_start_at)}</dd>
              <dt>Original bid close</dt>
              <dd>{fmtDateTime(rfq.bid_close_at)}</dd>
              <dt>Forced bid close</dt>
              <dd>{fmtDateTime(rfq.forced_close_at)}</dd>
            </dl>
            {status === 'ACTIVE' && windowStartMs !== null && (
              <p className="muted small">
                Trigger window now: {fmtTime(new Date(windowStartMs).toISOString())} –{' '}
                {fmtTime(rfq.current_close_at)}
              </p>
            )}
          </section>
        </aside>
      </div>
    </>
  )
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="card stat">
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
      {sub && <span className="stat-sub">{sub}</span>}
    </div>
  )
}
