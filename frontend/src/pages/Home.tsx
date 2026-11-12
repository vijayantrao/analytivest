import { useQuery } from '@tanstack/react-query'
import { Activity, ArrowRight, Gauge, Rocket, Scale, ShieldAlert, Star } from 'lucide-react'
import { Link } from 'react-router-dom'
import { SearchBox } from '../components/SearchBox'
import { Badge, Card, EmptyState, Skeleton } from '../components/ui'
import { api } from '../lib/api'
import { ago, shortDate } from '../lib/format'

const EXAMPLES = [
  { s: 'TCS.NS', l: 'TCS' }, { s: 'HDFCBANK.NS', l: 'HDFC Bank' }, { s: 'RELIANCE.NS', l: 'Reliance' },
  { s: 'INFY.NS', l: 'Infosys' }, { s: 'ASIANPAINT.NS', l: 'Asian Paints' },
]
const SAMPLES = [
  { s: 'DEMO-STEADY', l: 'Steady consumer' }, { s: 'DEMO-LEVER', l: 'Leveraged infra' }, { s: 'DEMO-BANK', l: 'Sample bank' },
]

export default function Home() {
  const watch = useQuery({ queryKey: ['watchlist'], queryFn: () => api.watchlist(false) })
  const ipos = useQuery({ queryKey: ['ipos'], queryFn: api.ipos })
  const health = useQuery({ queryKey: ['health'], queryFn: api.health })
  const saved = useQuery({ queryKey: ['saved'], queryFn: api.saved })

  return (
    <div className="space-y-6">
      <section className="mx-auto max-w-3xl pt-6 text-center sm:pt-10">
        <p className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-accent">Analytivest · Invest with evidence</p>
        <h1 className="text-2xl font-semibold tracking-tight text-ink sm:text-3xl">Data-led analysis of Indian stocks and IPOs</h1>
        <p className="mx-auto mt-2 max-w-2xl text-[15px] text-ink-2">
          Three separate verdicts (business quality, financial risk and valuation), each traced to the numbers, sources and formulas behind it.
        </p>
        <div className="mt-5 text-left"><SearchBox size="lg" autoFocus globalShortcut /></div>
        <div className="mt-3 flex flex-wrap items-center justify-center gap-2 text-sm">
          <span className="text-muted">Try:</span>
          {EXAMPLES.map((e) => (
            <Link key={e.s} to={`/c/${e.s}`} className="rounded-full border border-line bg-surface px-3 py-1 text-ink-2 hover:border-accent hover:text-accent">{e.l}</Link>
          ))}
        </div>
        <div className="mt-2 flex flex-wrap items-center justify-center gap-2 text-xs">
          <span className="text-muted">Offline sample data:</span>
          {SAMPLES.map((e) => (
            <Link key={e.s} to={`/c/${e.s}`} className="rounded-full border border-dashed border-line-strong px-2.5 py-0.5 text-muted hover:text-ink">{e.l}</Link>
          ))}
        </div>
      </section>

      <section aria-label="The three verdicts" className="grid gap-3 sm:grid-cols-3">
        {[
          { icon: Gauge, t: 'Business quality', d: 'Is the company fundamentally strong? Growth, profitability, cash conversion and governance.' },
          { icon: ShieldAlert, t: 'Financial risk', d: 'How vulnerable is it to debt, cash-flow problems or deterioration? Leverage, liquidity and red flags.' },
          { icon: Scale, t: 'Valuation', d: 'Is the price reasonable? DCF, peer multiples and history, with assumptions you can edit.' },
        ].map((x) => (
          <div key={x.t} className="rounded-xl border border-line bg-surface p-4">
            <x.icon size={18} className="text-accent" aria-hidden />
            <h2 className="mt-2 text-sm font-semibold">{x.t}</h2>
            <p className="mt-1 text-[13px] text-ink-2">{x.d}</p>
          </div>
        ))}
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={<span className="inline-flex items-center gap-2"><Star size={16} aria-hidden /> Watchlist</span>}
          actions={<Link to="/watchlist" className="text-xs text-accent">Open with scores <ArrowRight size={12} className="inline" /></Link>}>
          {watch.isLoading ? <Skeleton className="h-24" /> : (watch.data?.items || []).length === 0 ? (
            <EmptyState title="Your watchlist is empty">Open a company and press “Watch” to track it here.</EmptyState>
          ) : (
            <ul className="divide-y divide-line">
              {watch.data.items.slice(0, 8).map((w: any) => (
                <li key={w.symbol}>
                  <Link to={`/c/${w.symbol}`} className="flex items-center justify-between py-2 hover:text-accent">
                    <span className="truncate text-sm">{w.name || w.symbol}</span>
                    <span className="text-xs text-muted">{w.symbol}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title={<span className="inline-flex items-center gap-2"><Rocket size={16} aria-hidden /> IPOs</span>}
          actions={<Link to="/ipo/upload" className="text-xs text-accent">Upload RHP/DRHP <ArrowRight size={12} className="inline" /></Link>}>
          {ipos.isLoading ? <Skeleton className="h-24" /> : (
            <ul className="divide-y divide-line">
              {(ipos.data?.items || []).slice(0, 6).map((i: any) => (
                <li key={i.id}>
                  <Link to={`/ipo/${i.id}`} className="flex items-center justify-between gap-2 py-2 hover:text-accent">
                    <span className="truncate text-sm">{i.name}</span>
                    <span className="flex shrink-0 items-center gap-2 text-xs text-muted">
                      {i.is_sample && <Badge tone="warn">Sample</Badge>}
                      ₹{i.price_band?.[0]}–{i.price_band?.[1]}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 text-xs text-muted">{ipos.data?.note}</p>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Saved analyses" subtitle="Snapshots you saved from a company page">
          {(saved.data?.items || []).length === 0 ? <p className="text-sm text-muted">None yet.</p> : (
            <ul className="divide-y divide-line">
              {saved.data.items.slice(0, 6).map((s: any) => (
                <li key={s.id} className="flex items-center justify-between py-2 text-sm">
                  <Link to={`/c/${s.symbol}`} className="truncate hover:text-accent">{s.label || s.summary?.name || s.symbol}</Link>
                  <span className="shrink-0 text-xs text-muted">{s.summary?.decision_label} · {shortDate(new Date(s.created_at * 1000))}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title={<span className="inline-flex items-center gap-2"><Activity size={16} aria-hidden /> Data status</span>}>
          {health.isError ? <p className="text-sm text-neg">Backend unreachable. Start it with start.ps1.</p> : (
            <ul className="space-y-1 text-sm text-ink-2">
              {(health.data?.providers || []).map((p: any) => <li key={p.name}>✓ {p.label}</li>)}
              {health.data?.offline && <li className="text-warn">Offline mode: only sample data is available.</li>}
              {Object.entries(health.data?.cache || {}).map(([k, v]: any) => (
                <li key={k} className="text-xs text-muted">Cache · {k}: {v.count} item(s), last update {ago(v.last_fetched_at)}</li>
              ))}
              <li className="text-xs text-muted">Quotes are delayed (not real-time). Fundamentals refresh every 24 h, quotes every 15 min.</li>
            </ul>
          )}
        </Card>
      </div>
    </div>
  )
}
