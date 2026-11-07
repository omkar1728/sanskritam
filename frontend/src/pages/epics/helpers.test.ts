import { describe, expect, it } from 'vitest'
import type { EpicVerse } from '../../types'
import {
  availableVariants, chapterNo, chapterTitle, countLabel, epicLabels, isUnverified, kandaPath, layerBadge, looseText, parseNum,
  pickVariant, refLabel, sargaPath, unitLabel, variantLines, variantSource, verseKindBadge,
  loadSourceSel, saveSourceSel, sourceCounts, filterBySources, verseSources,
} from './helpers'

// FIXTURE data only: placeholder strings, not real verse text.
const fx: EpicVerse = {
  id: 'fixture-001-001',
  refs: { critical_smith: { sarga: 3, verse: 7 }, vulgate_net_locators: ['1-4-9'] },
  text: {
    critical_smith: { lines: ['FIXTURE a', 'FIXTURE b'], punctuated_derived: 'FIXTURE a |\nFIXTURE b ||' },
    vulgate_net: null,
    vulgate_gitapress: { lines: ['FIXTURE ocr'] },
  },
}
const vo: EpicVerse = { id: 'fixture-vo', refs: { critical_smith: null, vulgate_in_locators: ['1.1.13'] }, text: { vulgate_in: { lines: ['FIXTURE v'] } } }

describe('epics helpers', () => {
  it('lists available variants', () => {
    expect(availableVariants(fx)).toEqual(['critical', 'gitapress'])
    expect(availableVariants({ id: 'x' })).toEqual([])
  })
  it('picks preferred or falls back', () => {
    expect(pickVariant(fx, 'gitapress')).toBe('gitapress')
    expect(pickVariant(fx, 'vulgate_net')).toBe('critical')
    expect(pickVariant(vo, 'critical')).toBe('vulgate_in')
    expect(pickVariant(vo, null)).toBe('vulgate_in')
    expect(pickVariant({ id: 'x' }, 'critical')).toBeNull()
  })
  it('uses punctuated_derived for critical', () => {
    expect(variantLines(fx, 'critical')).toEqual(['FIXTURE a |', 'FIXTURE b ||'])
    expect(variantLines(fx, 'gitapress')).toEqual(['FIXTURE ocr'])
  })
  it('builds labels', () => {
    expect(refLabel(fx)).toBe('Critical 3.7 · Vulgate 1.4.9')
    expect(refLabel(vo)).toBe('Vulgate 1.1.13')
    expect(refLabel({ id: 'z' })).toBe('z')
  })
  it('builds paths', () => {
    expect(kandaPath(2)).toBe('/epics/ramayana/2')
    expect(sargaPath(2, 15)).toBe('/epics/ramayana/2/15')
    expect(parseNum('12')).toBe(12)
    expect(parseNum('x1')).toBeNull()
    expect(parseNum(undefined)).toBeNull()
  })
  it('flags unverified meanings', () => {
    expect(isUnverified({ source: 'Gita Press via archive.org OCR' })).toBe(true)
    expect(isUnverified({ source: 'a', provenance: 'unverified: x' })).toBe(true)
    expect(isUnverified({ source: 'valmikiramayan.net' })).toBe(false)
  })
  it('builds epic-aware paths', () => {
    expect(kandaPath(1, 'mahabharata')).toBe('/epics/mahabharata/1')
    expect(sargaPath(1, 1024, 'mahabharata')).toBe('/epics/mahabharata/1/1024')
  })
  it('formats labels', () => {
    expect(epicLabels({ id: 'mahabharata', name: 'Mahabharata', kanda_count: 18, verse_count: 1, book_label: 'Parvan', chapter_label: 'Adhyaya' }, 'mahabharata'))
      .toEqual({ book: 'Parvan', chapter: 'Adhyaya', name: 'Mahabharata' })
    expect(epicLabels(null, 'ramayana')).toEqual({ book: 'Kāṇḍa', chapter: 'Sarga', name: 'Ramayana' })
    expect(epicLabels(null, 'harivamsha').book).toBe('Part')
    expect(countLabel(225, 'Adhyaya')).toBe('225 Adhyayas')
    expect(countLabel(1, 'Adhyaya')).toBe('1 Adhyaya')
  })
  it('badges layers and kinds', () => {
    expect(layerBadge('southern_only', 1024)).toBe('Southern only')
    expect(layerBadge('supplements_unplaced', 0)).toBe('Unplaced supplements')
    expect(layerBadge(null, 0)).toBe('Unplaced supplements')
    expect(layerBadge('critical', 3)).toBeNull()
    expect(layerBadge(undefined, 3)).toBeNull()
    expect(chapterNo(1024, 24)).toBe(24)
    expect(chapterNo(5, null)).toBe(5)
    expect(chapterTitle('Adhyaya', 1024, 24, 'southern_only')).toBe('Adhyaya 24')
    expect(chapterTitle('Adhyaya', 1063, null, null, true)).toBe('Adhyaya 63 (Southern only)')
    expect(chapterNo(1063, undefined)).toBe(63)
    expect(layerBadge(null, 1063)).toBe('Southern only')
    expect(chapterTitle('Adhyaya', 0)).toBe('Unplaced supplements')
    expect(verseKindBadge('supplement')).toBe('Supplement')
    expect(verseKindBadge('critical')).toBeNull()
  })
  it('labels meaning units and loose items', () => {
    expect(unitLabel({ source: 'Itihasa', translator: 'Dutt', verse_ref: '1' })).toBe('Itihasa (Dutt) [1]')
    expect(unitLabel({})).toBe('unknown source')
    expect(looseText(null)).toBe('')
    expect(looseText('trans_els_12#1')).toBe('trans_els_12#1')
    expect(looseText({ text: 'abc' })).toBe('abc')
  })
  it('uses southern variant and rights flags', () => {
    const sv: EpicVerse = { id: 's', text: { critical_smith: null, southern_sarit: { lines: ['FIXTURE s'] } } }
    expect(availableVariants(sv)).toEqual(['southern'])
    expect(pickVariant(sv, 'critical')).toBe('southern')
    expect(isUnverified({ source: 'x', rights: 'possibly machine-generated' })).toBe(true)
  })
  it('renders Harivamsha and supplement text fields', () => {
    const hv: EpicVerse = { id: 'HV_x', text: { iast_original: ['FIXTURE iast'], devanagari_machine_transliterated: ['FIXTURE deva'] }, devanagari_origin: 'machine-converted' }
    expect(availableVariants(hv)).toEqual(['hv_deva', 'iast'])
    expect(pickVariant(hv, 'critical')).toBe('hv_deva')
    expect(variantLines(hv, 'hv_deva')).toEqual(['FIXTURE deva'])
    expect(variantSource(hv, 'hv_deva')).toBe('machine-converted')
    const sp: EpicVerse = { id: 'supp', kind: 'supplement', passage: { passage_id: 'FX*1', lines: [{ text: 'FIXTURE p' }, { text: '' }] } }
    expect(variantLines(sp, 'passage')).toEqual(['FIXTURE p'])
    expect(variantSource(sp, 'passage')).toContain('FX*1')
    expect(pickVariant(sp, null)).toBe('passage')
  })
})

