import type { BatchJob, BatchRequest, BatchScope, JobStatus } from '../../types'

export interface BatchForm {
  kanda: string; sarga: string; verseId: string
  voiceId: string; steps: string; seed: string; meterId: string
}

const num = (s: string): number | null => {
  if (!s.trim()) return null
  const n = Number(s)
  return Number.isFinite(n) ? n : null
}

/** Build the preview/create body. Blank kanda/sarga/verse mean "all"; verse needs a sarga. */
export function buildBatchBody(f: BatchForm): BatchRequest {
  const kanda = num(f.kanda)
  const sarga = kanda === null ? null : num(f.sarga)
  const verse_id = sarga === null || !f.verseId ? null : f.verseId
  const seed = num(f.seed)
  return {
    epic: 'ramayana', kanda, sarga, verse_id,
    voice_id: f.voiceId, steps: num(f.steps) ?? 16,
    ...(seed === null ? {} : { seed }),
    meter_id: f.meterId || null,
  }
}

/** The list endpoint has no total; sum the per-status counts. */
export const countsTotal = (counts: Record<string, number> | null | undefined): number =>
  Object.values(counts ?? {}).reduce((a, b) => a + b, 0)

export function scopeLabel(s: BatchScope, kandaName?: string | null): string {
  if (s.kanda === null) return 'Whole Ramayana (all kāṇḍas)'
  const k = kandaName ? `Kāṇḍa ${s.kanda} (${kandaName})` : `Kāṇḍa ${s.kanda}`
  if (s.sarga === null) return `${k}, all sargas`
  if (!s.verse_id) return `${k}, sarga ${s.sarga}, all verses`
  return `${k}, sarga ${s.sarga}, verse ${s.verse_id}`
}

/** Whole-epic scope needs the extra confirmation. */
export const needsConfirmAll = (s: BatchScope) => s.kanda === null

export const ACTIVE: JobStatus[] = ['awaiting_result', 'queued', 'running', 'aligning']
/** Statuses that keep the polling going (awaiting_result is the user's step, but still unfinished). */
export const POLLING: JobStatus[] = ['awaiting_result', 'queued', 'running', 'aligning']
export const isBatchActive = (jobs: Pick<BatchJob, 'status'>[]) => jobs.some(j => POLLING.includes(j.status))

export function statusCounts(jobs: Pick<BatchJob, 'status'>[]): Record<string, number> {
  const c: Record<string, number> = {}
  for (const j of jobs) c[j.status] = (c[j.status] ?? 0) + 1
  return c
}

const ORDER = ['awaiting_result', 'queued', 'running', 'aligning', 'done', 'failed', 'cancelled']
export function statusSummary(counts: Record<string, number>): string {
  const keys = Object.keys(counts).filter(k => counts[k] > 0)
  keys.sort((a, b) => (ORDER.indexOf(a) < 0 ? 99 : ORDER.indexOf(a)) - (ORDER.indexOf(b) < 0 ? 99 : ORDER.indexOf(b)))
  if (!keys.length) return 'no jobs'
  return keys.map(k => `${counts[k]} ${k.replace('_', ' ')}`).join(', ')
}

export function meterBreakdown(m: { meter_id: string; count: number }[]): string {
  return [...m].sort((a, b) => b.count - a.count).map(x => `${x.meter_id}: ${x.count}`).join(', ')
}

/** Summary line for a Drive import; `missing` is informational, not an error. */
export function importSummary(r: { accepted: number; failed: number; ignored?: number; missing: number }): { text: string; note: string; isError: boolean } {
  const text = `Accepted ${r.accepted}, failed ${r.failed}, missing ${r.missing}${r.ignored ? `, ignored ${r.ignored}` : ''}.`
  const note = r.missing > 0 ? `${r.missing} verses not rendered yet; re-run the import later` : ''
  return { text, note, isError: r.failed > 0 }
}
