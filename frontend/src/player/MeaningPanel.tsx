import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { api } from '../api'
import type { Alignment, Meanings } from '../types'
import Player from './Player'
import { BADGE_LABEL, badgeState, findMeaning, keyOf, wordRefs } from './meanings'
import './meanings.css'

function Badge({ origin, reviewed }: { origin: 'seed' | 'user' | 'machine'; reviewed: boolean }) {
  const st = badgeState(origin, reviewed)
  return <span className={'mbadge ' + st}>{BADGE_LABEL[st]}</span>
}

/** Player plus meaning panel, table and summary. Hooks into the player's DOM (.vline / .w) without modifying it. */
export function MeaningPlayer({ src, alignment, meanings }: { src: string; alignment: Alignment; meanings?: Meanings }) {
  const root = useRef<HTMLDivElement>(null)
  const refs = useMemo(() => wordRefs(alignment, []), [alignment])
  const [sel, setSel] = useState<string | null>(null)
  const [cur, setCur] = useState<string | null>(null)

  const spans = useCallback(() => {
    const out: HTMLElement[][] = []
    root.current?.querySelectorAll('.verse .vline').forEach(l => {
      out.push(Array.from(l.querySelectorAll<HTMLElement>(':scope > .w')))
    })
    return out
  }, [])
  const locate = useCallback((el: Element | null) => {
    const w = el?.closest('.verse .w')
    if (!w) return null
    const all = spans()
    for (let l = 0; l < all.length; l++) { const i = all[l].indexOf(w as HTMLElement); if (i >= 0) return keyOf(l, i) }
    return null
  }, [spans])

  useEffect(() => {
    const el = root.current
    if (!el) return
    const prep = () => spans().flat().forEach(s => { s.tabIndex = 0; s.setAttribute('role', 'button') })
    prep()
    const onFocus = (e: FocusEvent) => { const k = locate(e.target as Element); if (k) setSel(k) }
    const onKey = (e: KeyboardEvent) => {
      if ((e.key === 'Enter') && (e.target as Element).matches?.('.verse .w')) (e.target as HTMLElement).click()
    }
    const onClick = (e: MouseEvent) => { const k = locate(e.target as Element); if (k) setSel(k) }
    const obs = new MutationObserver(() => {
      prep()
      const c = el.querySelector('.verse .w.cur')
      const k = c ? locate(c) : null
      setCur(k)
      if (k) setSel(k)
    })
    obs.observe(el, { subtree: true, childList: true, attributes: true, attributeFilter: ['class'] })
    el.addEventListener('focusin', onFocus)
    el.addEventListener('keydown', onKey)
    el.addEventListener('click', onClick)
    return () => { obs.disconnect(); el.removeEventListener('focusin', onFocus); el.removeEventListener('keydown', onKey); el.removeEventListener('click', onClick) }
  }, [spans, locate])

  const playWord = (line: number, index: number) => { setSel(keyOf(line, index)); spans()[line]?.[index]?.click() }

  const rows = refs.map(r => ({ r, m: findMeaning(meanings, r.line, r.index, r.text) }))
  const hasWords = rows.some(x => x.m)
  const summary = meanings?.summary ?? null
  const selRow = rows.find(x => keyOf(x.r.line, x.r.index) === sel)

  return (
    <div ref={root}>
      <Player src={src} alignment={alignment} />
      <div className="card meaning-panel" aria-label="Meaning" aria-live="polite">
        <h3>Meaning</h3>
        {!selRow ? <p className="muted">Select a word to see its meaning.</p> : (
          <div>
            <div className="devanagari" style={{ fontSize: '1.6rem' }}>{selRow.r.text}</div>
            {selRow.m ? (
              <>
                <div>{selRow.m.meaning}</div>
                {selRow.m.grammar && <div className="muted">Grammar: {selRow.m.grammar}</div>}
              </>
            ) : <div className="muted">No meaning added for this word.</div>}
          </div>
        )}
      </div>
      <div className="card" aria-label="Word by word">
        <h3>Word by word</h3>
        {!hasWords ? <p className="muted">No meanings added yet</p> : (
          <>
            <table className="mtable">
              <thead><tr><th>Word</th><th>Meaning</th><th>Grammar</th></tr></thead>
              <tbody>
                {rows.filter(x => x.m).map(({ r, m }) => {
                  const k = keyOf(r.line, r.index)
                  return (
                    <tr key={k} className={(k === cur ? 'cur ' : '') + (k === sel ? 'sel' : '')} tabIndex={0}
                      onClick={() => playWord(r.line, r.index)}
                      onKeyDown={e => { if (e.key === 'Enter') playWord(r.line, r.index) }}>
                      <td className="devanagari">{r.text}</td><td>{m!.meaning}</td><td>{m!.grammar ?? ''}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            {(() => {
              const draft = rows.find(x => x.m && badgeState(x.m.origin, x.m.reviewed) === 'draft')
              const any = rows.find(x => x.m)!.m!
              const b = draft?.m ?? any
              return <Badge origin={b.origin} reviewed={b.reviewed} />
            })()}
          </>
        )}
      </div>
      <div className="card" aria-label="Summary">
        <h3>Summary</h3>
        {!summary ? <p className="muted">No meanings added yet</p> : (
          <>
            <p><strong>Translation:</strong> {summary.translation}</p>
            {summary.explanation && <p><strong>Explanation:</strong> {summary.explanation}</p>}
            <Badge origin={summary.origin} reviewed={summary.reviewed} />
          </>
        )}
      </div>
    </div>
  )
}

export function EditMeanings({ verseId, lines, alignment, meanings, onSaved }: {
  verseId: string; lines: string[]; alignment: Alignment | null; meanings?: Meanings; onSaved: () => void
}) {
  const refs = useMemo(() => wordRefs(alignment, lines), [alignment, lines])
  const init = useMemo(() => {
    const m: Record<string, { meaning: string; grammar: string }> = {}
    for (const r of refs) {
      const f = findMeaning(meanings, r.line, r.index, r.text)
      m[keyOf(r.line, r.index)] = { meaning: f?.meaning ?? '', grammar: f?.grammar ?? '' }
    }
    return m
  }, [refs, meanings])
  const [words, setWords] = useState(init)
  const [translation, setTranslation] = useState(meanings?.summary?.translation ?? '')
  const [explanation, setExplanation] = useState(meanings?.summary?.explanation ?? '')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setErr(''); setBusy(true)
    try {
      await api.saveMeanings(verseId, {
        words: refs.map(r => ({ r, v: words[keyOf(r.line, r.index)] })).filter(x => x.v.meaning.trim())
          .map(({ r, v }) => ({ line: r.line, index: r.index, text: r.text, meaning: v.meaning.trim(), grammar: v.grammar.trim() || null })),
        ...(translation.trim() ? { summary: { translation: translation.trim(), explanation: explanation.trim() || null } } : {}),
        origin: 'user', reviewed: true,
      })
      onSaved()
    } catch (x) { setErr((x as Error).message) }
    setBusy(false)
  }

  return (
    <details className="card">
      <summary>Edit meanings</summary>
      <form onSubmit={submit} style={{ marginTop: '1rem' }}>
        {refs.map(r => {
          const k = keyOf(r.line, r.index)
          const set = (f: 'meaning' | 'grammar') => (e: { target: { value: string } }) =>
            setWords({ ...words, [k]: { ...words[k], [f]: e.target.value } })
          return (
            <div key={k} className="medit-row">
              <span className="devanagari medit-word">{r.text}</span>
              <input aria-label={`Meaning of ${r.text}`} placeholder="Meaning" value={words[k]?.meaning ?? ''} onChange={set('meaning')} />
              <input aria-label={`Grammar of ${r.text}`} placeholder="Grammar" value={words[k]?.grammar ?? ''} onChange={set('grammar')} />
            </div>
          )
        })}
        <label>Translation<textarea rows={2} value={translation} onChange={e => setTranslation(e.target.value)} /></label>
        <label>Explanation<textarea rows={3} value={explanation} onChange={e => setExplanation(e.target.value)} /></label>
        {err && <p className="danger" role="alert">{err}</p>}
        <button className="btn" disabled={busy}>{busy ? 'Saving…' : 'Save'}</button>
      </form>
    </details>
  )
}