describe('source filter', () => {
  const full: EpicVerse = {
    id: 'F1', text: { critical_smith: { lines: ['FIXTURE a'] }, southern_sarit: { lines: ['FIXTURE b'] } },
    meanings: { english_translation: [{ source: 'enjoylearningsanskrit.com (x)' }, { source: 'Itihasa (rahular/itihasa), English by M. N. Dutt' }] },
    supplements: [{ passage_id: 'FX' }],
  }
  const south: EpicVerse = { id: 'F2', kind: 'southern_only', text: { critical_smith: null, southern_sarit: { lines: ['FIXTURE c'] } }, meanings: { english_translation: [] }, supplements: [] }
  const bare: EpicVerse = { id: 'F3' }
  it('detects sources and tolerates missing fields', () => {
    expect(verseSources(full).sort()).toEqual(['critical', 'enjoy', 'itihasa', 'southern', 'supplement'])
    expect(verseSources(south)).toEqual(['southern'])
    expect(verseSources(bare)).toEqual([])
    expect(verseSources({ id: 's', kind: 'supplement' })).toEqual(['supplement'])
  })
  it('counts and filters with OR semantics', () => {
    const vs = [full, south, bare]
    expect(sourceCounts(vs)).toEqual({ critical: 1, southern: 2, itihasa: 1, enjoy: 1, supplement: 1 })
    expect(filterBySources(vs, [])).toHaveLength(3)
    expect(filterBySources(vs, ['southern']).map(v => v.id)).toEqual(['F1', 'F2'])
    expect(filterBySources(vs, ['critical', 'itihasa']).map(v => v.id)).toEqual(['F1'])
  })
  it('survives unavailable storage', () => {
    const orig = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
    Object.defineProperty(globalThis, 'localStorage', { configurable: true, get() { throw new Error('no') } })
    expect(loadSourceSel()).toEqual([])
    expect(() => saveSourceSel(['critical'])).not.toThrow()
    if (orig) Object.defineProperty(globalThis, 'localStorage', orig); else delete (globalThis as Record<string, unknown>).localStorage
  })
})
