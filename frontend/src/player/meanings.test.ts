import { describe, expect, it } from 'vitest'
import { badgeState, findMeaning, meaningsState, wordRefs } from './meanings'
import type { Meanings, WordMeaning } from '../types'

// Fixture data only.
const w = (o: Partial<WordMeaning> = {}): WordMeaning => ({
  line: 0, index: 1, text: 'abc', meaning: 'm', grammar: null, origin: 'user', reviewed: true, ...o,
})

describe('findMeaning', () => {
  const m: Meanings = { words: [w()], summary: null }
  it('matches by line/index/text', () => expect(findMeaning(m, 0, 1, 'abc')?.meaning).toBe('m'))
  it('ignores text mismatch', () => expect(findMeaning(m, 0, 1, 'xyz')).toBeNull())
  it('ignores other positions and missing meanings', () => {
    expect(findMeaning(m, 1, 1, 'abc')).toBeNull()
    expect(findMeaning(undefined, 0, 1, 'abc')).toBeNull()
  })
})
describe('badge and state', () => {
  it('badge', () => {
    expect(badgeState('machine', false)).toBe('draft')
    expect(badgeState('machine', true)).toBe('reviewed')
    expect(badgeState('seed', false)).toBe('reviewed')
  })
  it('state', () => {
    expect(meaningsState(undefined)).toBe('none')
    expect(meaningsState({ words: [], summary: null })).toBe('none')
    expect(meaningsState({ words: [w()], summary: null })).toBe('reviewed')
    expect(meaningsState({ words: [w({ origin: 'machine', reviewed: false })], summary: null })).toBe('draft')
  })
})
describe('wordRefs', () => {
  it('splits verse lines without alignment', () => {
    expect(wordRefs(null, ['a b', 'c'])).toEqual([
      { line: 0, index: 0, text: 'a' }, { line: 0, index: 1, text: 'b' }, { line: 1, index: 0, text: 'c' }])
  })
})
