import { useQuery } from '@tanstack/react-query'
import { X } from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import { SeriesChart } from '../components/charts'
import { SearchBox } from '../components/SearchBox'
import { Badge, Card, EmptyState, ErrorState, PageSkeleton, cx } from '../components/ui'
import { api } from '../lib/api'
import { isNum, money, pct, price, ratio } from '../lib/format'

type Row = { label: string; get: (r: any) => any; fmt: (v: any, r: any) => string; better?: 'high' | 'low' }
const ROWS: { group: string; rows: Row[] }[] = [
  { group: 'Verdicts', rows: [
    { label: 'Decision support', get: (r) => r.decision_label, fmt: (v) => v ?? '—' },
    { label: 'Business quality', get: (r) => r.business_quality, fmt: (v, r) => (isNum(v) ? `${v.toFixed(0)} · ${r.business_quality_label}` : 'n/a'), better: 'high' },
    { label: 'Financial risk (higher = riskier)', get: (r) => r.financial_risk, fmt: (v, r) => (isNum(v) ? `${v.toFixed(0)} · ${r.financial_risk_label}` : 'n/a'), better: 'low' },
    { label: 'Valuation', get: (r) => r.valuation_score, fmt: (v, r) => `${r.valuation_label}${isNum(v) ? ` (${v.toFixed(0)})` : ''}`, better: 'high' },
    { label: 'Confidence / completeness', get: (r) => r.completeness, fmt: (v, r) => `${r.confidence} · ${isNum(v) ? v.toFixed(0) : '—'}%` },
    { label: 'Red flags (high)', get: (r) => r.flags_total, fmt: (v, r) => `${v} (${r.flags_high})`, better: 'low' },
  ] },
  { group: 'Size & price', rows: [
    { label: 'Price', get: (r) => r.price, fmt: (v, r) => price(v, r.currency) },
    { label: 'Market cap', get: (r) => r.market_cap, fmt: (v, r) => money(v, r.currency) },
    { label: 'Latest fiscal year', get: (r) => r.latest_period, fmt: (v) => v ?? '—' },
  ] },
  { group: 'Growth & profitability', rows: [
    { label: 'Revenue CAGR (3y or longest)', get: (r) => r.metrics.revenue_cagr_3y, fmt: (v) => pct(v), better: 'high' },
    { label: 'EPS CAGR (3y or longest)', get: (r) => r.metrics.eps_cagr_3y, fmt: (v) => pct(v), better: 'high' },
    { label: 'ROE', get: (r) => r.metrics.roe, fmt: (v) => pct(v), better: 'high' },
    { label: 'ROCE', get: (r) => r.metrics.roce, fmt: (v) => pct(v), better: 'high' },
    { label: 'Operating margin', get: (r) => r.metrics.operating_margin, fmt: (v) => pct(v), better: 'high' },
    { label: 'Net margin', get: (r) => r.metrics.net_margin, fmt: (v) => pct(v), better: 'high' },
  ] },
  { group: 'Balance sheet & cash', rows: [
    { label: 'Debt / equity', get: (r) => r.metrics.debt_to_equity, fmt: (v) => ratio(v), better: 'low' },
    { label: 'Interest coverage', get: (r) => r.metrics.interest_coverage, fmt: (v) => ratio(v, 1), better: 'high' },
    { label: 'Cash conversion (CFO/PAT)', get: (r) => r.metrics.cash_conversion, fmt: (v) => ratio(v), better: 'high' },
    { label: 'FCF margin', get: (r) => r.metrics.fcf_margin, fmt: (v) => pct(v), better: 'high' },
  ] },
  { group: 'Valuation', rows: [
    { label: 'P/E (latest FY)', get: (r) => r.metrics.pe, fmt: (v) => ratio(v, 1), better: 'low' },
    { label: 'P/B', get: (r) => r.metrics.pb, fmt: (v) => ratio(v, 2), better: 'low' },
    { label: 'EV/EBITDA', get: (r) => r.metrics.ev_ebitda, fmt: (v) => ratio(v, 1), better: 'low' },
    { label: 'FCF yield', get: (r) => r.metrics.fcf_yield, fmt: (v) => pct(v), better: 'high' },
    { label: 'Dividend yield', get: (r) => r.metrics.dividend_yield, fmt: (v) => pct(v, 2) },
  ] },
]

