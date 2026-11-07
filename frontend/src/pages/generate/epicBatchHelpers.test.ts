import { describe, expect, it } from 'vitest'
import {
  buildBatchBody, countsTotal, isBatchActive, meterBreakdown, needsConfirmAll, scopeLabel, importSummary, statusCounts, statusSummary,
} from './epicBatchHelpers'

// FIXTURE data only: ids and names are placeholders, not real verses.
const form = { kanda: '2', sarga: '5', verseId: 'fixture-v1', voiceId: 'vx', steps: '24', seed: '', meterId: '' }

describe('buildBatchBody', () => {
  it('builds a single-verse body', () => {
    expect(buildBatchBody(form)).toEqual({
      epic: 'ramayana', kanda: 2, sarga: 5, verse_id: 'fixture-v1', voice_id: 'vx', steps: 24, meter_id: null,
    })
  })
  it('drops sarga and verse when kanda is all', () => {
    const b = buildBatchBody({ ...form, kanda: '' })
    expect([b.kanda, b.sarga, b.verse_id]).toEqual([null, null, null])
  })
  it('drops verse when no sarga; passes seed and meter', () => {
    const b = buildBatchBody({ ...form, sarga: '', seed: '7', meterId: 'm1' })
    expect(b.verse_id).toBeNull(); expect(b.seed).toBe(7); expect(b.meter_id).toBe('m1')
  })
  it('defaults steps', () => expect(buildBatchBody({ ...form, steps: 'x' }).steps).toBe(16))
})

describe('scopeLabel', () => {
  it('covers each scope', () => {
    expect(scopeLabel({ epic: 'ramayana', kanda: null, sarga: null, verse_id: null })).toMatch(/Whole/)
    expect(scopeLabel({ epic: 'ramayana', kanda: 1, sarga: null, verse_id: null }, 'Fx')).toBe('Kāṇḍa 1 (Fx), all sargas')
    expect(scopeLabel({ epic: 'ramayana', kanda: 1, sarga: 2, verse_id: null })).toBe('Kāṇḍa 1, sarga 2, all verses')
    expect(scopeLabel({ epic: 'ramayana', kanda: 1, sarga: 2, verse_id: 'v' })).toBe('Kāṇḍa 1, sarga 2, verse v')
  })
  it('flags whole-epic', () => {
    expect(needsConfirmAll({ epic: 'ramayana', kanda: null, sarga: null, verse_id: null })).toBe(true)
    expect(needsConfirmAll({ epic: 'ramayana', kanda: 1, sarga: null, verse_id: null })).toBe(false)
  })
})

describe('status helpers', () => {
  const jobs = [{ status: 'done' as const }, { status: 'done' as const }, { status: 'awaiting_result' as const }, { status: 'failed' as const }]
  it('counts and summarises', () => {
    expect(statusCounts(jobs)).toEqual({ done: 2, awaiting_result: 1, failed: 1 })
    expect(statusSummary(statusCounts(jobs))).toBe('1 awaiting result, 2 done, 1 failed')
    expect(statusSummary({})).toBe('no jobs')
  })
  it('detects active', () => {
    expect(isBatchActive(jobs)).toBe(true)
    expect(isBatchActive([{ status: 'done' }, { status: 'failed' }])).toBe(false)
  })
  it('orders meters by count', () => expect(meterBreakdown([{ meter_id: 'a', count: 1 }, { meter_id: 'b', count: 5 }])).toBe('b: 5, a: 1'))
})

describe('seed and countsTotal', () => {
  const base = { kanda: '', sarga: '', verseId: '', voiceId: 'v', steps: '16', meterId: '' }
  it('omits seed when blank or whitespace', () => {
    expect('seed' in buildBatchBody({ ...base, seed: '' })).toBe(false)
    expect('seed' in buildBatchBody({ ...base, seed: '   ' })).toBe(false)
  })
  it('keeps numeric seeds including 0', () => {
    expect(buildBatchBody({ ...base, seed: '0' }).seed).toBe(0)
    expect(buildBatchBody({ ...base, seed: '42' }).seed).toBe(42)
  })
  it('sums counts', () => {
    expect(countsTotal({ done: 109, failed: 1 })).toBe(110)
    expect(countsTotal(undefined)).toBe(0)
  })
})

describe('importSummary', () => {
  // FIXTURE counts only.
  it('notes missing verses without flagging an error', () => {
    const r = importSummary({ accepted: 3, failed: 0, ignored: 0, missing: 2 })
    expect(r.text).toBe('Accepted 3, failed 0, missing 2.')
    expect(r.note).toBe('2 verses not rendered yet; re-run the import later')
    expect(r.isError).toBe(false)
  })
  it('flags failures, no note when nothing missing', () => {
    const r = importSummary({ accepted: 1, failed: 1, ignored: 4, missing: 0 })
    expect(r.text).toContain('ignored 4')
    expect(r.note).toBe('')
    expect(r.isError).toBe(true)
  })
})
