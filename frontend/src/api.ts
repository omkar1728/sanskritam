import type {
  Alignment, CreateJob, ExecutorHealth, ExecutorInfo, Job, MeaningsUpdate, Meter, MeterSuggestion, NewVerse, Settings, SettingsUpdate, Verse, Voice,
} from './types'

async function req<T>(path: string, init?: RequestInit): Promise<T> {
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
  alignment: (id: number) => req<Alignment>(`/api/jobs/${id}/alignment`),
}
export const audioUrl = (jobId: number) => `/api/jobs/${jobId}/audio.mp3`
export const bundleUrl = (jobId: number) => `/api/jobs/${jobId}/bundle`
