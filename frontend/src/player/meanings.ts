import type { Alignment, MeaningOrigin, Meanings, WordMeaning } from '../types'

export const norm = (s: string) => s.normalize('NFC').trim()
export const keyOf = (line: number, index: number) => `${line}:${index}`

/** Find the meaning for the word at (line,index); ignored if its text differs from the alignment word. */
export function findMeaning(m: Meanings | null | undefined, line: number, index: number, text: string): WordMeaning | null {
  const w = m?.words?.find(x => x.line === line && x.index === index)
  if (!w || norm(w.text) !== norm(text)) return null
  return w
}

export type BadgeState = 'draft' | 'reviewed'
export function badgeState(origin: MeaningOrigin, reviewed: boolean): BadgeState {
  return origin === 'machine' && !reviewed ? 'draft' : 'reviewed'
}
export const BADGE_LABEL: Record<BadgeState, string> = { draft: 'Machine draft, unreviewed', reviewed: 'Reviewed' }

export type MeaningsState = 'none' | 'draft' | 'reviewed'
export const MEANINGS_STATE_LABEL: Record<MeaningsState, string> = { none: 'none', draft: 'draft', reviewed: 'reviewed' }
/** Overall state: none if empty, draft if any entry is an unreviewed machine draft. */
export function meaningsState(m: Meanings | null | undefined): MeaningsState {
  if (!m || (m.words.length === 0 && !m.summary)) return 'none'
  const items = [...m.words, ...(m.summary ? [m.summary] : [])]
  return items.some(i => badgeState(i.origin, i.reviewed) === 'draft') ? 'draft' : 'reviewed'
}

export interface WordRef { line: number; index: number; text: string }
/** Word list per alignment, or whitespace split of verse lines when no alignment. */
export function wordRefs(alignment: Alignment | null, lines: string[]): WordRef[] {
  if (alignment) return alignment.lines.flatMap((l, line) => l.words.map((w, index) => ({ line, index, text: w.text })))
  return lines.flatMap((l, line) => l.split(/\s+/).filter(Boolean).map((text, index) => ({ line, index, text })))
}
