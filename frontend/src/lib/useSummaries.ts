import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from './api'

/** Load company summaries a few at a time (each may trigger provider fetches), caching them in React Query. */
export function useSummaries(symbols: string[], concurrency = 2) {
  const qc = useQueryClient()
  const [state, setState] = useState<Record<string, { data?: any; error?: string; loading?: boolean }>>({})
  const key = symbols.join(',')
  useEffect(() => {
    let cancelled = false
    const queue = [...symbols]
    const next = async () => {
      while (!cancelled && queue.length) {
        const s = queue.shift()!
        setState((st) => ({ ...st, [s]: { ...st[s], loading: true } }))
        try {
          const data = await qc.fetchQuery({ queryKey: ['summary', s], queryFn: () => api.summary(s), staleTime: 10 * 60_000 })
          if (!cancelled) setState((st) => ({ ...st, [s]: { data } }))
        } catch (e) {
          if (!cancelled) setState((st) => ({ ...st, [s]: { error: (e as Error).message } }))
        }
      }
    }
    for (let i = 0; i < concurrency; i++) next()
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
  return state
}
