import { useEffect, useState } from 'react'
import { api } from '../../api'
import type { EpicSummary } from '../../types'

export interface LoadState<T> { data: T | null; error: string; loading: boolean }

export function useLoad<T>(fn: () => Promise<T>, deps: unknown[]): LoadState<T> {
  const key = JSON.stringify(deps)
  const [res, setRes] = useState<{ key: string; data: T | null; error: string } | null>(null)
  useEffect(() => {
    let live = true
    fn().then(
      data => { if (live) setRes({ key, data, error: '' }) },
      e => { if (live) setRes({ key, data: null, error: (e as Error).message }) },
    )
    return () => { live = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
  if (!res || res.key !== key) return { data: null, error: '', loading: true }
  return { data: res.data, error: res.error, loading: false }
}

/** The EpicSummary for an epic id (null while loading or unknown). */
export function useEpic(id: string): EpicSummary | null {
  const { data } = useLoad(() => api.epics(), [])
  return data?.find(e => e.id === id) ?? null
}