export default function Compare() {
  const [sp, setSp] = useSearchParams()
  const syms = (sp.get('s') || '').split(',').map((s) => s.trim()).filter(Boolean).slice(0, 5)
  const q = useQuery({ queryKey: ['compare', syms.join(',')], queryFn: () => api.compare(syms), enabled: syms.length > 0 })
  const setSyms = (list: string[]) => setSp(list.length ? { s: list.join(',') } : {})
  const rows = q.data?.rows || []
  const labels = Array.from(new Set(rows.flatMap((r: any) => r.series.labels))).sort() as string[]
  const roeRows = labels.map((l) => {
    const o: any = { label: l }
    rows.forEach((r: any, i: number) => { const j = r.series.labels.indexOf(l); o[`c${i}`] = j >= 0 ? r.series.roe[j] : null })
    return o
  })
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Compare companies</h1>
        <p className="text-[13px] text-ink-2">Up to five companies side by side. The best value in each row is marked ▲. Comparisons across sectors (e.g. a bank vs a manufacturer) are rarely like-for-like.</p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {syms.map((s) => (
          <span key={s} className="inline-flex items-center gap-1 rounded-full border border-line bg-surface py-1 pl-3 pr-1 text-sm">
            {s}<button aria-label={`Remove ${s}`} onClick={() => setSyms(syms.filter((x) => x !== s))} className="rounded-full p-0.5 text-muted hover:text-neg"><X size={14} /></button>
          </span>
        ))}
        {syms.length < 5 && <div className="w-full sm:w-80"><SearchBox placeholder="Add a company…" onSelect={(s) => !syms.includes(s) && setSyms([...syms, s])} /></div>}
      </div>
      {syms.length === 0 ? <EmptyState title="Add companies to compare">Search above, or open a company’s Peers tab and choose “Open in Compare”.</EmptyState>
        : q.isLoading ? <PageSkeleton /> : q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : !q.data ? <PageSkeleton /> : (
          <>
            {q.data.errors?.length > 0 && <p className="text-sm text-warn">Could not load: {q.data.errors.map((e: any) => `${e.symbol} (${e.message})`).join('; ')}</p>}
            <Card>
              <div className="scroll-x">
                <table className="w-full min-w-[640px] text-[13px]">
                  <thead>
                    <tr className="border-b border-line">
                      <th className="sticky left-0 bg-surface py-2 pr-3 text-left font-medium text-muted">Metric</th>
                      {rows.map((r: any) => (
                        <th key={r.symbol} className="py-2 pl-3 text-right align-bottom">
                          <Link to={`/c/${r.symbol}`} className="font-semibold hover:text-accent">{r.name}</Link>
                          <span className="block text-[11px] font-normal text-muted">{r.symbol}{r.model === 'financial' ? ' · financial model' : ''}</span>
                          {r.is_sample && <Badge tone="warn">Sample</Badge>}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  {ROWS.map((g) => (
                    <tbody key={g.group}>
                      <tr><td colSpan={rows.length + 1} className="pt-4 pb-1 text-xs font-semibold uppercase tracking-wide text-muted">{g.group}</td></tr>
                      {g.rows.map((row) => {
                        const vals = rows.map((r: any) => row.get(r))
                        const nums = vals.filter(isNum) as number[]
                        const best = row.better && nums.length > 1 ? (row.better === 'high' ? Math.max(...nums) : Math.min(...nums)) : null
                        return (
                          <tr key={row.label} className="border-b border-line/60">
                            <td className="sticky left-0 bg-surface py-1.5 pr-3 text-ink-2">{row.label}</td>
                            {rows.map((r: any, i: number) => (
                              <td key={r.symbol} className={cx('num py-1.5 pl-3 text-right', best != null && vals[i] === best && 'font-semibold')}>
                                {best != null && vals[i] === best && <span aria-label="best" className="mr-1 text-[10px] text-accent">▲</span>}
                                {row.fmt(vals[i], r)}
                              </td>
                            ))}
                          </tr>
                        )
                      })}
                    </tbody>
                  ))}
                </table>
              </div>
            </Card>
            {rows.length > 0 && rows.length <= 3 && (
              <SeriesChart title="Return on equity over time" subtitle="% by fiscal year" rows={roeRows}
                series={rows.map((r: any, i: number) => ({ key: `c${i}`, name: r.name, type: 'line' as const, color: (['s1', 's2', 's3'] as const)[i] }))}
                fmt={(v) => pct(v)} />
            )}
            {rows.length > 3 && <p className="text-xs text-muted">The ROE chart is shown for up to three companies, where colours stay distinguishable. The table above covers all of them.</p>}
          </>
        )}
    </div>
  )
}
