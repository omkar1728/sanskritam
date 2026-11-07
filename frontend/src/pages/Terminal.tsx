import { useEffect, useRef, useState } from 'react'
import { Terminal as XTerm } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { STANDALONE } from '../api'
import './terminal.css'

const KEY = 'ec2-terminal'
type Saved = { host: string; username: string; keyPath: string }

function load(): Saved {
  const d = { host: '', username: 'ubuntu', keyPath: '' }
  try {
    const s = JSON.parse(localStorage.getItem(KEY) || '{}')
    return { host: s.host || d.host, username: s.username || d.username, keyPath: s.keyPath || d.keyPath }
  } catch { return d }
}
function save(s: Saved) {
  try { localStorage.setItem(KEY, JSON.stringify(s)) } catch { /* ignore */ }
}

export default function Terminal() {
  const [form, setForm] = useState<Saved>(load)
  const [active, setActive] = useState(false)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const boxRef = useRef<HTMLDivElement>(null)
  const cleanup = useRef<(() => void) | null>(null)

  useEffect(() => () => { cleanup.current?.() }, [])

  function disconnect() {
    cleanup.current?.()
    cleanup.current = null
    setActive(false)
  }

  function connect(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    save(form)
    setStatus('connecting')
    setActive(true)
    // wait for the container to render
    requestAnimationFrame(() => start())
  }

  function start() {
    const box = boxRef.current
    if (!box) return
    const term = new XTerm({ cursorBlink: true, fontSize: 14, fontFamily: 'monospace',
      theme: { background: '#0d0e14', foreground: '#e8e8ef' } })
    const fit = new FitAddon()
    term.loadAddon(fit)
    term.open(box)
    try { fit.fit() } catch { /* ignore */ }
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${location.host}/api/ssh/terminal`)
    ws.binaryType = 'arraybuffer'
    let failed = false
    let disposed = false
    const send = (o: unknown) => { if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(o)) }
    ws.onopen = () => send({ type: 'connect', host: form.host.trim(), username: form.username.trim(),
      key_path: form.keyPath.trim(), cols: term.cols, rows: term.rows })
    ws.onmessage = (ev) => {
      if (typeof ev.data !== 'string') { term.write(new Uint8Array(ev.data as ArrayBuffer)); return }
      try {
        const m = JSON.parse(ev.data)
        if (m.type === 'status') {
          setStatus(m.state)
          if (m.state === 'connected') { term.focus(); send({ type: 'resize', cols: term.cols, rows: term.rows }) }
        } else if (m.type === 'error') {
          failed = true
          setError(String(m.message))
          setStatus('error')
        }
      } catch { /* ignore */ }
    }
    ws.onerror = () => { failed = true; setError('WebSocket connection failed'); setStatus('error') }
    ws.onclose = () => {
      if (disposed) return
      if (failed) { cleanup.current?.(); cleanup.current = null; setActive(false) }
      else setStatus('closed')
    }
    const d = term.onData((data) => send({ type: 'input', data }))
    const doFit = () => {
      try { fit.fit() } catch { return }
      send({ type: 'resize', cols: term.cols, rows: term.rows })
    }
    const ro = new ResizeObserver(doFit)
    ro.observe(box)
    cleanup.current = () => {
      disposed = true
      ro.disconnect(); d.dispose(); ws.close(); term.dispose()
    }
  }

  if (STANDALONE) {
    return <div className="card"><h2>EC2 Terminal</h2>
      <p className="muted">Not available in the offline app: needs the desktop backend.</p></div>
  }

  const set = (k: keyof Saved) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value })

  return (
    <div>
      <h2>EC2 Terminal</h2>
      {!active && (
        <form className="card" onSubmit={connect}>
          <label>IP address / host
            <input value={form.host} onChange={set('host')} placeholder="203.0.113.10" required />
          </label>
          <label>Username
            <input value={form.username} onChange={set('username')} required />
            <span className="muted">ubuntu for Ubuntu AMIs; ec2-user for Amazon Linux.</span>
          </label>
          <label>Key file path
            <input value={form.keyPath} onChange={set('keyPath')} placeholder="~/.ssh/my-key.pem" required />
            <span className="muted">A path on the machine running the backend, not uploaded from the browser.</span>
          </label>
          {error && <p className="danger">{error}</p>}
          <button className="btn" type="submit">Connect</button>
        </form>
      )}
      {active && (
        <>
          <div className="term-bar">
            <span className={status === 'connected' ? 'success' : status === 'error' ? 'danger' : 'muted'}>
              Status: {status}{error ? ` (${error})` : ''}
            </span>
            <button className="btn secondary" onClick={disconnect}>Disconnect</button>
          </div>
          <div className="term-box" ref={boxRef} />
        </>
      )}
    </div>
  )
}
