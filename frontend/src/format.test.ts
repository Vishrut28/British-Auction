import { describe, expect, it } from 'vitest'
import { errorMessage } from './api'
import { fmtCountdown, fmtDurationBetween, liveStatus } from './format'

const t = (hhmm: string) => `2026-11-03T${hhmm}:00Z`
const ms = (hhmm: string) => new Date(t(hhmm)).getTime()
const rfq = { bid_start_at: t('10:00'), current_close_at: t('18:00'), forced_close_at: t('18:30') }

describe('liveStatus (same rules as the server)', () => {
  it('is Scheduled before the start', () => {
    expect(liveStatus(rfq, ms('09:59'))).toBe('SCHEDULED')
  })
  it('is Active from the start until just before the close', () => {
    expect(liveStatus(rfq, ms('10:00'))).toBe('ACTIVE')
    expect(liveStatus(rfq, ms('18:00') - 1)).toBe('ACTIVE')
  })
  it('is Closed at the close time when not extended to the forced close', () => {
    expect(liveStatus(rfq, ms('18:00'))).toBe('CLOSED')
  })
  it('is Force Closed when extensions reached the forced close', () => {
    const extended = { ...rfq, current_close_at: t('18:30') }
    expect(liveStatus(extended, ms('18:29'))).toBe('ACTIVE')
    expect(liveStatus(extended, ms('18:30'))).toBe('FORCE_CLOSED')
  })
})

describe('fmtCountdown', () => {
  it('shows mm:ss under an hour', () => {
    expect(fmtCountdown(65_000)).toBe('01:05')
  })
  it('adds hours and days when needed', () => {
    expect(fmtCountdown(3_723_000)).toBe('1:02:03')
    expect(fmtCountdown(90_061_000)).toBe('1d 01:01:01')
  })
  it('never goes negative', () => {
    expect(fmtCountdown(-5_000)).toBe('00:00')
  })
})

describe('fmtDurationBetween', () => {
  it('formats whole minutes, seconds, and both', () => {
    expect(fmtDurationBetween(t('18:00'), t('18:05'))).toBe('5 min')
    expect(fmtDurationBetween('2026-11-03T18:00:00Z', '2026-11-03T18:00:45Z')).toBe('45 s')
    expect(fmtDurationBetween('2026-11-03T18:00:00Z', '2026-11-03T18:02:30Z')).toBe('2 min 30 s')
  })
})

describe('errorMessage', () => {
  it('passes through a plain detail string', () => {
    expect(errorMessage({ detail: 'Bidding is closed for this RFQ.' }, 409)).toBe(
      'Bidding is closed for this RFQ.',
    )
  })
  it('turns FastAPI validation errors into readable text', () => {
    const body = {
      detail: [
        { loc: ['body'], msg: 'Value error, Forced bid close time must be later than bid close time.' },
        { loc: ['body', 'freight_charges'], msg: 'Input should be greater than or equal to 0' },
      ],
    }
    expect(errorMessage(body, 422)).toBe(
      'Forced bid close time must be later than bid close time. · ' +
        'freight_charges: Input should be greater than or equal to 0',
    )
  })
  it('falls back to the status code', () => {
    expect(errorMessage(null, 500)).toBe('Request failed (500)')
  })
})
