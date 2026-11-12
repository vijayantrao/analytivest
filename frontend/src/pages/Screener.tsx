import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDown, ArrowUp, Play, Square } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge, Card, EmptyState, ErrorState, Segmented, Skeleton, cx } from '../components/ui'
import { api } from '../lib/api'
import { dateTime, isNum, money, pct, ratio } from '../lib/format'
import { JobProgress, useJob } from './Alerts'
import { ML_LEVEL } from './company/Extras'

type F = { minBQ: number; maxRisk: number; val: string; sector: string; minROE: string; maxDE: string; maxPE: string; minDY: string; text: string }
const BLANK: F = { minBQ: 0, maxRisk: 100, val: 'any', sector: 'any', minROE: '', maxDE: '', maxPE: '', minDY: '', text: '' }
const PRESETS: Record<string, { label: string; f: Partial<F>; note: string }> = {
  all: { label: 'All', f: {}, note: 'Everything scanned.' },
  quality: { label: 'Quality at a fair price', f: { minBQ: 70, maxRisk: 35, val: 'fair_or_cheap' }, note: 'Business quality ≥ 70, financial risk ≤ 35, price within or below the fair-value range.' },
  undervalued: { label: 'Potentially undervalued', f: { minBQ: 50, val: 'Potentially undervalued' }, note: 'Below the estimated fair-value range with business quality ≥ 50.' },
  dividend: { label: 'Low-risk dividend payers', f: { maxRisk: 25, minDY: '2' }, note: 'Financial risk ≤ 25 and dividend yield ≥ 2%.' },
  avoid: { label: 'Red-flag watch', f: { maxRisk: 100, minBQ: 0 }, note: 'Elevated or high financial risk: companies to research carefully (or avoid).' },
  ml: { label: 'Unusual accounts (ML)', f: {}, note: 'Earnings-quality signals unlike their peers, according to the machine-learning model (top 10% of the scan; banks excluded). Unusual is not wrong: read the reasons, then the annual report.' },
}

type SortKey = 'market_cap' | 'business_quality' | 'financial_risk' | 'valuation_score' | 'pe' | 'roe' | 'dividend_yield' | 'ml'

