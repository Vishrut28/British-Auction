import { useEffect, useState, type FormEvent } from 'react'
import { api, type AuctionStatus, type BidResult, type RfqDetail, type Supplier } from '../api'
import { fmtMoney, fmtTime } from '../format'

const SUPPLIER_KEY = 'bidding-as-supplier'

function readSaved(): number | null {
  try {
    const v = localStorage.getItem(SUPPLIER_KEY)
    return v ? Number(v) : null
  } catch {
    return null
  }
}

function inDays(days: number): string {
  const d = new Date(Date.now() + days * 86400000)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

const EMPTY = {
  carrier_name: '',
  freight_charges: '',
  origin_charges: '0',
  destination_charges: '0',
  transit_time_days: '3',
  quote_valid_until: inDays(30),
}

/**
 * Login is out of scope, so a supplier is picked from a list.
 * The choice is remembered in this browser.
 */
export function BidForm({
  rfq,
  status,
  onPlaced,
}: {
  rfq: RfqDetail
  status: AuctionStatus
  onPlaced: () => Promise<void> | void
}) {
  const [suppliers, setSuppliers] = useState<Supplier[]>([])
  const [supplierId, setSupplierId] = useState<number | null>(readSaved)
  const [adding, setAdding] = useState(false)
  const [form, setForm] = useState(EMPTY)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<BidResult | null>(null)

  useEffect(() => {
    api.listSuppliers().then(setSuppliers).catch((e) => setError((e as Error).message))
  }, [])

  useEffect(() => {
    try {
      if (supplierId) localStorage.setItem(SUPPLIER_KEY, String(supplierId))
    } catch {
      /* storage unavailable: the choice just isn't remembered */
    }
  }, [supplierId])

  const supplier = suppliers.find((s) => s.id === supplierId) ?? null
  const mine = rfq.ranking.find((r) => r.supplier_id === supplierId) ?? null
  const charges = [form.freight_charges, form.origin_charges, form.destination_charges].map((v) => Number(v || 0))
  const total = charges.reduce((a, b) => a + b, 0)
  const tooHigh = mine !== null && total >= Number(mine.total_amount)

  // Prefill from the supplier's current quote, so lowering a price is quick.
  useEffect(() => {
    if (mine) {
      setForm((f) => ({
        ...f,
        carrier_name: f.carrier_name || mine.carrier_name,
        transit_time_days: String(mine.transit_time_days),
        quote_valid_until: mine.quote_valid_until,
      }))
    }
    // Only when the supplier changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [supplierId])

  if (status === 'SCHEDULED') return <p className="muted">Bidding has not opened yet.</p>
  if (status === 'CLOSED' || status === 'FORCE_CLOSED') {
    const winner = rfq.ranking[0]
    return (
      <p className="muted">
        Bidding is closed.{' '}
        {winner ? (
          <>
            Final L1: <strong>{winner.supplier_name}</strong> at <strong>{fmtMoney(winner.total_amount)}</strong>.
          </>
        ) : (
          'No bids were received.'
        )}
      </p>
    )
  }

  const set = (k: keyof typeof EMPTY) => (ev: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [k]: ev.target.value }))

  async function submit(ev: FormEvent) {
    ev.preventDefault()
    if (!supplierId) return setError('Choose which supplier you are bidding as.')
    if (!form.carrier_name.trim()) return setError('Carrier name is required.')
    if (charges.some((c) => Number.isNaN(c) || c < 0)) return setError('Charges must be zero or more.')
    if (total <= 0) return setError('Total charges must be greater than zero.')
    if (tooHigh) return setError(`Your new bid must be lower than your current ${fmtMoney(mine!.total_amount)}.`)
    setSubmitting(true)
    setError(null)
    setResult(null)
    try {
      const res = await api.placeBid(rfq.id, {
        supplier_id: supplierId,
        carrier_name: form.carrier_name.trim(),
        freight_charges: form.freight_charges || '0',
        origin_charges: form.origin_charges || '0',
        destination_charges: form.destination_charges || '0',
        transit_time_days: Number(form.transit_time_days),
        quote_valid_until: form.quote_valid_until,
      })
      setResult(res)
      setForm((f) => ({ ...f, freight_charges: '' }))
      await onPlaced()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form className="form bid-form" onSubmit={submit} noValidate>
      <label className="field">
        <span className="field-label">Bidding as</span>
        <div className="inline">
          <select
            value={supplierId ?? ''}
            onChange={(e) => {
              setSupplierId(e.target.value ? Number(e.target.value) : null)
              setResult(null)
              setError(null)
            }}
          >
            <option value="">Choose a supplier…</option>
            {suppliers.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
          <button type="button" className="btn btn-sm" onClick={() => setAdding((a) => !a)}>
            {adding ? 'Cancel' : 'New'}
          </button>
        </div>
      </label>

      {adding && (
        <AddSupplier
          onAdded={(s) => {
            setSuppliers((list) => [...list, s].sort((a, b) => a.name.localeCompare(b.name)))
            setSupplierId(s.id)
            setAdding(false)
          }}
        />
      )}

      {supplier && (
        <p className="hint-box">
          {mine ? (
            <>
              {supplier.name} is <strong>L{mine.rank}</strong> at <strong>{fmtMoney(mine.total_amount)}</strong>. A new
              bid must be lower.
            </>
          ) : (
            <>{supplier.name} has not bid yet.</>
          )}
        </p>
      )}

      <label className="field">
        <span className="field-label">Carrier name</span>
        <input value={form.carrier_name} onChange={set('carrier_name')} placeholder="e.g. BlueDart Freight" />
      </label>
      <div className="grid-3 tight">
        <label className="field">
          <span className="field-label">Freight</span>
          <input type="number" min={0} step="0.01" value={form.freight_charges} onChange={set('freight_charges')} />
        </label>
        <label className="field">
          <span className="field-label">Origin</span>
          <input type="number" min={0} step="0.01" value={form.origin_charges} onChange={set('origin_charges')} />
        </label>
        <label className="field">
          <span className="field-label">Destination</span>
          <input
            type="number"
            min={0}
            step="0.01"
            value={form.destination_charges}
            onChange={set('destination_charges')}
          />
        </label>
      </div>
      <div className={`total-line ${tooHigh ? 'total-bad' : ''}`}>
        <span>Total</span>
        <strong>{fmtMoney(String(total))}</strong>
      </div>
      <div className="grid-2 tight">
        <label className="field">
          <span className="field-label">Transit time (days)</span>
          <input type="number" min={1} value={form.transit_time_days} onChange={set('transit_time_days')} />
        </label>
        <label className="field">
          <span className="field-label">Quote valid until</span>
          <input type="date" value={form.quote_valid_until} onChange={set('quote_valid_until')} />
        </label>
      </div>

      {error && <div className="alert alert-error">{error}</div>}
      {result && (
        <div className={`alert ${result.extended ? 'alert-warn' : 'alert-ok'}`}>
          Bid placed: you are <strong>L{result.rank}</strong>.
          {result.extended && <> Auction extended to {fmtTime(result.current_close_at)}.</>}
          {result.extension_blocked && <> The forced close time stopped any further extension.</>}
        </div>
      )}

      <button type="submit" className="btn btn-primary btn-block" disabled={submitting || !supplierId}>
        {submitting ? 'Submitting…' : 'Submit bid'}
      </button>
    </form>
  )
}

function AddSupplier({ onAdded }: { onAdded: (s: Supplier) => void }) {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function add() {
    setError(null)
    try {
      onAdded(await api.createSupplier({ name: name.trim(), email: email.trim() }))
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div className="subform">
      <input placeholder="Supplier name" value={name} onChange={(e) => setName(e.target.value)} />
      <input placeholder="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
      {error && <div className="alert alert-error">{error}</div>}
      <button type="button" className="btn btn-sm" onClick={add} disabled={!name.trim() || !email.trim()}>
        Add supplier
      </button>
    </div>
  )
}
