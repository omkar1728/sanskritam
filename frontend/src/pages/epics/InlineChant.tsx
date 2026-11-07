import { useEffect, useRef, useState } from 'react'
import { api, audioUrl } from '../../api'
import type { Alignment, AudioRef, Verse } from '../../types'
import { MeaningPlayer } from '../../player/MeaningPanel'

type State = { kind: 'idle' } | { kind: 'loading' } | { kind: 'error'; msg: string }
  | { kind: 'ready'; verse: Verse; alignment: Alignment | null }

/** The Learn page's player (highlighted text, controls, word meanings) inside a verse card; loads when scrolled near. */
export default function InlineChant({ verseId, audio }: { verseId: string; audio: AudioRef }) {
  const box = useRef<HTMLDivElement>(null)
  const [s, setS] = useState<State>({ kind: 'idle' })

  useEffect(() => {
    const el = box.current
    if (!el) return
    let dead = false
    const load = () => {
      setS({ kind: 'loading' })
      Promise.all([api.verse(verseId), api.alignment(audio.job_id).catch(() => null)])
        .then(([verse, alignment]) => { if (!dead) setS({ kind: 'ready', verse, alignment }) })
        .catch(e => { if (!dead) setS({ kind: 'error', msg: e instanceof Error ? e.message : String(e) }) })
    }
    if (typeof IntersectionObserver === 'undefined') { load(); return () => { dead = true } }
    const io = new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) { io.disconnect(); load() } }, { rootMargin: '400px' })
    io.observe(el)
    return () => { dead = true; io.disconnect() }
  }, [verseId, audio.job_id])

  return (
    <div ref={box} className="ep-chant">
      {s.kind === 'ready' && s.alignment && <MeaningPlayer src={audioUrl(audio.job_id)} alignment={s.alignment} meanings={s.verse.meanings} />}
      {s.kind === 'ready' && !s.alignment && (
        <>
          <div className="card">{s.verse.text.map((l, i) => <div key={i} className="devanagari">{l}</div>)}</div>
          <p className="muted">Word highlighting is unavailable for this chant; plain player shown.</p>
          <audio controls preload="none" src={audioUrl(audio.job_id)} style={{ width: '100%', maxWidth: 480 }} />
        </>
      )}
      {s.kind === 'error' && <p className="danger" role="alert">Could not load the chant: {s.msg}</p>}
      {(s.kind === 'idle' || s.kind === 'loading') && <p className="muted">Loading chant…</p>}
    </div>
  )
}
