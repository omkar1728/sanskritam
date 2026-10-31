import { describe, expect, it } from 'vitest'
import { atomicUnits, findSyllableIndex, findWordIndex, groupGraphemes, syllableUnits } from './helpers'

describe('grapheme grouping', () => {
  it('atomic units', () => expect(atomicUnits('कर्मण्येव')).toEqual(['क', 'र्', 'म', 'ण्', 'ये', 'व']))
  it('merges codas into syllables', () => expect(syllableUnits('कर्मण्येव')).toEqual(['कर्', 'मण्', 'ये', 'व']))
  it('groups to requested count', () => {
    expect(groupGraphemes('कर्मण्येव', 4)).toEqual(['कर्', 'मण्', 'ये', 'व'])
    expect(groupGraphemes('कर्मण्येव', 6)?.length).toBe(6)
  })
  it('returns null on mismatch', () => expect(groupGraphemes('कर्मण्येव', 3)).toBeNull())
})

describe('time lookup', () => {
  const w = [{ start: 0.5, end: 1 }, { start: 1, end: 2 }, { start: 3, end: 4 }]
  it('finds words', () => {
    expect(findWordIndex(w, 0.1)).toBe(-1)
    expect(findWordIndex(w, 0.7)).toBe(0)
    expect(findWordIndex(w, 1.5)).toBe(1)
    expect(findWordIndex(w, 2.1)).toBe(1)
    expect(findWordIndex(w, 2.9)).toBe(-1)
    expect(findWordIndex(w, 3.5)).toBe(2)
  })
  it('finds syllables', () => {
    expect(findSyllableIndex(w, 1.2)).toBe(1)
    expect(findSyllableIndex(w, 2.5)).toBe(-1)
  })
})
