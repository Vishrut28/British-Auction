import { useMemo, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, type TriggerType } from '../api'
import { TRIGGER_LABEL } from '../format'

// <input type="datetime-local"> works in local time without a zone.
function toLocalInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}
const toLocalDate = (d: Date) => toLocalInput(d).slice(0, 10)
const addMinutes = (d: Date, m: number) => new Date(d.getTime() + m * 60000)

function defaults() {
  const now = new Date()
  now.setSeconds(0, 0)
  const ref = `RFQ-${toLocalDate(now).replace(/-/g, '')}-${String(now.getHours()).padStart(2, '0')}${String(now.getMinutes()).padStart(2, '0')}`
  return {
    reference_id: ref,
    name: '',
    pickup_date: toLocalDate(addMinutes(now, 3 * 24 * 60)),
    bid_start_at: toLocalInput(now),
    bid_close_at: toLocalInput(addMinutes(now, 15)),
    forced_close_at: toLocalInput(addMinutes(now, 30)),
    trigger_window_minutes: '5',
    extension_minutes: '3',
    trigger_type: 'L1_CHANGE' as TriggerType,
  }
}

type Form = ReturnType<typeof defaults>

// Same rules as the backend (docs/auction-rules.md), checked early for quick feedback.
function validate(f: Form): Partial<Record<keyof Form, string>> {
  const e: Partial<Record<keyof Form, string>> = {}
  if (!f.reference_id.trim()) e.reference_id = 'Required.'
  if (!f.name.trim()) e.name = 'Required.'
  if (!f.pickup_date) e.pickup_date = 'Required.'
  const start = Date.parse(f.bid_start_at)
  const close = Date.parse(f.bid_close_at)
  const forced = Date.parse(f.forced_close_at)
  if (Number.isNaN(start)) e.bid_start_at = 'Required.'
  if (Number.isNaN(close)) e.bid_close_at = 'Required.'
  else if (close <= start) e.bid_close_at = 'Must be later than the bid start time.'
  else if (close <= Date.now()) e.bid_close_at = 'Must be in the future.'
  if (Number.isNaN(forced)) e.forced_close_at = 'Required.'
  else if (!Number.isNaN(close) && forced <= close)
    e.forced_close_at = 'Must be later than the bid close time.'
  for (const k of ['trigger_window_minutes', 'extension_minutes'] as const) {
    const n = Number(f[k])
    if (!Number.isInteger(n) || n < 1 || n > 1440) e[k] = 'Whole minutes, 1 to 1440.'
  }
  return e
}

