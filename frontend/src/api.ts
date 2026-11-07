import type {
  BatchCreated, BatchDetail, BatchId, BatchPreview, BatchRequest, BatchSummary, BatchUploadResult, BatchImportResult, AlignUploadResult,
  Alignment, CreateJob, EpicSummary, KandaSummary, SargaSummary, SargaDetail, ExecutorHealth, ExecutorInfo, Job, MeaningsUpdate, Meter, MeterSuggestion, NewVerse, Settings, SettingsUpdate, Verse, Voice,
} from './types'

export const STANDALONE = import.meta.env.VITE_STANDALONE === '1'
const OFFLINE_MSG = 'Not available in the offline app: needs the desktop backend'

/** Offline app: map '/api/X' to the bundled static file '/data/X.json'. */
export function staticPath(path: string): string {
  return '/data/' + path.replace(/^\/api\//, '').split('?')[0] + '.json'
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  if (STANDALONE) {
    if (init?.method && init.method !== 'GET') throw new Error(OFFLINE_MSG)
    const r = await fetch(staticPath(path))
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
    return r.json() as Promise<T>
  }
  const headers: Record<string, string> = init?.body ? { 'Content-Type': 'application/json' } : {}
  const r = await fetch(path, { ...init, headers })
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`
    try {
      const d = (await r.json()).detail
      if (d) msg = typeof d === 'string' ? d : JSON.stringify(d)
    } catch { /* non-JSON body */ }
    throw new Error(msg)
  }
  return r.json() as Promise<T>
}
const post = <T>(p: string, b?: unknown) => req<T>(p, { method: 'POST', body: JSON.stringify(b ?? {}) })

export const FALLBACK_EXECUTORS: ExecutorInfo[] = [
  { name: 'local', label: 'Local', description: 'Render on this machine.' },
  { name: 'colab_drive', label: 'Colab (Drive)', description: 'Colab notebook polls a mounted Google Drive folder.' },
  { name: 'colab_manual', label: 'Colab (manual)', description: 'Download a bundle, run it in Colab, upload the result zip.' },
]

export const api = {
  executors: () => req<ExecutorInfo[]>('/api/executors').catch(() => FALLBACK_EXECUTORS),
  uploadResult: async (jobId: number, file: File): Promise<void> => {
    if (STANDALONE) throw new Error(OFFLINE_MSG)
    const r = await fetch(`/api/jobs/${jobId}/result`, {
      method: 'PUT', headers: { 'Content-Type': 'application/zip' }, body: file,
    })
    if (!r.ok) {
      let msg = `${r.status} ${r.statusText}`
      try {
        const d = (await r.json()).detail
        if (d) msg = typeof d === 'string' ? d : JSON.stringify(d)
      } catch { /* non-JSON body */ }
      throw new Error(msg)
    }
  },
  meters: () => req<Meter[]>('/api/meters'),
  voices: () => req<Voice[]>('/api/voices'),
  verses: () => req<Verse[]>('/api/verses'),
  verse: (id: string) => req<Verse>(`/api/verses/${encodeURIComponent(id)}`),
  saveMeanings: (id: string, b: MeaningsUpdate) =>
    req<unknown>(`/api/verses/${encodeURIComponent(id)}/meanings`, { method: 'PUT', body: JSON.stringify(b) }),
  addVerse: (v: NewVerse) => post<{ id: string }>('/api/verses', v),
  meterSuggest: (text: string[] | string) => post<MeterSuggestion>('/api/meter-suggest', { text }).then(s => [s]),
  getSettings: () => req<Settings>('/api/settings'),
  putSettings: (s: SettingsUpdate) => req<Settings>('/api/settings', { method: 'PUT', body: JSON.stringify(s) }),
  executorHealth: (name: string) => req<ExecutorHealth>(`/api/executors/${encodeURIComponent(name)}/health`),
  jobs: () => req<Job[]>('/api/jobs'),
  createJob: (j: CreateJob) => post<{ id: number }>('/api/jobs', j),
  job: (id: number) => req<Job>(`/api/jobs/${id}`),
  cancelJob: (id: number) => post<{ ok: boolean }>(`/api/jobs/${id}/cancel`),
  epics: () => req<EpicSummary[]>('/api/epics'),
  epicKandas: (e: string) => req<KandaSummary[]>(`/api/epics/${e}/kandas`),
  ramayanaKandas: () => req<KandaSummary[]>('/api/epics/ramayana/kandas'),
  epicSargas: (e: string, k: number) => req<SargaSummary[]>(`/api/epics/${e}/kandas/${k}/sargas`),
  epicSarga: (e: string, k: number, s: number) => req<SargaDetail>(`/api/epics/${e}/kandas/${k}/sargas/${s}`),
  ramayanaSargas: (k: number) => req<SargaSummary[]>(`/api/epics/ramayana/kandas/${k}/sargas`),
  ramayanaSarga: (k: number, s: number) => req<SargaDetail>(`/api/epics/ramayana/kandas/${k}/sargas/${s}`),
  batchPreview: (b: BatchRequest) => post<BatchPreview>('/api/epic-batches/preview', b),
  createBatch: (b: BatchRequest & { confirm: true; confirm_all?: boolean }) => post<BatchCreated>('/api/epic-batches', b),
  batches: () => req<BatchSummary[]>('/api/epic-batches'),
  batch: (id: BatchId) => req<BatchDetail>(`/api/epic-batches/${id}`),
  importBatchDrive: (id: BatchId) => post<BatchImportResult>(`/api/epic-batches/${id}/import-drive`),
  uploadBatchResult: (id: BatchId, file: File, onProgress?: (frac: number) => void) =>
    new Promise<BatchUploadResult>((resolve, reject) => {
      if (STANDALONE) { reject(new Error(OFFLINE_MSG)); return }
      const x = new XMLHttpRequest()
      x.open('PUT', `/api/epic-batches/${id}/result`)
      x.setRequestHeader('Content-Type', 'application/zip')
      x.upload.onprogress = e => { if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total) }
      x.onerror = () => reject(new Error('Network error during upload'))
      x.onload = () => {
        let body: unknown = null
        try { body = JSON.parse(x.responseText) } catch { /* non-JSON */ }
        if (x.status >= 200 && x.status < 300) { resolve(body as BatchUploadResult); return }
        const d = (body as { detail?: unknown } | null)?.detail
        reject(new Error(d ? (typeof d === 'string' ? d : JSON.stringify(d)) : `${x.status} ${x.statusText}`))
      }
      x.send(file)
    }),
  uploadAlignZip: (file: File, onProgress?: (frac: number) => void) =>
    new Promise<AlignUploadResult>((resolve, reject) => {
      if (STANDALONE) { reject(new Error(OFFLINE_MSG)); return }
      const x = new XMLHttpRequest()
      x.open('PUT', '/api/alignment/upload')
      x.setRequestHeader('Content-Type', 'application/zip')
      x.upload.onprogress = e => { if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total) }
      x.onerror = () => reject(new Error('Network error during upload'))
      x.onload = () => {
        let body: unknown = null
        try { body = JSON.parse(x.responseText) } catch { /* non-JSON */ }
        if (x.status >= 200 && x.status < 300) { resolve(body as AlignUploadResult); return }
        const d = (body as { detail?: unknown } | null)?.detail
        reject(new Error(d ? (typeof d === 'string' ? d : JSON.stringify(d)) : `${x.status} ${x.statusText}`))
      }
      x.send(file)
    }),
  alignment: (id: number) => req<Alignment>(`/api/jobs/${id}/alignment`),
}
export const audioUrl = (jobId: number) => STANDALONE ? `/data/jobs/${jobId}/audio.mp3` : `/api/jobs/${jobId}/audio.mp3`
export const bundleUrl = (jobId: number) => `/api/jobs/${jobId}/bundle`
export const batchInputUrl = (id: BatchId) => `/api/epic-batches/${id}/input.zip`
