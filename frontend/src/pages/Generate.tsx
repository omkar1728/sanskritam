import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, bundleUrl, FALLBACK_EXECUTORS } from '../api'
import EpicBatch from './generate/EpicBatch'
import './generate/epicBatch.css'
import type { ExecutorInfo, Job, Meter, MeterSuggestion, Verse, Voice } from '../types'

const FINAL = ['done', 'failed', 'cancelled']

export default function Generate() {
  const [mode, setMode] = useState<'verse' | 'epic'>('verse')
  const [params] = useSearchParams()
  const [verses, setVerses] = useState<Verse[]>([])
  const [meters, setMeters] = useState<Meter[]>([])
  const [voices, setVoices] = useState<Voice[]>([])
  const [verseId, setVerseId] = useState(params.get('verse') ?? '')
  const [meterId, setMeterId] = useState('')
  const [voiceId, setVoiceId] = useState('')
  const [executor, setExecutor] = useState('')
  const [device, setDevice] = useState('')
  const [steps, setSteps] = useState('16')
  const [seed, setSeed] = useState('')
  const [sugg, setSugg] = useState<MeterSuggestion[]>([])
  const [err, setErr] = useState('')
  const [job, setJob] = useState<Job | null>(null)
  const [busy, setBusy] = useState(false)
  const [executors, setExecutors] = useState<ExecutorInfo[]>(FALLBACK_EXECUTORS)
  const [up, setUp] = useState<{ state: 'idle' | 'busy' | 'ok' | 'err'; text: string }>({ state: 'idle', text: '' })
  const fileRef = useRef<HTMLInputElement>(null)
  const logRef = useRef<HTMLPreElement>(null)

  useEffect(() => {
    Promise.all([api.verses(), api.meters(), api.voices(), api.getSettings()]).then(([vs, ms, vc, st]) => {
      setVerses(vs); setMeters(ms); setVoices(vc)
      setVoiceId(v => v || vc[0]?.id || '')
      setExecutor(st.executor); setDevice(st.device); setSteps(String(st.steps))
      setVerseId(v => v || vs[0]?.id || '')
    }).catch(e => setErr((e as Error).message))
  }, [])

  useEffect(() => { api.executors().then(setExecutors) }, [])

  useEffect(() => {
    const v = verses.find(x => x.id === verseId)
    if (!v) return
    let stale = false
    api.meterSuggest(v.text).then(s => {
      if (stale) return
      setSugg(s)
      if (s[0]) setMeterId(s[0].meter_id)
    }).catch(() => { if (!stale) setSugg([]) })
    return () => { stale = true }
  }, [verseId, verses])

  const jobId = job?.id
  const final = job ? FINAL.includes(job.status) : true
  useEffect(() => {
    if (jobId === undefined || final) return
    const t = setInterval(() => {
      api.job(jobId).then(setJob).catch(e => setErr((e as Error).message))
    }, 2000)
    return () => clearInterval(t)
  }, [jobId, final])

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [job?.log])

  const submit = async () => {
    setErr(''); setBusy(true)
    try {
      const { id } = await api.createJob({
        verse_id: verseId, meter_id: meterId, voice_id: voiceId || undefined,
        executor: executor || undefined, device: device || undefined,
        steps: Number(steps) || undefined, seed: seed.trim() ? Number(seed) : undefined,
      })
      setJob(await api.job(id))
    } catch (e) { setErr((e as Error).message) }
    setBusy(false)
  }

  const cancel = async () => {
    if (!job) return
    try { await api.cancelJob(job.id) } catch (e) { setErr((e as Error).message) }
  }

  const sorted = [...meters].sort((a, b) => Number(!!a.is_prose) - Number(!!b.is_prose))
  const top = sugg[0]
  const upload = async () => {
    const f = fileRef.current?.files?.[0]
    if (!job || !f) { setUp({ state: 'err', text: 'Choose a result zip first.' }); return }
    setUp({ state: 'busy', text: `Uploading ${f.name} (${(f.size / 1048576).toFixed(1)} MB)…` })
    try {
      await api.uploadResult(job.id, f)
      setUp({ state: 'ok', text: 'Result uploaded. Processing continues.' })
      setJob(await api.job(job.id))
    } catch (e) { setUp({ state: 'err', text: (e as Error).message }) }
  }
  const running = !!job && !final

  return (
    <div>
      <h1>Generate</h1>
      <div className="gen-tabs" role="group" aria-label="Generate mode">
        <button className="btn secondary" aria-pressed={mode === 'verse'} onClick={() => setMode('verse')}>Library verse</button>
        <button className="btn secondary" aria-pressed={mode === 'epic'} onClick={() => setMode('epic')}>Epic verses</button>
      </div>
      {mode === 'epic' && <EpicBatch />}
      {mode === 'verse' && <>
      <p className="muted">A local render takes several minutes. Keep this page open to follow progress.</p>
      {err && <p className="danger" role="alert">{err}</p>}
      <div className="card">
        <label>Verse
          <select value={verseId} onChange={e => setVerseId(e.target.value)} disabled={running}>
            {verses.map(v => <option key={v.id} value={v.id}>{v.title || v.id}</option>)}
          </select>
        </label>
        <label>Meter {top && meterId === top.meter_id && <em>(suggested)</em>}
          <select value={meterId} onChange={e => setMeterId(e.target.value)} disabled={running}>
            {sorted.map(m => (
              <option key={m.id} value={m.id}>
                {m.name}{m.is_prose ? ' (prose)' : ''}{top?.meter_id === m.id ? ' — suggested' : ''}
              </option>
            ))}
          </select>
        </label>
        {top && <p className="muted" style={{ marginTop: '-.5rem' }}>Suggestion: {top.meter}. {top.reason}</p>}
        <label>Voice
          <select value={voiceId} onChange={e => setVoiceId(e.target.value)} disabled={running}>
            {voices.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}
          </select>
        </label>
        {voices.find(v => v.id === voiceId)?.notice && <p className="muted">{voices.find(v => v.id === voiceId)?.notice}</p>}
        <details style={{ marginBottom: '1rem' }}>
          <summary>Advanced</summary>
          <div style={{ marginTop: '.8rem' }}>
            <label>Executor
              <select value={executor} onChange={e => setExecutor(e.target.value)}>
                {executors.map(x => <option key={x.name} value={x.name}>{x.label || x.name}</option>)}
              </select>
            </label>
            {executors.find(x => x.name === executor)?.description && (
              <p className="muted" style={{ marginTop: '-.5rem' }}>{executors.find(x => x.name === executor)?.description}</p>
            )}
            <label>Device
              <select value={device} onChange={e => setDevice(e.target.value)}>
                <option>cpu</option><option>cuda</option>
              </select>
            </label>
            {executor && executor !== 'local' && device === 'cpu' && (
              <p className="danger" style={{ marginTop: '-.5rem' }}>Use cuda for Colab; cpu will be very slow.</p>
            )}
            <label>Steps<input type="number" min={1} max={64} value={steps} onChange={e => setSteps(e.target.value)} /></label>
            <label>Seed (blank = default)<input type="number" value={seed} onChange={e => setSeed(e.target.value)} /></label>
          </div>
        </details>
        <button className="btn" onClick={submit} disabled={busy || running || !verseId || !meterId}>
          {busy ? 'Submitting…' : 'Generate'}
        </button>
      </div>

      {job && (
        <div className="card">
          <h2>Job #{job.id}: <span className={job.status === 'done' ? 'success' : job.status === 'failed' ? 'danger' : ''}>{job.status}</span></h2>
          <progress value={job.progress} max={1} style={{ width: '100%' }} />
          <div className="muted">{Math.round(job.progress * 100)}%</div>
          <pre ref={logRef} style={{ fontFamily: 'monospace', fontSize: '.8rem', background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 6, padding: '.6rem', height: 200, overflow: 'auto', whiteSpace: 'pre-wrap' }}>{job.log || ''}</pre>
          {job.status === 'running' && job.executor === 'colab_manual' && (
            <div className="card" style={{ background: 'var(--bg)' }}>
              <strong>Manual Colab steps</strong>
              <ol>
                <li><a href={bundleUrl(job.id)} download>Download bundle</a></li>
                <li>Run it in the Colab notebook (see COLAB.md).</li>
                <li>Upload the resulting zip here.</li>
              </ol>
              <input type="file" accept=".zip,application/zip" ref={fileRef} />{' '}
              <button className="btn" onClick={upload} disabled={up.state === 'busy'}>Upload result zip</button>
              {up.text && <p className={up.state === 'ok' ? 'success' : up.state === 'err' ? 'danger' : 'muted'}>{up.text}</p>}
              <p className="muted">The queue is blocked until the result is uploaded or the job is cancelled.</p>
            </div>
          )}
          {job.status === 'running' && job.executor === 'colab_drive' && (
            <p className="muted">Waiting for the Colab notebook; make sure it is running.</p>
          )}
          {job.status === 'failed' && <p className="danger">{job.error || 'Job failed.'}</p>}
          {running && <button className="btn secondary" onClick={cancel}>Cancel</button>}
          {job.status === 'done' && <Link to={`/learn/${job.id}`}><button className="btn" type="button">Open in Learn</button></Link>}
        </div>
      )}
      </>}
    </div>
  )
}
