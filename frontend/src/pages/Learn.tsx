import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, audioUrl } from '../api'
import type { Alignment, Verse, Voice } from '../types'
import { MeaningPlayer, EditMeanings } from '../player/MeaningPanel'

type State =
  | { kind: 'loading' }
  | { kind: 'error'; msg: string }
  | { kind: 'ready'; verse: Verse; alignment: Alignment | null; voice: Voice | null }

export default function Learn() {
  const { jobId } = useParams()
  const id = Number(jobId)
  const [s, setS] = useState<State>({ kind: 'loading' })
  const [rev, setRev] = useState(0)

  useEffect(() => {
    let dead = false
    ;(async () => {
      try {
        const job = await api.job(id)
        const [verse, alignment, voices] = await Promise.all([
          api.verse(job.verse_id),
          api.alignment(id).catch(() => null),
          api.voices().catch(() => [] as Voice[]),
        ])
        if (!dead) setS({ kind: 'ready', verse, alignment, voice: voices.find(v => v.id === job.voice_id) ?? null })
      } catch (e) {
        if (!dead) setS({ kind: 'error', msg: e instanceof Error ? e.message : String(e) })
      }
    })()
    return () => { dead = true }
  }, [id, rev])

  if (!Number.isFinite(id)) return <p className="danger">Invalid job id.</p>
  if (s.kind === 'loading') return <p className="muted">Loading...</p>
  if (s.kind === 'error') return <p className="danger">Could not load: {s.msg}</p>
  const { verse, alignment, voice } = s
  const src = verse.source

  return (
    <div className="player-page">
      <h1>{verse.title ?? verse.id}</h1>
      <div className="notice" style={{ borderLeft: '3px solid var(--accent)', padding: '.4rem .8rem', marginBottom: '1rem', background: 'var(--surface2)' }}>
        Synthetic voice, not a recording of the speaker.{voice?.notice ? ` ${voice.notice}` : ''}
      </div>
      {alignment ? (
        <MeaningPlayer src={audioUrl(id)} alignment={alignment} meanings={verse.meanings} />
      ) : (
        <>
          <div className="notice" style={{ borderLeft: '3px solid var(--danger)', padding: '.4rem .8rem', marginBottom: '1rem', background: 'var(--surface2)' }}>
            Alignment unavailable: word and syllable highlighting is off. Plain audio player shown.
          </div>
          <div className="card">
            {verse.text.map((l, i) => <div key={i} className="devanagari">{l}</div>)}
          </div>
          <div className="card"><audio controls src={audioUrl(id)} style={{ width: '100%' }} /></div>
        </>
      )}
      <EditMeanings key={JSON.stringify(verse.meanings)} verseId={verse.id} lines={verse.text} alignment={alignment}
        meanings={verse.meanings} onSaved={() => setRev(r => r + 1)} />
      <div className="card" aria-label="Source">
        <h3>Source</h3>
        <div><strong>{src.work}</strong>, {src.reference}</div>
        {src.edition && <div className="muted">Edition: {src.edition}</div>}
        {src.url && <div><a href={src.url} target="_blank" rel="noopener noreferrer">View source</a></div>}
        {verse.notes && <p className="muted">{verse.notes}</p>}
      </div>
    </div>
  )
}
