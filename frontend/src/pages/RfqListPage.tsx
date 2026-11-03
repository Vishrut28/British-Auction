import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, type RfqSummary } from '../api'
import { StatusBadge } from '../components/StatusBadge'
import {
  fmtCountdown,
  fmtDateTime,
  fmtMoney,
  liveStatus,
  syncServerClock,
  TRIGGER_SHORT,
  usePolling,
  useServerNow,
} from '../format'

export function RfqListPage() {
  const [items, setItems] = useState<RfqSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const now = useServerNow()
  const navigate = useNavigate()

  usePolling(async () => {
    try {
      const res = await api.listRfqs()
      syncServerClock(res.server_time)
      setItems(res.items)
      setError(null)
    } catch (e) {
      setError((e as Error).message)
    }
  }, 5000)

  return (
    <>
      <div className="page-head">
        <div>
          <h1>British Auctions</h1>
          <p className="muted">Every RFQ running as a British auction. Updates live.</p>
        </div>
      </div>

      {error && <div className="alert alert-error">Could not load auctions: {error}</div>}

      {items === null && !error && <p className="muted">Loading…</p>}

      {items?.length === 0 && (
        <div className="card empty">
          <p>No auctions yet.</p>
          <Link to="/rfqs/new" className="btn btn-primary">
            Create the first RFQ
          </Link>
        </div>
      )}

      {items && items.length > 0 && (
        <div className="card table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>RFQ</th>
                <th className="num">Current lowest bid</th>
                <th>Current bid close</th>
                <th>Forced close</th>
                <th>Status</th>
                <th className="num">Bids</th>
              </tr>
            </thead>
            <tbody>
              {items.map((r) => {
                const status = liveStatus(r, now)
                const closeMs = new Date(r.current_close_at).getTime()
                return (
                  <tr key={r.id} className="row-link" onClick={() => navigate(`/rfqs/${r.id}`)}>
                    <td>
                      <Link to={`/rfqs/${r.id}`} className="strong" onClick={(e) => e.stopPropagation()}>
                        {r.reference_id}
                      </Link>
                      <div className="muted small">
                        {r.name} · {TRIGGER_SHORT[r.trigger_type]}
                      </div>
                    </td>
                    <td className="num strong">{fmtMoney(r.lowest_bid)}</td>
                    <td>
                      {fmtDateTime(r.current_close_at)}
                      {r.extension_count > 0 && (
                        <span className="tag tag-ext" title={`Original close: ${fmtDateTime(r.bid_close_at)}`}>
                          +{r.extension_count} ext
                        </span>
                      )}
                      {status === 'ACTIVE' && (
                        <div className="small countdown-inline">closes in {fmtCountdown(closeMs - now)}</div>
                      )}
                      {status === 'SCHEDULED' && (
                        <div className="small muted">
                          opens in {fmtCountdown(new Date(r.bid_start_at).getTime() - now)}
                        </div>
                      )}
                    </td>
                    <td>{fmtDateTime(r.forced_close_at)}</td>
                    <td>
                      <StatusBadge status={status} />
                    </td>
                    <td className="num">
                      {r.bid_count}
                      <div className="muted small">
                        {r.supplier_count} supplier{r.supplier_count === 1 ? '' : 's'}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}
