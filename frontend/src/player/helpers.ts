import type { Alignment, AlignWord } from '../types'

export interface FlatWord { line: number; index: number; word: AlignWord; pieces: string[] | null }

const VIRAMA = 0x094d
const isBase = (c: number) =>
  (c >= 0x0904 && c <= 0x0914) || (c >= 0x0915 && c <= 0x0939) || (c >= 0x0958 && c <= 0x0961)

/** Split Devanagari into atomic units: one base letter with its matra/virama/marks. */
export function atomicUnits(text: string): string[] {
  const out: string[] = []
  for (const ch of text) {
    const c = ch.codePointAt(0)!
    if (isBase(c) || out.length === 0) out.push(ch)
    else out[out.length - 1] += ch
  }
  return out
}

const endsVirama = (s: string) => s.codePointAt(s.length - 1) === VIRAMA

/** Merge virama-final units into the preceding unit (coda), or the next if leading. */
export function syllableUnits(text: string): string[] {
  const out: string[] = []
  let carry = ''
  for (const u of atomicUnits(text)) {
    if (endsVirama(u)) {
      if (out.length) out[out.length - 1] += u
      else carry += u
    } else {
      out.push(carry + u)
      carry = ''
    }
  }
  if (carry) out.push(carry)
  return out
}

/** Split a word's text into exactly `n` display pieces, or null if impossible. */
export function groupGraphemes(text: string, n: number): string[] | null {
  if (n <= 0 || !text) return null
  const cands: string[][] = [syllableUnits(text), atomicUnits(text)]
  const Seg = (Intl as unknown as { Segmenter?: new (l: string, o: object) => { segment(t: string): Iterable<{ segment: string }> } }).Segmenter
  if (Seg) cands.push(Array.from(new Seg('sa', { granularity: 'grapheme' }).segment(text), s => s.segment))
  return cands.find(c => c.length === n) ?? null
}

export function flattenWords(a: Alignment): FlatWord[] {
  const out: FlatWord[] = []
  a.lines.forEach((l, li) =>
    l.words.forEach(w => out.push({ line: li, index: out.length, word: w, pieces: groupGraphemes(w.text, w.syllables.length) })))
  return out
}

/** Index of word containing t; between words, the most recent word started; -1 before first. */
export function findWordIndex(words: { start: number; end: number }[], t: number): number {
  let lo = 0, hi = words.length - 1, ans = -1
  while (lo <= hi) {
    const m = (lo + hi) >> 1
    if (words[m].start <= t) { ans = m; lo = m + 1 } else hi = m - 1
  }
  if (ans >= 0 && t >= words[ans].end + 0.25) return -1
  return ans
}

export function findSyllableIndex(sylls: { start: number; end: number }[], t: number): number {
  for (let i = 0; i < sylls.length; i++) if (t >= sylls[i].start && t < sylls[i].end) return i
  return -1
}

export function formatTime(t: number): string {
  if (!isFinite(t) || t < 0) t = 0
  const m = Math.floor(t / 60), s = t - m * 60
  return `${m}:${s.toFixed(1).padStart(4, '0')}`
}
