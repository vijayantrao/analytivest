import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ArrowDownRight, ArrowUpRight, Bookmark, Download, Printer, RefreshCw, Star } from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, useParams } from 'react-router-dom'
import { Badge, ErrorState, FreshnessBadge, PageSkeleton, SampleBanner, cx } from '../components/ui'
import { api } from '../lib/api'
import { money, pct, price } from '../lib/format'
import { CashFlow, Debt, Financials, Growth } from './company/Fundamentals'
import { AnalysisTab, News, Peers, Risks, Shareholding } from './company/Other'
import Overview from './company/Overview'
import Valuation from './company/Valuation'

const TABS = [
  { k: 'overview', l: 'Overview' }, { k: 'financials', l: 'Financials' }, { k: 'growth', l: 'Growth & profitability' },
  { k: 'debt', l: 'Debt & balance sheet' }, { k: 'cashflow', l: 'Cash flow' }, { k: 'valuation', l: 'Valuation' },
  { k: 'shareholding', l: 'Management & shareholding' }, { k: 'peers', l: 'Peers' }, { k: 'risks', l: 'Risks & red flags' },
  { k: 'news', l: 'News & disclosures' }, { k: 'analysis', l: 'Analysis' },
]

function Header({ a }: { a: any }) {
  const qc = useQueryClient()
  const q = a.quote
  const up = (q.change ?? 0) >= 0
  const [watched, setWatched] = useState<boolean>(a.in_watchlist)
  useEffect(() => setWatched(a.in_watchlist), [a.in_watchlist])
  // The intended action is passed in explicitly: onMutate flips `watched` before mutationFn runs.
  const watch = useMutation({
    mutationFn: (op: 'add' | 'remove') => (op === 'add' ? api.watchAdd(a.symbol) : api.watchRemove(a.symbol)),
    onMutate: (op) => setWatched(op === 'add'),
    onError: (_e, op) => setWatched(op !== 'add'),
    onSettled: () => qc.invalidateQueries({ queryKey: ['watchlist'] }),
  })
  const save = useMutation({ mutationFn: () => api.saveAnalysis(a.symbol), onSuccess: () => qc.invalidateQueries({ queryKey: ['saved'] }) })
  const refresh = useMutation({
    mutationFn: () => api.analysis(a.symbol, true),
    onSuccess: (d) => qc.setQueryData(['analysis', a.symbol], d),
  })
  const btn = 'inline-flex items-center gap-1.5 rounded-lg border border-line px-2.5 py-1.5 text-xs font-medium text-ink-2 hover:bg-surface-2 hover:text-ink disabled:opacity-50'
  return (
    <div className="space-y-3">
      {a.is_sample && <SampleBanner />}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">{a.profile.name}</h1>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-[13px] text-muted">
            <Badge tone="accent">{a.symbol}</Badge>
            <span>{a.profile.exchange}</span>
            {a.profile.sector && <span>· {a.profile.sector}</span>}
            {a.profile.industry && <span>· {a.profile.industry}</span>}
            {a.scores.model === 'financial' && <Badge>Financial-sector model</Badge>}
          </div>
        </div>
        <div className="sm:text-right">
          <div className="num text-2xl font-semibold">{price(q.price, q.currency)}</div>
          <div className={cx('num inline-flex items-center gap-1 text-sm font-medium', up ? 'text-pos' : 'text-neg')}>
            {up ? <ArrowUpRight size={15} aria-hidden /> : <ArrowDownRight size={15} aria-hidden />}
            {price(q.change, q.currency)} ({pct(q.change_pct, 2, true)})
            <span className="sr-only">{up ? 'up' : 'down'} today</span>
          </div>
          <div className="text-xs text-muted">Mcap {money(a.valuation.market_cap, q.currency)} · 52w {price(q.week52_low, q.currency)}–{price(q.week52_high, q.currency)}</div>
        </div>
      </div>
      <div className="no-print flex flex-wrap items-center gap-2">
        <FreshnessBadge freshness={a.quote_freshness} what="Quote (delayed)" />
        <FreshnessBadge freshness={a.freshness} what="Fundamentals" />
        <span className="flex-1" />
        <button className={btn} onClick={() => watch.mutate(watched ? 'remove' : 'add')} aria-pressed={watched}>
          <Star size={14} aria-hidden fill={watched ? 'currentColor' : 'none'} /> {watched ? 'Watching' : 'Watch'}
        </button>
        <button className={btn} onClick={() => save.mutate()} disabled={save.isPending}>
          <Bookmark size={14} aria-hidden /> {save.isSuccess ? 'Saved' : 'Save snapshot'}
        </button>
        <button className={btn} onClick={() => api.exportCsv(a.symbol).catch((e) => alert(`CSV export failed: ${e.message}`))}><Download size={14} aria-hidden /> CSV</button>
        <button className={btn} onClick={() => window.print()}><Printer size={14} aria-hidden /> PDF</button>
        <button className={btn} onClick={() => refresh.mutate()} disabled={refresh.isPending} title="Fetch fresh data from the provider">
          <RefreshCw size={14} className={cx(refresh.isPending && 'animate-spin')} aria-hidden /> Refresh
        </button>
      </div>
      {refresh.isError && <p className="text-xs text-neg">Refresh failed: {(refresh.error as Error).message}</p>}
      {a.freshness?.served_from === 'stale-cache' && (
        <div role="alert" className="flex items-start gap-2 rounded-lg bg-warn-soft px-3 py-2 text-[13px] text-warn">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" aria-hidden />
          The data provider is unavailable; showing cached data from {new Date(a.freshness.retrieved_at * 1000).toLocaleString('en-IN')}. It may be out of date.
        </div>
      )}
      {(a.data_quality || []).filter((d: any) => d.severity === 'high').map((d: any, i: number) => (
        <div key={i} role="note" className="flex items-start gap-2 rounded-lg border border-line bg-surface px-3 py-2 text-[13px] text-ink-2">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" style={{ color: 'var(--status-serious)' }} aria-hidden />
          <span><b className="text-ink">Data discrepancy:</b> {d.message}</span>
        </div>
      ))}
    </div>
  )
}

