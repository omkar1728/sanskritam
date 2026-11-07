import type { EpicLayer, EpicMeaningItem, EpicSummary, EpicVerse } from '../../types'

export type VariantKey = 'critical' | 'vulgate_net' | 'vulgate_in' | 'gitapress' | 'southern' | 'passage' | 'hv_deva' | 'iast' | 'raw'
export const VARIANTS: { key: VariantKey; label: string }[] = [
  { key: 'critical', label: 'Critical' },
  { key: 'vulgate_net', label: 'Vulgate (net)' },
  { key: 'vulgate_in', label: 'Vulgate (valmikiramayan.in)' },
  { key: 'gitapress', label: 'Gita Press OCR' },
  { key: 'southern', label: 'Southern (SARIT)' },
  { key: 'passage', label: 'Supplement / star passage' },
  { key: 'hv_deva', label: 'Devanagari (machine transliteration)' },
  { key: 'iast', label: 'IAST original' },
  { key: 'raw', label: 'Raw source text' },
]
const FIELD = {
  critical: 'critical_smith', vulgate_net: 'vulgate_net', vulgate_in: 'vulgate_in', gitapress: 'vulgate_gitapress', southern: 'southern_sarit',
} as const

const strs = (a: unknown): string[] | null => {
  const x = typeof a === 'string' ? [a] : Array.isArray(a) ? a.filter((y): y is string => typeof y === 'string' && y.trim() !== '') : []
  return x.length ? x : null
}
export function variantLines(v: EpicVerse, key: VariantKey): string[] | null {
  if (key === 'hv_deva') return strs(v.text?.devanagari_machine_transliterated) ?? strs(v.text?.padas_devanagari)
  if (key === 'iast') return strs(v.text?.iast_original)
  if (key === 'raw') return strs(v.text?.raw_source)
  if (key === 'passage') return strs((v.passage?.lines ?? []).map(l => (typeof l === 'string' ? l : l.text ?? '')))
  const t = v.text?.[FIELD[key]]
  if (!t) return null
  if (key === 'critical') {
    const c = v.text?.critical_smith
    if (c?.punctuated_derived) return c.punctuated_derived.split('\n')
  }
  return t.lines && t.lines.length ? t.lines : null
}
export function variantSource(v: EpicVerse, key: VariantKey): string | null {
  if (key === 'hv_deva') return v.devanagari_origin ?? 'machine transliteration from IAST'
  if (key === 'iast') return 'GRETIL IAST'
  if (key === 'raw') return 'GRETIL raw source line(s)'
  if (key === 'passage') return v.passage?.passage_id ? `Critical Edition supplement ${v.passage.passage_id}` : null
  return v.text?.[FIELD[key]]?.source ?? null
}
export const availableVariants = (v: EpicVerse): VariantKey[] => VARIANTS.map(x => x.key).filter(k => variantLines(v, k))
/** Preferred variant if present, else the first available in VARIANTS order, else null. */
export function pickVariant(v: EpicVerse, pref: string | null | undefined): VariantKey | null {
  const av = availableVariants(v)
  if (pref && (av as string[]).includes(pref)) return pref as VariantKey
  return av[0] ?? null
}
export const isVariantKey = (s: unknown): s is VariantKey => VARIANTS.some(x => x.key === s)

export function refLabel(v: EpicVerse): string {
  const r = v.refs
  const parts: string[] = []
  if (r?.critical_smith && r.critical_smith.sarga != null) parts.push(`Critical ${r.critical_smith.sarga}.${r.critical_smith.verse}`)
  const vul = r?.vulgate_net_locators?.length ? r.vulgate_net_locators.map(x => x.replace(/-/g, '.'))
    : r?.vulgate_in_locators?.length ? r.vulgate_in_locators
    : r?.vulgate_gitapress_refs?.length ? r.vulgate_gitapress_refs : []
  if (vul.length) parts.push(`Vulgate ${vul.join(', ')}`)
  if (!parts.length) parts.push(v.id)
  return parts.join(' · ')
}

export const epicPath = (epic: string) => `/epics/${epic}`
export const kandaPath = (k: number, epic = 'ramayana') => `/epics/${epic}/${k}`
export const sargaPath = (k: number, s: number, epic = 'ramayana') => `/epics/${epic}/${k}/${s}`

/** Heading labels for an epic; falls back to the Ramayana terms (or generic ones) while /api/epics loads. */
export function epicLabels(epic: EpicSummary | null | undefined, id: string): { book: string; chapter: string; name: string } {
  const ram = id === 'ramayana'
  return {
    book: epic?.book_label || (ram ? 'Kāṇḍa' : 'Part'),
    chapter: epic?.chapter_label || (ram ? 'Sarga' : 'Chapter'),
    name: epic?.name || (id ? id.charAt(0).toUpperCase() + id.slice(1) : 'Epic'),
  }
}
/** '225 Adhyayas', '1 Adhyaya'. */
export const countLabel = (n: number, label: string) => `${n} ${label}${n === 1 ? '' : 's'}`

/** Chapter number to show: adhyaya_display for Mahabharata layers, else the sarga number. */
export const chapterNo = (sarga: number, display?: number | null) => display ?? (sarga >= 1000 ? sarga - 1000 : sarga)
/** Layer, inferred from the sarga number when the API omits it (1000+N = Southern only, 0 = unplaced). */
const layerOf = (layer: EpicLayer | null | undefined, sarga: number): EpicLayer | null =>
  sarga === 0 ? 'supplements_unplaced' : sarga >= 1000 ? 'southern_only' : layer ?? null
