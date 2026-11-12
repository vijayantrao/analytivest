import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Trash2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Card, EmptyState, ErrorState, Skeleton } from '../components/ui'
import { api } from '../lib/api'
import { dateTime, isNum, pct, price } from '../lib/format'

export default function Watchlist() {
  const qc = useQueryClient()
  const w = useQuery({ queryKey: ['watchlist', 'details'], queryFn: () => api.watchlist(true) })
  const saved = useQuery({ queryKey: ['saved'], queryFn: api.saved })
  const rm = useMutation({ mutationFn: api.watchRemove, onSuccess: () => qc.invalidateQueries({ queryKey: ['watchlist'] }) })
  const del = useMutation({ mutationFn: api.savedDelete, onSuccess: () => qc.invalidateQueries({ queryKey: ['saved'] }) })
  const items = w.data?.items || []
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Watchlist & saved analyses</h1>
      <Card title="Watchlist" subtitle="Scores use cached data; the first load of a new company may take a while.">
        {w.isLoading ? <Skeleton className="h-32" /> : w.isError ? <ErrorState error={w.error} onRetry={() => w.refetch()} /> : items.length === 0 ? (
          <EmptyState title="Nothing on your watchlist yet">Open a company and press “Watch”.</EmptyState>
        ) : (
          <div className="scroll-x">
            <table className="w-full min-w-[760px] text-[13px]">
              <thead><tr className="border-b border-line text-left text-muted">
                <th className="py-2 font-medium">Company</th><th className="py-2 text-right font-medium">Price</th><th className="py-2 text-right font-medium">Day</th>
                <th className="py-2 pl-4 font-medium">Business quality</th><th className="py-2 font-medium">Financial risk</th><th className="py-2 font-medium">Valuation</th><th className="py-2 font-medium">Flags</th><th /></tr></thead>
              <tbody>
                {items.map((it: any) => {
                  const s = it.summary
                  return (
                    <tr key={it.symbol} className="border-b border-line/60">
                      <td className="py-2"><Link to={`/c/${it.symbol}`} className="font-medium hover:text-accent">{it.name || it.symbol}</Link><span className="block text-[11px] text-muted">{it.symbol}</span></td>
                      {it.error ? <td colSpan={6} className="py-2 text-xs text-warn">{it.error}</td> : (
                        <>
                          <td className="num py-2 text-right">{price(s.price, s.currency)}</td>
                          <td className="num py-2 text-right">{pct(s.change_pct, 2, true)}</td>
                          <td className="py-2 pl-4">{isNum(s.business_quality) ? `${s.business_quality.toFixed(0)} · ${s.business_quality_label}` : 'n/a'}</td>
                          <td className="py-2">{isNum(s.financial_risk) ? `${s.financial_risk.toFixed(0)} · ${s.financial_risk_label}` : 'n/a'}</td>
                          <td className="py-2">{s.valuation_label}</td>
                          <td className="py-2">{s.flags_total} ({s.flags_high} high)</td>
                        </>
                      )}
                      <td className="py-2 text-right"><button aria-label={`Remove ${it.symbol}`} onClick={() => rm.mutate(it.symbol)} className="p-1 text-muted hover:text-neg"><Trash2 size={14} /></button></td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <Card title="Saved analyses" subtitle="Point-in-time snapshots of verdicts, flags and the narrative">
        {(saved.data?.items || []).length === 0 ? <p className="text-sm text-muted">None saved yet. Use “Save snapshot” on a company page.</p> : (
          <ul className="divide-y divide-line">
            {saved.data.items.map((s: any) => (
              <li key={s.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-[13px]">
                <span><Link to={`/c/${s.symbol}`} className="font-medium hover:text-accent">{s.summary?.name || s.symbol}</Link>
                  <span className="block text-xs text-muted">{dateTime(s.created_at)} · {s.summary?.decision_label} · BQ {isNum(s.summary?.business_quality) ? s.summary.business_quality.toFixed(0) : 'n/a'} · risk {s.summary?.financial_risk_label} · {s.summary?.valuation_label} · price then {price(s.summary?.price, s.summary?.currency)}</span></span>
                <button aria-label="Delete snapshot" onClick={() => del.mutate(s.id)} className="p-1 text-muted hover:text-neg"><Trash2 size={14} /></button>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}
