import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import type { Job, Verse } from '../types'
import { meaningsState, MEANINGS_STATE_LABEL } from '../player/meanings'

const fmtDur = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`

function AddVerse({ onAdded }: { onAdded: () => void }) {
  const [f, setF] = useState({ id: '', title: '', text: '', work: '', reference: '', edition: '', url: '', notes: '' })
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value })

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setErr(''); setBusy(true)
    try {
      await api.addVerse({
        id: f.id.trim(), title: f.title.trim() || null,
        text: f.text.split('\n').map(s => s.trim()).filter(Boolean),
        source: { work: f.work.trim(), reference: f.reference.trim(), edition: f.edition.trim() || null, url: f.url.trim() || null },
        notes: f.notes.trim() || null,
      })
      setF({ id: '', title: '', text: '', work: '', reference: '', edition: '', url: '', notes: '' })
      onAdded()
    } catch (x) { setErr((x as Error).message) }
    setBusy(false)
  }

  return (
    <details className="card">
      <summary>Add verse</summary>
      <form onSubmit={submit} style={{ marginTop: '1rem' }}>
        <label>ID *<input required value={f.id} onChange={set('id')} /></label>
        <label>Title<input value={f.title} onChange={set('title')} /></label>
        <label>Text * (one line per line)
          <textarea required rows={4} value={f.text} onChange={set('text')} className="devanagari" style={{ maxWidth: 520, fontSize: '1.2rem' }} />
        </label>
        <label>Source work *<input required value={f.work} onChange={set('work')} /></label>
        <label>Reference *<input required value={f.reference} onChange={set('reference')} /></label>
        <label>Edition<input value={f.edition} onChange={set('edition')} /></label>
        <label>URL<input type="url" value={f.url} onChange={set('url')} /></label>
        <label>Notes<textarea rows={2} value={f.notes} onChange={set('notes')} /></label>
        {err && <p className="danger" role="alert">{err}</p>}
        <button className="btn" disabled={busy}>{busy ? 'Adding…' : 'Add verse'}</button>
      </form>
    </details>
  )
}

export default function Library() {
  const [verses, setVerses] = useState<Verse[] | null>(null)
  const [jobs, setJobs] = useState<Job[]>([])
  const [err, setErr] = useState('')

  const load = useCallback(() => {
    api.verses().then(setVerses).catch(e => setErr((e as Error).message))
    api.jobs().then(setJobs).catch(e => setErr((e as Error).message))
  }, [])
  useEffect(() => { load() }, [load])

  return (
    <div>
      <h1>Library</h1>
      {err && <p className="danger" role="alert">{err}</p>}
      {verses === null && !err && <p className="muted">Loading…</p>}
      {verses?.length === 0 && <div className="card muted">No verses yet. Add one below.</div>}
      {verses?.map(v => (
        <div className="card" key={v.id}>
          <h2>{v.title || v.id} <span className="muted" style={{ fontSize: '.8rem' }}>{v.id}</span></h2>
          <div className="muted" style={{ fontSize: '.8rem' }} data-testid="meanings-state">Meanings: {MEANINGS_STATE_LABEL[meaningsState(v.meanings)]}</div>
          <div>{v.text.map((l, i) => <div key={i} className="devanagari">{l}</div>)}</div>
          <div className="muted" style={{ margin: '.6rem 0' }}>
            <strong>{v.source.work}</strong>, {v.source.reference}
            {v.source.edition && <> · {v.source.edition}</>}
            {v.source.url && <> · <a href={v.source.url} target="_blank" rel="noopener noreferrer">link</a></>}
            {v.notes && <div>{v.notes}</div>}
          </div>
          {v.audio.length > 0 ? (
            <ul>
              {v.audio.map(a => (
                <li key={a.job_id}>
                  <Link to={`/learn/${a.job_id}`}>{a.meter_id} · {a.voice_id} · {a.steps} steps · {fmtDur(a.duration)}</Link>
                </li>
              ))}
            </ul>
          ) : <p className="muted">No audio yet.</p>}
          <Link to={`/generate?verse=${encodeURIComponent(v.id)}`}><button className="btn" type="button">Generate audio</button></Link>
        </div>
      ))}
      <AddVerse onAdded={load} />
      <h2>Recent jobs</h2>
      {jobs.length === 0 ? <p className="muted">No jobs yet.</p> : (
        <div className="card">
          {jobs.slice(0, 15).map(j => (
            <div key={j.id} style={{ marginBottom: '.4rem' }}>
              #{j.id} {j.verse_id} · {j.meter_id} ·{' '}
              <span className={j.status === 'done' ? 'success' : j.status === 'failed' ? 'danger' : 'muted'}>{j.status}</span>
              {(j.status === 'running' || j.status === 'aligning') && <> {Math.round(j.progress * 100)}%</>}
              {j.status === 'done' && <> · <Link to={`/learn/${j.id}`}>Open</Link></>}
              {j.status === 'failed' && j.error && <span className="danger"> · {j.error.slice(0, 120)}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
