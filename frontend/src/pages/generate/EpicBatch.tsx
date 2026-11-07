import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, batchInputUrl } from '../../api'
import type {
  BatchDetail, BatchId, BatchPreview, BatchSummary, BatchUploadResult, BatchImportResult, KandaSummary, Meter, SargaSummary, Voice,
} from '../../types'
import type { EpicVerse } from '../../types'
import {
  buildBatchBody, countsTotal, importSummary, isBatchActive, meterBreakdown, needsConfirmAll, scopeLabel, statusCounts, statusSummary,
} from './epicBatchHelpers'
import AlignDrop from './AlignDrop'
import './epicBatch.css'

const msg = (e: unknown) => (e instanceof Error ? e.message : String(e))
const verseLabel = (v: EpicVerse) => {
  const c = v.refs?.critical_smith
  const n = c?.verse ?? v.seq_in_sarga
  return `${v.seq_in_sarga ?? '?'}${n !== undefined && n !== v.seq_in_sarga ? ` (v${n})` : ''} — ${v.id}`
}

export default function EpicBatch() {
  const [kandas, setKandas] = useState<KandaSummary[]>([])
  const [sargas, setSargas] = useState<SargaSummary[]>([])
  const [verses, setVerses] = useState<EpicVerse[]>([])
  const [meters, setMeters] = useState<Meter[]>([])
  const [voices, setVoices] = useState<Voice[]>([])
  const [kanda, setKanda] = useState('')
  const [sarga, setSarga] = useState('')
  const [verseId, setVerseId] = useState('')
  const [voiceId, setVoiceId] = useState('')
  const [steps, setSteps] = useState('16')
  const [seed, setSeed] = useState('')
  const [meterId, setMeterId] = useState('')
  const [err, setErr] = useState('')
  const [preview, setPreview] = useState<BatchPreview | null>(null)
  const [pvBusy, setPvBusy] = useState(false)
  const [pvErr, setPvErr] = useState('')
  const [confirming, setConfirming] = useState(false)
  const [ack, setAck] = useState(false)
  const [creating, setCreating] = useState(false)
  const [batchId, setBatchId] = useState<BatchId | null>(null)
  const [batches, setBatches] = useState<BatchSummary[]>([])

  const loadBatches = () => api.batches().then(setBatches).catch(e => setErr(msg(e)))
  useEffect(() => {
    Promise.all([api.ramayanaKandas(), api.meters(), api.voices(), api.getSettings()]).then(([ks, ms, vc, st]) => {
      setKandas(ks); setMeters(ms); setVoices(vc)
      setVoiceId(v => v || vc[0]?.id || ''); setSteps(String(st.steps))
    }).catch(e => setErr(msg(e)))
    loadBatches()
  }, [])

  useEffect(() => {
    if (!kanda) return
    let stale = false
    api.ramayanaSargas(Number(kanda)).then(s => { if (!stale) setSargas(s) }).catch(e => { if (!stale) setErr(msg(e)) })
    return () => { stale = true }
  }, [kanda])

  useEffect(() => {
    if (!kanda || !sarga) return
    let stale = false
    api.ramayanaSarga(Number(kanda), Number(sarga)).then(d => { if (!stale) setVerses(d.verses) }).catch(e => { if (!stale) setErr(msg(e)) })
    return () => { stale = true }
  }, [kanda, sarga])

  const body = useMemo(
    () => buildBatchBody({ kanda, sarga, verseId, voiceId, steps, seed, meterId }),
    [kanda, sarga, verseId, voiceId, steps, seed, meterId],
  )
  const bodyKey = JSON.stringify(body)
  useEffect(() => {
    if (!body.voice_id) return
    let stale = false
    const t = setTimeout(() => {
      setPvBusy(true); setPvErr('')
      api.batchPreview(body).then(p => { if (!stale) { setPreview(p); setPvBusy(false) } })
        .catch(e => { if (!stale) { setPreview(null); setPvErr(msg(e)); setPvBusy(false) } })
    }, 400)
    return () => { stale = true; clearTimeout(t) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bodyKey])

  const kandaName = kandas.find(k => String(k.number) === kanda)?.name_en
  const whole = needsConfirmAll(body)
  const sorted = [...meters].sort((a, b) => Number(!!a.is_prose) - Number(!!b.is_prose))

  const create = async () => {
    setErr(''); setCreating(true)
    try {
      const r = await api.createBatch({ ...body, confirm: true, ...(whole ? { confirm_all: true } : {}) })
      setConfirming(false); setAck(false); setBatchId(r.batch_id); loadBatches()
    } catch (e) { setErr(msg(e)) }
    setCreating(false)
  }

  return (
    <div>
      <AlignDrop />
      {err && <p className="danger" role="alert">{err}</p>}
      <div className="card">
        <label>Epic
          <select value="ramayana" disabled><option value="ramayana">Ramayana</option></select>
        </label>
        <label>Kāṇḍa
          <select value={kanda} onChange={e => { setKanda(e.target.value); setSargas([]); setSarga(''); setVerses([]); setVerseId('') }}>
            <option value="">All kāṇḍas</option>
            {kandas.map(k => <option key={k.number} value={k.number}>{k.number}. {k.name_en || k.name_sa} ({k.verse_count})</option>)}
          </select>
        </label>
        <label>Sarga
          <select value={sarga} onChange={e => { setSarga(e.target.value); setVerses([]); setVerseId('') }} disabled={!kanda}>
            <option value="">All sargas in this kāṇḍa</option>
            {sargas.map(s => <option key={s.sarga} value={s.sarga}>{s.sarga}. {s.title_en || s.title_hi || ''} ({s.verse_count})</option>)}
          </select>
        </label>
        <label>Verse
          <select value={verseId} onChange={e => setVerseId(e.target.value)} disabled={!sarga}>
            <option value="">All verses in this sarga</option>
            {verses.map(v => <option key={v.id} value={v.id}>{verseLabel(v)}</option>)}
          </select>
        </label>
        <label>Voice
          <select value={voiceId} onChange={e => setVoiceId(e.target.value)}>
            {voices.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}
          </select>
        </label>
        <div className="eb-row">
          <label>Steps<input type="number" min={1} max={64} value={steps} onChange={e => setSteps(e.target.value)} /></label>
          <label>Seed (blank = default)<input type="number" value={seed} onChange={e => setSeed(e.target.value)} /></label>
        </div>
        <label>Meter for the whole sarga
          <select value={meterId} onChange={e => setMeterId(e.target.value)}>
            <option value="">Auto-suggest per verse</option>
            {sorted.map(m => <option key={m.id} value={m.id}>{m.name}{m.is_prose ? ' (prose)' : ''}</option>)}
          </select>
        </label>

        <div className="eb-preview" aria-live="polite">
          <strong>{scopeLabel(body, kandaName)}</strong>
          {pvErr && <p className="danger">{pvErr}</p>}
          {preview && (
            <div className={pvBusy ? 'eb-stale' : ''}>
              <dl className="eb-counts">
                <div><dt>Total</dt><dd>{preview.total}</dd></div>
                <div><dt>To generate</dt><dd>{preview.to_generate}</dd></div>
                <div><dt>Already done (skipped)</dt><dd>{preview.skipped}</dd></div>
                <div><dt>Unavailable</dt><dd>{preview.unavailable}</dd></div>
              </dl>
              {preview.meters.length > 0 && <p className="muted">Meters: {meterBreakdown(preview.meters)}</p>}
            </div>
          )}
          {!preview && !pvErr && <p className="muted">{pvBusy ? 'Counting…' : 'Choose a voice to preview.'}</p>}
        </div>

        <button className="btn" disabled={!preview || pvBusy || preview.to_generate === 0 || !voiceId}
          onClick={() => { setAck(false); setConfirming(true) }}>Create batch</button>
        {preview && preview.to_generate === 0 && !pvBusy && <span className="muted"> Nothing to generate.</span>}
      </div>

      {confirming && preview && (
        <div className="eb-modal" role="dialog" aria-modal="true" aria-label="Confirm batch">
          <div className="card eb-dialog">
            <h2>Create batch?</h2>
            <p>{scopeLabel(body, kandaName)}</p>
            <p><strong>{preview.to_generate}</strong> verses will be queued for Colab ({preview.skipped} already done and skipped, {preview.unavailable} unavailable).</p>
            {whole && (
              <label className="eb-ack">
                <input type="checkbox" checked={ack} onChange={e => setAck(e.target.checked)} />{' '}
                I understand this queues the whole Ramayana ({preview.to_generate} verses).
              </label>
            )}
            <button className="btn" onClick={create} disabled={creating || (whole && !ack)}>{creating ? 'Creating…' : 'Confirm'}</button>{' '}
            <button className="btn secondary" onClick={() => setConfirming(false)} disabled={creating}>Cancel</button>
          </div>
        </div>
      )}

      {batchId !== null && <BatchPanel key={String(batchId)} id={batchId} onChange={loadBatches} />}

      <div className="card">
        <h2>Previous batches</h2>
        {batches.length === 0 && <p className="muted">None yet.</p>}
        <ul className="eb-list">
          {batches.map(b => (
            <li key={String(b.id)}>
              <button className="btn secondary" onClick={() => setBatchId(b.id)} aria-pressed={batchId === b.id}>
                Batch {String(b.id)}
              </button>{' '}
              <span className="muted">{b.created_at} · {countsTotal(b.counts ?? {})} jobs · {statusSummary(b.counts ?? {})}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

function BatchPanel({ id, onChange }: { id: BatchId; onChange: () => void }) {
  const [d, setD] = useState<BatchDetail | null>(null)
  const [err, setErr] = useState('')
  const [pct, setPct] = useState<number | null>(null)
  const [res, setRes] = useState<BatchUploadResult | null>(null)
  const [upErr, setUpErr] = useState('')
  const [imp, setImp] = useState<BatchImportResult | null>(null)
  const [impErr, setImpErr] = useState('')
  const [impBusy, setImpBusy] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const [tick, setTick] = useState(0)

  const active = d ? isBatchActive(d.jobs) : true
  useEffect(() => {
    let stale = false
    api.batch(id).then(x => { if (!stale) { setD(x); setErr('') } }).catch(e => { if (!stale) setErr(msg(e)) })
    return () => { stale = true }
  }, [id, tick])
  useEffect(() => {
    if (!active) { onChange(); return }
    const t = setInterval(() => setTick(n => n + 1), 3000)
    return () => clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, id])

  const importDrive = async () => {
    setImpErr(''); setImp(null); setImpBusy(true)
    try {
      setImp(await api.importBatchDrive(id))
      setTick(n => n + 1)
    } catch (e) { setImpErr(msg(e)) }
    setImpBusy(false)
  }

  const upload = async () => {
    const f = fileRef.current?.files?.[0]
    if (!f) { setUpErr('Choose results.zip first.'); return }
    setUpErr(''); setRes(null); setPct(0)
    try {
      setRes(await api.uploadBatchResult(id, f, setPct))
      setTick(n => n + 1)
    } catch (e) { setUpErr(msg(e)) }
    setPct(null)
  }

  return (
    <div className="card">
      <h2>Batch {String(id)}</h2>
      {err && <p className="danger" role="alert">{err}</p>}
      {d && <p className="muted">{d.jobs.length} jobs: {statusSummary(statusCounts(d.jobs))}</p>}
      <ol className="eb-steps">
        <li><a className="btn" href={batchInputUrl(id)} download="batch.zip">Download batch.zip</a></li>
        <li>Run the Colab notebook (<code>notebooks/colab_batch.ipynb</code>): one cell, pick <code>batch.zip</code> when asked. It renders every verse on the GPU and saves the results into your Google Drive under <code>batch_results/</code>. It does not download anything automatically.</li>
        <li>
          <div>
            <strong>Option A:</strong>{' '}
            <button className="btn" onClick={importDrive} disabled={impBusy}>{impBusy ? 'Importing…' : 'Import from Drive folder'}</button>
            <p className="muted">Works when your Google Drive folder is mounted on this PC (Settings &gt; Colab Drive folder). Results are read from batch_results/ramayana/&lt;kanda&gt;/sarga_NNN/&lt;verse&gt; in it.</p>
            {impErr && <p className="danger" role="alert">{impErr} <Link to="/settings">Set the Drive folder in Settings</Link></p>}
            {imp && (() => { const s = importSummary(imp); return (
              <>
                <p className={s.isError ? 'danger' : 'success'}>{s.text}</p>
                {s.note && <p className="muted">{s.note}</p>}
              </>
            ) })()}
          </div>
          <div>
          <strong>Option B:</strong>{' '}
          <input type="file" accept=".zip,application/zip" ref={fileRef} aria-label="Upload results.zip" />{' '}
          <button className="btn" onClick={upload} disabled={pct !== null}>Upload results.zip</button>
          {pct !== null && <div><progress value={pct} max={1} style={{ width: '100%' }} /> <span className="muted">{Math.round(pct * 100)}%</span></div>}
          {upErr && <p className="danger" role="alert">{upErr}</p>}
          {res && <p className={res.failed ? 'danger' : 'success'}>Accepted {res.accepted}, failed {res.failed}, ignored {res.ignored}.</p>}
          </div>
        </li>
      </ol>
      {!d && !err && <p className="muted">Loading…</p>}
      {d && (
        <div className="eb-table-wrap">
          <table className="eb-table">
            <thead><tr><th>Job</th><th>Verse</th><th>Status</th><th>Progress</th></tr></thead>
            <tbody>
              {d.jobs.map(j => (
                <tr key={j.id}>
                  <td>{j.status === 'done' ? <Link to={`/learn/${j.id}`}>#{j.id}</Link> : `#${j.id}`}</td>
                  <td>{j.verse_id}</td>
                  <td className={j.status === 'done' ? 'success' : j.status === 'failed' ? 'danger' : ''}>
                    {j.status.replace('_', ' ')}{j.error ? ` — ${j.error}` : ''}
                  </td>
                  <td>{Math.round(j.progress * 100)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