export default function Screener() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['screener'], queryFn: api.screener })
  const [size, setSize] = useState('100')
  const [peers, setPeers] = useState(false)
  const [jobId, setJobId] = useState<string | null>(null)
  const job = useJob(jobId)
  const [preset, setPreset] = useState('quality')
  const [f, setF] = useState<F>({ ...BLANK, ...PRESETS.quality.f })
  const [sort, setSort] = useState<{ k: SortKey; desc: boolean }>({ k: 'business_quality', desc: true })
  const scan = useMutation({ mutationFn: () => api.scan(Number(size), peers), onSuccess: (d) => setJobId(d.job_id) })
  const cancel = useMutation({ mutationFn: api.scanCancel })
  useEffect(() => { if (q.data?.job && ['queued', 'running'].includes(q.data.job.status) && !jobId) setJobId(q.data.job.id) }, [q.data, jobId])
  useEffect(() => { if (job.data) qc.invalidateQueries({ queryKey: ['screener'] }) }, [job.data?.progress, job.data?.status, qc])

  const rows: any[] = useMemo(() => (q.data?.results || []).map((r: any) => ({ symbol: r.symbol, scanned_at: r.scanned_at, ...r.summary, ml: q.data?.ml?.[r.symbol] })), [q.data])
  const sectors = useMemo(() => Array.from(new Set(rows.map((r) => r.sector).filter(Boolean))).sort(), [rows])
  const filtered = useMemo(() => {
    const num = (v: string) => (v === '' ? null : Number(v))
    return rows.filter((r) => {
      const m = r.metrics || {}
      if (preset === 'avoid' && !['Elevated', 'High'].includes(r.financial_risk_label)) return false
      if (preset === 'ml' && !(r.ml && r.ml.level !== 'typical')) return false
      if ((r.business_quality ?? -1) < f.minBQ && f.minBQ > 0) return false
      if (f.maxRisk < 100 && !(isNum(r.financial_risk) && r.financial_risk <= f.maxRisk)) return false
      if (f.val === 'fair_or_cheap' && !['Within estimated fair-value range', 'Potentially undervalued'].includes(r.valuation_label)) return false
      if (f.val !== 'any' && f.val !== 'fair_or_cheap' && r.valuation_label !== f.val) return false
      if (f.sector !== 'any' && r.sector !== f.sector) return false
      if (num(f.minROE) != null && !(isNum(m.roe) && m.roe >= num(f.minROE)!)) return false
      if (num(f.maxDE) != null && isNum(m.debt_to_equity) && m.debt_to_equity > num(f.maxDE)!) return false
      if (num(f.maxPE) != null && !(isNum(m.pe) && m.pe <= num(f.maxPE)!)) return false
      if (num(f.minDY) != null && !(isNum(m.dividend_yield) && m.dividend_yield >= num(f.minDY)!)) return false
      if (f.text && !`${r.name} ${r.symbol}`.toLowerCase().includes(f.text.toLowerCase())) return false
      return true
    }).sort((a, b) => {
      const g = (r: any) => (sort.k === 'ml' ? r.ml?.percentile : ['pe', 'roe', 'dividend_yield'].includes(sort.k) ? r.metrics?.[sort.k] : r[sort.k])
      const va = g(a), vb = g(b)
      if (!isNum(va)) return 1
      if (!isNum(vb)) return -1
      return sort.desc ? vb - va : va - vb
    })
  }, [rows, f, sort, preset])

  const choose = (k: string) => { setPreset(k); setF({ ...BLANK, ...PRESETS[k].f }); if (k === 'ml') setSort({ k: 'ml', desc: true }) }
  const head = (k: SortKey, label: string, right = true) => (
    <th className={cx('py-2 font-medium', right && 'text-right')}>
      <button onClick={() => setSort({ k, desc: sort.k === k ? !sort.desc : true })} className="inline-flex items-center gap-0.5 hover:text-ink" aria-label={`Sort by ${label}`}>
        {label}{sort.k === k && (sort.desc ? <ArrowDown size={11} aria-hidden /> : <ArrowUp size={11} aria-hidden />)}
      </button>
    </th>
  )
  const est = q.data?.estimates?.[size]
  const running = job.data && ['queued', 'running'].includes(job.data.status)
  const lastScan = rows.length ? Math.max(...rows.map((r) => r.scanned_at)) : null

  if (q.isLoading) return <Skeleton className="h-60" />
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Stock screener</h1>
        <p className="max-w-3xl text-[13px] text-ink-2">Scan the largest Indian listed companies through the same three verdicts, then filter. Scanning uses the free data provider politely, so it runs in the background; results are kept and re-scanned after 24 hours.</p>
      </div>
      <Card title="Scan" subtitle={lastScan ? `${rows.length} companies scanned · latest ${dateTime(lastScan)}` : 'No scan yet.'}>
        <div className="flex flex-wrap items-center gap-3">
          <Segmented label="Universe size" value={size} onChange={setSize} options={['50', '100', '200', '500'].map((v) => ({ value: v, label: `Top ${v}` }))} />
          <label className="flex items-center gap-2 text-[13px]"><input type="checkbox" checked={peers} onChange={(e) => setPeers(e.target.checked)} /> Include peer comparison (slower; matches company pages)</label>
          {running
            ? <button onClick={() => cancel.mutate()} className="inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-2 text-sm"><Square size={14} aria-hidden /> Stop</button>
            : <button onClick={() => scan.mutate()} disabled={scan.isPending} className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white disabled:opacity-60"><Play size={14} aria-hidden /> Start scan</button>}
          {est && <span className="text-xs text-muted">≈ {peers ? est.peers : est.fast} min on a cold cache (much faster for already-analysed companies)</span>}
        </div>
        {scan.isError && <p role="alert" className="mt-2 text-sm text-neg">{(scan.error as Error).message}</p>}
        {job.data && <div className="mt-3"><JobProgress job={job.data} /></div>}
        {!peers && <p className="mt-2 text-[11px] text-muted">Fast mode skips peer comparison, so valuation uses DCF/DDM only and the industry score is blank; open a company for its full analysis.</p>}
      </Card>

      {rows.length === 0 ? <EmptyState title="Run a scan to start screening">Top 100 takes a few minutes the first time.</EmptyState> : (
        <>
          <div className="flex flex-wrap gap-2" role="tablist" aria-label="Presets">
            {Object.entries(PRESETS).map(([k, p]) => (
              <button key={k} role="tab" aria-selected={preset === k} onClick={() => choose(k)}
                className={cx('rounded-full border px-3 py-1 text-[13px]', preset === k ? 'border-accent bg-accent-soft text-accent-ink' : 'border-line text-ink-2 hover:text-ink')}>{p.label}</button>
            ))}
          </div>
          <p className="text-xs text-muted">{PRESETS[preset].note}</p>
          <Card title="Filters">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
              <label className="block text-xs"><span className="text-ink-2">Min business quality: <b className="num">{f.minBQ}</b></span>
                <input type="range" min={0} max={90} step={5} value={f.minBQ} onChange={(e) => setF({ ...f, minBQ: Number(e.target.value) })} className="mt-2 w-full" /></label>
              <label className="block text-xs"><span className="text-ink-2">Max financial risk: <b className="num">{f.maxRisk}</b></span>
                <input type="range" min={10} max={100} step={5} value={f.maxRisk} onChange={(e) => setF({ ...f, maxRisk: Number(e.target.value) })} className="mt-2 w-full" /></label>
              <label className="block text-xs"><span className="text-ink-2">Valuation</span>
                <select value={f.val} onChange={(e) => setF({ ...f, val: e.target.value })} className="mt-1 w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-sm">
                  <option value="any">Any</option><option value="fair_or_cheap">Within range or below</option><option>Potentially undervalued</option>
                  <option>Within estimated fair-value range</option><option>Potentially overvalued</option><option>Cannot reliably assess</option></select></label>
              <label className="block text-xs"><span className="text-ink-2">Sector</span>
                <select value={f.sector} onChange={(e) => setF({ ...f, sector: e.target.value })} className="mt-1 w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-sm">
                  <option value="any">Any</option>{sectors.map((s) => <option key={s}>{s}</option>)}</select></label>
              {([['minROE', 'Min ROE %'], ['maxDE', 'Max debt/equity'], ['maxPE', 'Max P/E'], ['minDY', 'Min dividend yield %']] as const).map(([k, l]) => (
                <label key={k} className="block text-xs"><span className="text-ink-2">{l}</span>
                  <input type="number" step="any" value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} className="num mt-1 w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-sm" /></label>
              ))}
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <input value={f.text} onChange={(e) => setF({ ...f, text: e.target.value })} placeholder="Filter by name…" aria-label="Filter by name"
                className="w-56 rounded-lg border border-line bg-surface px-2 py-1.5 text-sm" />
              <button onClick={() => { setPreset('all'); setF(BLANK) }} className="text-xs text-accent">Reset filters</button>
              <span className="text-xs text-muted">{filtered.length} of {rows.length} match</span>
            </div>
          </Card>
          <Card>
            <div className="scroll-x">
              <table className="w-full min-w-[1080px] text-[13px]">
                <thead><tr className="border-b border-line text-left text-muted">
                  <th className="py-2 font-medium">Company</th>{head('market_cap', 'Mcap')}{head('business_quality', 'Quality')}{head('financial_risk', 'Risk')}
                  {head('valuation_score', 'Valuation')}{head('pe', 'P/E')}{head('roe', 'ROE')}<th className="py-2 text-right font-medium">D/E</th>{head('dividend_yield', 'Div. yield')}
                  <th className="py-2 pl-3 font-medium">Flags</th>{head('ml', 'ML check')}</tr></thead>
                <tbody>
                  {filtered.slice(0, 300).map((r) => (
                    <tr key={r.symbol} className="border-b border-line/60 align-top">
                      <td className="py-2"><Link to={`/c/${r.symbol}`} className="font-medium hover:text-accent">{r.name}</Link>
                        <span className="block text-[11px] text-muted">{r.symbol} · {r.sector || '—'}</span></td>
                      <td className="num py-2 text-right">{money(r.market_cap, r.currency || 'INR')}</td>
                      <td className="num py-2 text-right">{isNum(r.business_quality) ? r.business_quality.toFixed(0) : '—'}<span className="block text-[11px] text-muted">{r.business_quality_label}</span></td>
                      <td className="num py-2 text-right">{isNum(r.financial_risk) ? r.financial_risk.toFixed(0) : '—'}<span className="block text-[11px] text-muted">{r.financial_risk_label}</span></td>
                      <td className="py-2 text-right text-xs">{r.valuation_label}</td>
                      <td className="num py-2 text-right">{ratio(r.metrics?.pe, 1)}</td>
                      <td className="num py-2 text-right">{pct(r.metrics?.roe)}</td>
                      <td className="num py-2 text-right">{ratio(r.metrics?.debt_to_equity)}</td>
                      <td className="num py-2 text-right">{pct(r.metrics?.dividend_yield, 2)}</td>
                      <td className="py-2 pl-3 text-xs">{r.flags_total ? <Badge tone={r.flags_high ? 'neg' : 'warn'}>{r.flags_total} ({r.flags_high} high)</Badge> : <span className="text-muted">none</span>}</td>
                      <td className="py-2 text-right text-xs">{r.ml ? <span title={r.ml.reasons.join('\n') || 'No single signal stands out'}><Badge tone={ML_LEVEL[r.ml.level].tone}>{ML_LEVEL[r.ml.level].label}</Badge>
                        <span className="block text-[11px] text-muted">more unusual than {Math.floor(r.ml.percentile)}%</span></span> : <span className="text-muted">—</span>}
                        {preset === 'ml' && r.ml?.reasons?.length > 0 && <span className="mt-1 block max-w-xs text-left text-[11px] text-ink-2">{r.ml.reasons[0]}</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-xs text-muted">A starting list for your own research, not recommendations. Verdicts use the free data provider's figures as of each scan.</p>
          </Card>
        </>
      )}
    </div>
  )
}