export function CreateRfqPage() {
  const navigate = useNavigate()
  const [form, setForm] = useState<Form>(defaults)
  const [touched, setTouched] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [serverError, setServerError] = useState<string | null>(null)
  const errors = useMemo(() => validate(form), [form])
  const show = (k: keyof Form) => (touched ? errors[k] : undefined)

  const set = (k: keyof Form) => (ev: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [k]: ev.target.value }))

  async function submit(ev: FormEvent) {
    ev.preventDefault()
    setTouched(true)
    if (Object.keys(errors).length) return
    setSubmitting(true)
    setServerError(null)
    try {
      const rfq = await api.createRfq({
        reference_id: form.reference_id.trim(),
        name: form.name.trim(),
        pickup_date: form.pickup_date,
        bid_start_at: new Date(form.bid_start_at).toISOString(),
        bid_close_at: new Date(form.bid_close_at).toISOString(),
        forced_close_at: new Date(form.forced_close_at).toISOString(),
        trigger_window_minutes: Number(form.trigger_window_minutes),
        extension_minutes: Number(form.extension_minutes),
        trigger_type: form.trigger_type,
      })
      navigate(`/rfqs/${rfq.id}`)
    } catch (e) {
      setServerError((e as Error).message)
      setSubmitting(false)
    }
  }

  const x = Number(form.trigger_window_minutes) || 'X'
  const y = Number(form.extension_minutes) || 'Y'

  return (
    <>
      <div className="page-head">
        <div>
          <h1>New RFQ</h1>
          <p className="muted">Create an RFQ with British auction bidding enabled.</p>
        </div>
      </div>

      <form className="card form" onSubmit={submit} noValidate>
        {serverError && <div className="alert alert-error">{serverError}</div>}

        <section>
          <h2>RFQ details</h2>
          <div className="grid-2">
            <Field label="RFQ name" error={show('name')}>
              <input value={form.name} onChange={set('name')} placeholder="e.g. Mumbai → Delhi, 2 × 40ft" />
            </Field>
            <Field label="Reference ID" error={show('reference_id')}>
              <input value={form.reference_id} onChange={set('reference_id')} />
            </Field>
            <Field label="Pickup / service date" error={show('pickup_date')}>
              <input type="date" value={form.pickup_date} onChange={set('pickup_date')} />
            </Field>
          </div>
        </section>

        <section>
          <h2>Bidding window</h2>
          <div className="grid-3">
            <Field label="Bid start" error={show('bid_start_at')}>
              <input type="datetime-local" value={form.bid_start_at} onChange={set('bid_start_at')} />
            </Field>
            <Field label="Bid close" error={show('bid_close_at')}>
              <input type="datetime-local" value={form.bid_close_at} onChange={set('bid_close_at')} />
            </Field>
            <Field
              label="Forced bid close"
              hint="The auction never extends past this."
              error={show('forced_close_at')}
            >
              <input type="datetime-local" value={form.forced_close_at} onChange={set('forced_close_at')} />
            </Field>
          </div>
        </section>

        <section>
          <h2>British auction configuration</h2>
          <div className="grid-2">
            <Field
              label="Trigger window (X minutes)"
              hint="How close to the close time bidding activity is watched."
              error={show('trigger_window_minutes')}
            >
              <input
                type="number"
                min={1}
                max={1440}
                value={form.trigger_window_minutes}
                onChange={set('trigger_window_minutes')}
              />
            </Field>
            <Field
              label="Extension duration (Y minutes)"
              hint="Time added to the close time when the trigger fires."
              error={show('extension_minutes')}
            >
              <input
                type="number"
                min={1}
                max={1440}
                value={form.extension_minutes}
                onChange={set('extension_minutes')}
              />
            </Field>
          </div>

          <fieldset className="radio-group">
            <legend>Extension trigger</legend>
            {(Object.keys(TRIGGER_LABEL) as TriggerType[]).map((t) => (
              <label key={t} className={`radio-card ${form.trigger_type === t ? 'selected' : ''}`}>
                <input
                  type="radio"
                  name="trigger_type"
                  value={t}
                  checked={form.trigger_type === t}
                  onChange={set('trigger_type')}
                />
                <span>
                  <strong>{TRIGGER_LABEL[t].replace('X', String(x))}</strong>
                  <span className="muted small">{TRIGGER_HELP[t]}</span>
                </span>
              </label>
            ))}
          </fieldset>

          <p className="summary">
            If the trigger fires in the last <strong>{x} min</strong> before close, the close time moves{' '}
            <strong>{y} min</strong> later, but never past the forced close.
          </p>
        </section>

        <div className="form-actions">
          <button type="button" className="btn" onClick={() => navigate('/')}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={submitting}>
            {submitting ? 'Creating…' : 'Create RFQ'}
          </button>
        </div>
      </form>
    </>
  )
}

const TRIGGER_HELP: Record<TriggerType, string> = {
  BID_RECEIVED: 'Any new bid in the window extends the auction.',
  ANY_RANK_CHANGE: 'Extends when a bid changes the rank of a supplier who was already ranked.',
  L1_CHANGE: 'Extends only when a different supplier becomes the lowest bidder.',
}

function Field({
  label,
  hint,
  error,
  children,
}: {
  label: string
  hint?: string
  error?: string
  children: React.ReactNode
}) {
  return (
    <label className={`field ${error ? 'has-error' : ''}`}>
      <span className="field-label">{label}</span>
      {children}
      {error ? <span className="field-error">{error}</span> : hint && <span className="field-hint">{hint}</span>}
    </label>
  )
}