export default function Company() {
  const { symbol = '', tab = 'overview' } = useParams()
  const sym = symbol.toUpperCase()
  const q = useQuery({ queryKey: ['analysis', sym], queryFn: () => api.analysis(sym) })
  useEffect(() => {
    document.title = q.data ? `${q.data.profile.name} (${sym}) · Analytivest` : `${sym} · Analytivest`
  }, [q.data, sym])
  if (q.isLoading) {
    return (
      <div>
        <p className="mb-3 text-sm text-muted">Loading {sym}… The first load fetches statements, prices and peers from the provider and can take 10–40 seconds; later loads come from the local cache.</p>
        <PageSkeleton />
      </div>
    )
  }
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} title={`Could not analyse ${sym}`} />
  const a = q.data
  const active = TABS.find((t) => t.k === tab) ? tab : 'overview'
  return (
    <div className="space-y-4">
      <Header a={a} />
      <nav aria-label="Company sections" className="no-print sticky top-14 z-30 -mx-4 border-b border-line bg-bg/95 px-4 backdrop-blur">
        <ul className="no-scrollbar flex gap-1 overflow-x-auto">
          {TABS.map((t) => (
            <li key={t.k}>
              <NavLink to={`/c/${encodeURIComponent(sym)}${t.k === 'overview' ? '' : `/${t.k}`}`} end
                className={() => cx('block whitespace-nowrap border-b-2 px-3 py-2.5 text-[13px] font-medium',
                  active === t.k ? 'border-accent text-ink' : 'border-transparent text-muted hover:text-ink')}
                aria-current={active === t.k ? 'page' : undefined}>
                {t.l}
                {t.k === 'risks' && a.flags.length > 0 && <span className="ml-1.5 rounded-full bg-surface-2 px-1.5 text-[11px] text-ink-2">{a.flags.length}</span>}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
      <div>
        {active === 'overview' && <Overview a={a} />}
        {active === 'financials' && <Financials a={a} />}
        {active === 'growth' && <Growth a={a} />}
        {active === 'debt' && <Debt a={a} />}
        {active === 'cashflow' && <CashFlow a={a} />}
        {active === 'valuation' && <Valuation a={a} />}
        {active === 'shareholding' && <Shareholding a={a} />}
        {active === 'peers' && <Peers a={a} />}
        {active === 'risks' && <Risks a={a} />}
        {active === 'news' && <News a={a} />}
        {active === 'analysis' && <AnalysisTab a={a} />}
      </div>
      <p className="text-xs text-muted">{a.disclaimer}</p>
    </div>
  )
}
