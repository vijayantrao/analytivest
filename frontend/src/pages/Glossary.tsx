import { useState } from 'react'
import { Card, ErrorState, PageSkeleton, useGlossary } from '../components/ui'

export default function Glossary() {
  const q = useGlossary()
  const [filter, setFilter] = useState('')
  if (q.isLoading) return <PageSkeleton />
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />
  const terms = Object.entries(q.data.terms as Record<string, any>)
    .filter(([, t]) => !filter || `${t.term} ${t.short}`.toLowerCase().includes(filter.toLowerCase()))
    .sort((a, b) => a[1].term.localeCompare(b[1].term))
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-xl font-semibold">Glossary</h1>
        <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter terms…" aria-label="Filter terms"
          className="w-64 rounded-lg border border-line bg-surface px-3 py-1.5 text-sm outline-none focus:border-accent" />
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        {terms.map(([k, t]) => (
          <Card key={k} id={k} title={t.term}>
            <p className="text-[13px] text-ink">{t.short}</p>
            {t.formula && <code className="mt-2 block rounded bg-surface-2 px-2 py-1 text-xs">{t.formula}</code>}
            {t.long && <p className="mt-2 text-[13px] text-ink-2">{t.long}</p>}
          </Card>
        ))}
      </div>
    </div>
  )
}
