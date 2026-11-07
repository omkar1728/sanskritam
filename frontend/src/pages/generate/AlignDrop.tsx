import { useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import type { AlignUploadResult, BatchJob } from '../../types'
import { isBatchActive, statusCounts, statusSummary } from './epicBatchHelpers'

const msg = (e: unknown) => (e instanceof Error ? e.message : String(e))

/** Drop a results zip anywhere in this box: the batch is detected from the zip and every chant is aligned automatically. */
export default function AlignDrop() {
  const [over, setOver] = useState(false)
  const [pct, setPct] = useState<number | null>(null)
  const [res, setRes] = useState<AlignUploadResult | null>(null)
  const [err, setErr] = useState('')
  const [jobs, setJobs] = useState<BatchJob[]>([])
  const [tick, setTick] = useState(0)
  const fileRef = useRef<HTMLInputElement>(null)

  const upload = async (f: File | undefined) => {
    if (!f) return
    if (!/\.zip$/i.test(f.name)) { setErr('Please choose a .zip file.'); return }
    setErr(''); setRes(null); setJobs([]); setPct(0)
    try { setRes(await api.uploadAlignZip(f, setPct)); setTick(n => n + 1) } catch (e) { setErr(msg(e)) }
    setPct(null)
    if (fileRef.current) fileRef.current.value = ''
  }

  const active = !!res && (jobs.length === 0 || isBatchActive(jobs))
  useEffect(() => {
    if (!res) return
    let stale = false
    Promise.all(res.batches.map(b => api.batch(b))).then(ds => {
      if (stale) return
      const mine = new Set(res.job_ids)
      setJobs(ds.flatMap(d => d.jobs).filter(j => mine.has(j.id)))
    }).catch(e => { if (!stale) setErr(msg(e)) })
    return () => { stale = true }
  }, [res, tick])
  useEffect(() => {
    if (!active) return
    const t = setInterval(() => setTick(n => n + 1), 3000)
    return () => clearInterval(t)
  }, [active])

  const counts = statusCounts(jobs)
  const done = (counts.done ?? 0) + (counts.failed ?? 0)
  return (
    <div className="card">
      <h2>Align results zip</h2>
      <div
        className={`eb-drop${over ? ' over' : ''}`}
        onDragOver={e => { e.preventDefault(); setOver(true) }}
        onDragLeave={() => setOver(false)}
        onDrop={e => { e.preventDefault(); setOver(false); void upload(e.dataTransfer.files[0]) }}
      >
        <p>Drop the Colab <code>results.zip</code> here, or</p>
        <label className="btn">
          Choose zip
          <input type="file" accept=".zip,application/zip" ref={fileRef} hidden aria-label="Upload results zip to align"
            onChange={e => void upload(e.target.files?.[0])} />
        </label>
        <p className="muted">The batch is detected from the zip. Alignment runs automatically, one verse at a time.</p>
      </div>
      {pct !== null && <progress value={pct} max={1} aria-label="Upload progress" />}
      {err && <p className="danger" role="alert">{err}</p>}
      {res && (
        <p className={res.failed ? 'danger' : 'success'} role="status">
          Accepted {res.accepted}, failed {res.failed}{res.ignored ? `, ignored ${res.ignored}` : ''}.
          {jobs.length > 0 && <> Aligned {done} of {jobs.length}{active ? '…' : '.'} ({statusSummary(counts)})</>}
        </p>
      )}
      {res && jobs.length > 0 && <progress value={done} max={jobs.length} aria-label="Alignment progress" />}
    </div>
  )
}
