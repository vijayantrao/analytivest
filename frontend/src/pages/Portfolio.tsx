import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, FileUp, Loader2, Plus, Trash2 } from 'lucide-react'
import { useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { SearchBox } from '../components/SearchBox'
import { Badge, Card, EmptyState, ErrorState, MetricTile, ScoreBar, Segmented, Skeleton, cx } from '../components/ui'
import { api } from '../lib/api'
import { isNum, money, pct, price } from '../lib/format'
import { useSummaries } from '../lib/useSummaries'

type SortKey = 'value' | 'pnl_pct' | 'weight' | 'business_quality' | 'financial_risk'

export default function Portfolio() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['portfolio'], queryFn: api.portfolio })
  const holdings: any[] = q.data?.holdings || []
  const sums = useSummaries(holdings.map((h) => h.symbol))
  const file = useRef<HTMLInputElement>(null)
  const [mode, setMode] = useState<'replace' | 'merge'>('replace')
  const [sort, setSort] = useState<SortKey>('value')
  const [add, setAdd] = useState<{ symbol: string; qty: string; avg: string }>({ symbol: '', qty: '', avg: '' })

  const imp = useMutation({
    mutationFn: (f: File) => api.upload(`/api/portfolio/import?mode=${mode}`, f, f.name),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['portfolio'] }),
  })
  const addM = useMutation({
    mutationFn: () => api.holdingAdd(add.symbol, Number(add.qty), add.avg ? Number(add.avg) : undefined),
    onSuccess: () => { setAdd({ symbol: '', qty: '', avg: '' }); qc.invalidateQueries({ queryKey: ['portfolio'] }) },
  })
  const rm = useMutation({ mutationFn: api.holdingRemove, onSuccess: () => qc.invalidateQueries({ queryKey: ['portfolio'] }) })

  const rows = useMemo(() => {
    const r = holdings.map((h) => {
      const s = sums[h.symbol]?.data
      const p = s?.price
      const value = isNum(p) ? p * h.quantity : null
      const cost = isNum(h.avg_cost) ? h.avg_cost * h.quantity : null
      const dayChg = isNum(p) && isNum(s?.change_pct) ? value! - value! / (1 + s.change_pct / 100) : null
      return { ...h, s, value, cost, pnl: value != null && cost != null ? value - cost : null,
        pnl_pct: value != null && cost ? (value / cost - 1) * 100 : null, dayChg }
    })
    const total = r.reduce((a, x) => a + (x.value || 0), 0)
    r.forEach((x: any) => { x.weight = total && x.value != null ? (x.value / total) * 100 : null })
    const keyOf = (x: any) => sort === 'business_quality' || sort === 'financial_risk' ? x.s?.[sort] : x[sort]
    return r.sort((a: any, b: any) => (keyOf(b) ?? -Infinity) - (keyOf(a) ?? -Infinity))
  }, [holdings, sums, sort])

  const loaded = rows.filter((r) => r.value != null)
  const total = loaded.reduce((a, r) => a + r.value!, 0)
  const invested = loaded.reduce((a, r) => a + (r.cost || 0), 0)
  const day = loaded.reduce((a, r) => a + (r.dayChg || 0), 0)
  const wq = loaded.filter((r) => isNum(r.s?.business_quality))
  const wqTotal = wq.reduce((a, r) => a + r.value!, 0)
  const wQuality = wqTotal ? wq.reduce((a, r) => a + r.s.business_quality * r.value!, 0) / wqTotal : null
  const riskyValue = loaded.filter((r) => ['Elevated', 'High'].includes(r.s?.financial_risk_label)).reduce((a, r) => a + r.value!, 0)
  const sectors = useMemo(() => {
    const m: Record<string, number> = {}
    for (const r of loaded) m[r.s?.sector || 'Unknown'] = (m[r.s?.sector || 'Unknown'] || 0) + r.value!
    return Object.entries(m).map(([k, v]) => ({ sector: k, value: v, weight: total ? (v / total) * 100 : 0 })).sort((a, b) => b.value - a.value)
  }, [loaded, total])

  const insights: { tone: 'warn' | 'neg'; text: string }[] = []
  for (const r of loaded) if ((r.weight || 0) > 20) insights.push({ tone: 'warn', text: `${r.s?.name || r.name || r.symbol} is ${r.weight!.toFixed(0)}% of the portfolio (above 20%).` })
  for (const s of sectors) if (s.weight > 35 && loaded.length > 2) insights.push({ tone: 'warn', text: `${s.sector} is ${s.weight.toFixed(0)}% of the portfolio (above 35%).` })
  for (const r of loaded) if (['Elevated', 'High'].includes(r.s?.financial_risk_label)) insights.push({ tone: 'neg', text: `${r.s?.name || r.name || r.symbol}: ${r.s.financial_risk_label.toLowerCase()} financial risk (${r.s.flags_high} high-severity flags).` })
  for (const r of loaded) if (r.s?.valuation_label === 'Potentially overvalued') insights.push({ tone: 'warn', text: `${r.s?.name || r.name || r.symbol}: price is above the estimated fair-value range.` })
  for (const r of loaded) if (r.s?.quarter?.verdict === 'Weak quarter') insights.push({ tone: 'neg', text: `${r.s?.name || r.name || r.symbol}: weak latest quarter (${r.s.quarter.latest}).` })

  const pending = holdings.length - Object.values(sums).filter((x) => x.data || x.error).length

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Portfolio</h1>
          <p className="max-w-2xl text-[13px] text-ink-2">Import your broker's holdings file (Zerodha Console, Groww or any CSV/Excel with symbol or name, quantity and average price) to see every holding through the three verdicts. Stored only on this computer.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Segmented label="Import mode" value={mode} onChange={setMode} options={[{ value: 'replace', label: 'Replace' }, { value: 'merge', label: 'Merge' }]} />
          <button onClick={() => file.current?.click()} disabled={imp.isPending}
            className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white disabled:opacity-60">
            {imp.isPending ? <Loader2 size={15} className="animate-spin" aria-hidden /> : <FileUp size={15} aria-hidden />} Import holdings
          </button>
          <input ref={file} type="file" className="sr-only" aria-label="Holdings file" onChange={(e) => { const f = e.target.files?.[0]; if (f) imp.mutate(f); e.target.value = '' }} />
        </div>
      </div>

      {imp.isError && <p role="alert" className="text-sm text-neg">{(imp.error as Error).message}</p>}
      {imp.data && (
        <div className="rounded-lg border border-line bg-surface p-3 text-[13px]">
          <b>{imp.data.added.length} holding(s) imported.</b>
          {imp.data.added.some((x: any) => x.note) && <span className="text-muted"> Matched by name: {imp.data.added.filter((x: any) => x.note).map((x: any) => `${x.from} → ${x.symbol}`).join('; ')}. Check these.</span>}
          {imp.data.unresolved.length > 0 && <p className="mt-1 text-warn">Not matched ({imp.data.unresolved.length}): {imp.data.unresolved.map((u: any) => `${u.name} (${u.reason})`).join('; ')}. Add them manually below with the NSE symbol.</p>}
        </div>
      )}

      {q.isLoading ? <Skeleton className="h-40" /> : q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : holdings.length === 0 ? (
        <EmptyState title="No holdings yet">Import your broker's holdings export above, or add a holding below.</EmptyState>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            <MetricTile label="Current value" value={money(total)} sub={pending > 0 ? `${pending} still loading` : `${holdings.length} holdings · delayed prices`} />
            <MetricTile label="Invested" value={invested ? money(invested) : '—'} sub="quantity × average cost" />
            <MetricTile label="Overall P&L" value={invested ? money(total - invested) : '—'} sub={invested ? pct((total / invested - 1) * 100, 1, true) : ''}
              tone={invested ? (total >= invested ? 'pos' : 'neg') : undefined} />
            <MetricTile label="Today" value={money(day)} sub="from day change" tone={day >= 0 ? 'pos' : 'neg'} />
            <MetricTile label="Weighted business quality" value={isNum(wQuality) ? `${wQuality.toFixed(0)}/100` : '—'} sub="by current value" />
            <MetricTile label="In elevated/high risk" value={total ? pct((riskyValue / total) * 100, 0) : '—'} sub="share of value" tone={riskyValue > 0 ? 'warn' : undefined} />
          </div>

          <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
            <Card title="Holdings" actions={<label className="text-xs text-muted">Sort{' '}
              <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)} className="ml-1 rounded-md border border-line bg-surface px-2 py-1 text-xs text-ink">
                <option value="value">Value</option><option value="weight">Weight</option><option value="pnl_pct">P&amp;L %</option>
                <option value="business_quality">Business quality</option><option value="financial_risk">Financial risk</option></select></label>}>
              <div className="scroll-x">
                <table className="w-full min-w-[860px] text-[13px]">
                  <thead><tr className="border-b border-line text-left text-muted">
                    <th className="py-2 font-medium">Company</th><th className="py-2 pl-4 text-right font-medium">Qty</th><th className="py-2 pl-4 text-right font-medium">Avg / LTP</th>
                    <th className="py-2 pl-4 text-right font-medium">Value</th><th className="py-2 pl-4 text-right font-medium">P&amp;L</th><th className="py-2 pl-4 text-right font-medium">Weight</th>
                    <th className="py-2 pl-4 font-medium">Quality</th><th className="py-2 font-medium">Risk</th><th className="py-2 font-medium">Valuation</th><th /></tr></thead>
                  <tbody>
                    {rows.map((r: any) => {
                      const st = sums[r.symbol]
                      return (
                        <tr key={r.symbol} className="border-b border-line/60 align-top">
                          <td className="py-2"><Link to={`/c/${r.symbol}`} className="font-medium hover:text-accent">{r.s?.name || r.name || r.symbol}</Link>
                            <span className="block text-[11px] text-muted">{r.symbol}{r.s?.sector ? ` · ${r.s.sector}` : ''}</span></td>
                          <td className="num py-2 pl-4 text-right">{r.quantity.toLocaleString('en-IN')}</td>
                          <td className="num py-2 pl-4 text-right">{price(r.avg_cost)}<span className="block text-[11px] text-muted">{price(r.s?.price)}</span></td>
                          <td className="num py-2 pl-4 text-right">{money(r.value)}</td>
                          <td className={cx('num py-2 pl-4 text-right', isNum(r.pnl) && (r.pnl >= 0 ? 'text-pos' : 'text-neg'))}>{isNum(r.pnl) ? money(r.pnl) : '—'}<span className="block text-[11px]">{pct(r.pnl_pct, 1, true)}</span></td>
                          <td className="num py-2 pl-4 text-right">{pct(r.weight, 1)}</td>
                          {st?.error ? <td colSpan={3} className="py-2 pl-4 text-xs text-warn">{st.error}</td> : !r.s ? (
                            <td colSpan={3} className="py-2 pl-4 text-xs text-muted"><Loader2 size={12} className="mr-1 inline animate-spin" aria-hidden />analysing…</td>
                          ) : (
                            <>
                              <td className="w-28 py-2 pl-4"><span className="num text-xs">{isNum(r.s.business_quality) ? r.s.business_quality.toFixed(0) : '—'} · {r.s.business_quality_label}</span><ScoreBar score={r.s.business_quality} label="Business quality" /></td>
                              <td className="py-2 text-xs">{r.s.financial_risk_label}{r.s.flags_high > 0 && <span className="block text-neg">{r.s.flags_high} high flag(s)</span>}</td>
                              <td className="py-2 text-xs">{r.s.valuation_label}</td>
                            </>
                          )}
                          <td className="py-2 text-right"><button aria-label={`Remove ${r.symbol}`} onClick={() => rm.mutate(r.symbol)} className="p-1 text-muted hover:text-neg"><Trash2 size={14} /></button></td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </Card>
            <div className="space-y-4">
              <Card title="Sector allocation">
                {sectors.length === 0 ? <p className="text-sm text-muted">Waiting for prices…</p> : (
                  <ul className="space-y-2" aria-label="Sector allocation">
                    {sectors.map((s) => (
                      <li key={s.sector} className="text-xs">
                        <div className="flex justify-between"><span className="text-ink-2">{s.sector}</span><span className="num font-medium">{pct(s.weight, 1)}</span></div>
                        <div className="mt-1 h-2 rounded-full bg-surface-2"><div className="h-2 rounded-full" style={{ width: `${Math.max(2, s.weight)}%`, background: 'var(--series-1)' }} /></div>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
              <Card title="Things to look at">
                {insights.length === 0 ? <p className="text-sm text-muted">{pending > 0 ? 'Analysing holdings…' : 'No concentration or risk warnings.'}</p> : (
                  <ul className="space-y-1.5">{insights.map((x, i) => (
                    <li key={i} className="flex gap-2 text-[13px]"><AlertTriangle size={14} className="mt-0.5 shrink-0" style={{ color: x.tone === 'neg' ? 'var(--status-critical)' : 'var(--status-serious)' }} aria-hidden />{x.text}</li>))}</ul>
                )}
                <p className="mt-2 text-[11px] text-muted">Rules of thumb, not advice: single holding above 20%, sector above 35%, elevated/high financial risk, price above fair-value range, weak latest quarter.</p>
              </Card>
            </div>
          </div>
        </>
      )}

      <Card title={<span className="inline-flex items-center gap-2"><Plus size={16} aria-hidden /> Add or update a holding</span>}>
        <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); if (add.symbol && Number(add.qty) > 0) addM.mutate() }}>
          <div className="w-full sm:w-72"><span className="mb-1 block text-xs text-ink-2">Company {add.symbol && <Badge tone="accent">{add.symbol}</Badge>}</span>
            <SearchBox placeholder="Search to pick a company…" onSelect={(s) => setAdd({ ...add, symbol: s })} /></div>
          <label className="block text-xs"><span className="text-ink-2">Quantity</span>
            <input type="number" min={0} step="any" value={add.qty} onChange={(e) => setAdd({ ...add, qty: e.target.value })} className="num mt-1 block w-28 rounded-lg border border-line bg-surface px-2 py-1.5 text-sm" /></label>
          <label className="block text-xs"><span className="text-ink-2">Average cost (₹)</span>
            <input type="number" min={0} step="any" value={add.avg} onChange={(e) => setAdd({ ...add, avg: e.target.value })} className="num mt-1 block w-32 rounded-lg border border-line bg-surface px-2 py-1.5 text-sm" /></label>
          <button type="submit" disabled={!add.symbol || !(Number(add.qty) > 0) || addM.isPending} className="rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white disabled:opacity-50">Save holding</button>
          {addM.isError && <span className="text-sm text-neg">{(addM.error as Error).message}</span>}
        </form>
      </Card>
    </div>
  )
}
