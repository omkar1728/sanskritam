import { useEffect, useState } from 'react'
import { api, FALLBACK_EXECUTORS } from '../api'
import type { ExecutorInfo } from '../types'

export default function Settings() {
  const [executor, setExecutor] = useState('local')
  const [device, setDevice] = useState('cpu')
  const [steps, setSteps] = useState(16)
  const [executors, setExecutors] = useState<ExecutorInfo[]>(FALLBACK_EXECUTORS)
  const [driveDir, setDriveDir] = useState('')
  const [timeoutS, setTimeoutS] = useState(1800)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.getSettings().then(s => {
      setExecutor(s.executor); setDevice(s.device); setSteps(Number(s.steps))
      setDriveDir(s.colab_drive_dir ?? ''); setTimeoutS(Number(s.colab_timeout_s) || 3600)
    }).catch(e => setMsg({ ok: false, text: String(e.message) }))
  }, [])
  useEffect(() => { api.executors().then(setExecutors) }, [])

  async function run(fn: () => Promise<string>) {
    setBusy(true); setMsg(null)
    try { setMsg({ ok: true, text: await fn() }) }
    catch (e) { setMsg({ ok: false, text: (e as Error).message }) }
    finally { setBusy(false) }
  }
  const save = () => run(async () => { await api.putSettings({
    executor, device, steps,
    ...(executor === 'colab_drive' ? { colab_drive_dir: driveDir, colab_timeout_s: timeoutS } : {}),
  }); return 'Settings saved.' })
  const test = () => run(async () => {
    const h = await api.executorHealth(executor)
    const detail = typeof h.detail === 'string' ? h.detail : JSON.stringify(h)
    if (h.ok === false) throw new Error('Connection failed: ' + detail)
    return 'Connection OK: ' + detail
  })

  return (
    <>
      <h1>Settings</h1>
      <div className="card">
        <label>Default executor
          <select value={executor} onChange={e => setExecutor(e.target.value)}>
            {executors.map(x => <option key={x.name} value={x.name}>{x.label || x.name}</option>)}
          </select>
        </label>
        {executors.find(x => x.name === executor)?.description && (
          <p className="muted" style={{ marginTop: '-.5rem' }}>{executors.find(x => x.name === executor)?.description}</p>
        )}
        {executor === 'colab_drive' && (
          <>
            <label>Drive folder (locally mounted path)
              <input value={driveDir} onChange={e => setDriveDir(e.target.value)} />
            </label>
            <label>Colab timeout (seconds)
              <input type="number" min={1} value={timeoutS} onChange={e => setTimeoutS(Number(e.target.value))} />
            </label>
          </>
        )}
        <p className="muted">Setup steps are in COLAB.md.</p>
        <label>Device
          <select value={device} onChange={e => setDevice(e.target.value)}>
            <option>cpu</option><option>cuda</option>
          </select>
        </label>
        <p className="muted" style={{ marginTop: '-.5rem' }}>Use cuda for Colab.</p>
        <label>Steps (1-64)
          <input type="number" min={1} max={64} value={steps} onChange={e => setSteps(Number(e.target.value))} />
        </label>
        <button className="btn" disabled={busy} onClick={save}>Save</button>{' '}
        <button className="btn secondary" disabled={busy} onClick={test}>Test connection</button>
        {msg && <p className={msg.ok ? 'success' : 'danger'}>{msg.text}</p>}
      </div>
      <p className="muted">Notice: the voice is synthetic (AI-generated), not a human reciter.</p>
    </>
  )
}