/** Badge text for the chapter layer; null for ordinary critical chapters. */
export function layerBadge(layer: EpicLayer | null | undefined, sarga: number): string | null {
  const l = layerOf(layer, sarga)
  if (l === 'supplements_unplaced') return 'Unplaced supplements'
  if (l === 'southern_only') return 'Southern only'
  return null
}
/** Heading for a chapter, e.g. 'Adhyaya 24', 'Unplaced supplements'. */
export function chapterTitle(chapter: string, sarga: number, display?: number | null, layer?: EpicLayer | null, withLayer = false): string {
  const l = layerOf(layer, sarga)
  if (l === 'supplements_unplaced') return 'Unplaced supplements'
  return `${chapter} ${chapterNo(sarga, display)}${withLayer && l === 'southern_only' ? ' (Southern only)' : ''}`
}
/** Badge text for a verse kind; null for plain critical verses. */
export function verseKindBadge(kind: string | null | undefined): string | null {
  if (kind === 'vulgate_only') return 'vulgate only'
  if (kind === 'southern_only') return 'Southern only'
  if (kind === 'supplement') return 'Supplement'
  return null
}
/** Label for one source-labelled meaning unit. Never returns 'null'. */
export function unitLabel(m: EpicMeaningItem): string {
  const loc = m.net_locator ?? m.in_locator ?? m.verse_ref
  return `${m.source ?? 'unknown source'}${m.translator ? ` (${m.translator})` : ''}${loc ? ` [${loc}]` : ''}`
}
/** Best-effort text for an unplaced item that may be a string or an object. */
export function looseText(x: unknown): string {
  if (x == null) return ''
  if (typeof x === 'string') return x
  if (typeof x === 'object') {
    const o = x as { text?: unknown; unit_id?: unknown }
    if (typeof o.text === 'string') return o.text
    if (typeof o.unit_id === 'string') return o.unit_id
  }
  return JSON.stringify(x)
}
export function parseNum(s: string | undefined): number | null {
  if (!s || !/^\d+$/.test(s)) return null
  return Number(s)
}

export function isUnverified(m: EpicMeaningItem): boolean {
  const t = `${m.provenance ?? ''} ${m.source ?? ''}`.toLowerCase()
  return t.includes('unverified') || (m.rights ?? '').toLowerCase().includes('unverified') || (m.rights ?? '').toLowerCase().includes('machine-generated') || t.includes('ocr') || !!(m.ocr_flags && m.ocr_flags.length)
}

const KEY = 'epics.reader.variant'
export function loadVariantPref(): string | null {
  try { return localStorage.getItem(KEY) } catch { return null }
}
export function saveVariantPref(k: string): void {
  try { localStorage.setItem(KEY, k) } catch { /* storage unavailable */ }
}

// ---- Source filter (Mahabharata / Harivamsha chapter page) ----
export type SourceKey = 'critical' | 'southern' | 'itihasa' | 'enjoy' | 'supplement'
export const SOURCE_FILTERS: { key: SourceKey; label: string }[] = [
  { key: 'critical', label: 'Critical Edition (Smith)' },
  { key: 'southern', label: 'Southern text (SARIT)' },
  { key: 'itihasa', label: 'English: Itihasa (Dutt)' },
  { key: 'enjoy', label: 'English: enjoylearningsanskrit' },
  { key: 'supplement', label: 'Supplement passages' },
]
const hasEnglish = (v: EpicVerse, needle: string) =>
  !!v.meanings?.english_translation?.some(m => `${m?.source ?? ''}`.toLowerCase().includes(needle))
/** Which filterable sources a verse has. Tolerates missing fields. */
export function verseSources(v: EpicVerse): SourceKey[] {
  const out: SourceKey[] = []
  if (v.text?.critical_smith?.lines?.length) out.push('critical')
  if (v.text?.southern_sarit?.lines?.length) out.push('southern')
  if (hasEnglish(v, 'itihasa')) out.push('itihasa')
  if (hasEnglish(v, 'enjoylearningsanskrit')) out.push('enjoy')
  if (v.supplements?.length || v.kind === 'supplement') out.push('supplement')
  return out
}
export function sourceCounts(vs: EpicVerse[]): Record<SourceKey, number> {
  const c: Record<SourceKey, number> = { critical: 0, southern: 0, itihasa: 0, enjoy: 0, supplement: 0 }
  for (const v of vs) for (const k of verseSources(v)) c[k]++
  return c
}
/** OR semantics; an empty selection shows everything. */
export function filterBySources(vs: EpicVerse[], sel: SourceKey[]): EpicVerse[] {
  if (!sel.length) return vs
  return vs.filter(v => verseSources(v).some(k => sel.includes(k)))
}
const SKEY = 'epics.reader.sources'
export function loadSourceSel(): SourceKey[] {
  try {
    const a = JSON.parse(localStorage.getItem(SKEY) ?? '[]')
    return Array.isArray(a) ? SOURCE_FILTERS.map(s => s.key).filter(k => a.includes(k)) : []
  } catch { return [] }
}
export function saveSourceSel(s: SourceKey[]): void {
  try { localStorage.setItem(SKEY, JSON.stringify(s)) } catch { /* storage unavailable */ }
}
