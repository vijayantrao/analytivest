import { useMutation } from '@tanstack/react-query'
import { RotateCcw } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { PeBandChart, SeriesChart } from '../../components/charts'
import { Badge, Card, EmptyState, Provenance, Term, Tip, cx } from '../../components/ui'
import { api } from '../../lib/api'
import { byUnit, dateTime, isNum, pct, price } from '../../lib/format'
import { FairValueBar } from './Overview'
import { type A, FinancialNotice } from './shared'

const ORDER = ['price', 'market_cap', 'enterprise_value', 'pe', 'pe_ttm', 'forward_pe', 'pb', 'ps', 'ev_ebitda', 'ev_ebit',
  'earnings_yield', 'fcf_yield', 'dps_ttm', 'dividend_yield', 'peg']
const TERM: Record<string, string> = { pe: 'pe', pe_ttm: 'pe', pb: 'pb', ev_ebitda: 'ev_ebitda', enterprise_value: 'ev', peg: 'peg', dividend_yield: 'dividend_yield' }

function Multiples({ a }: { a: A }) {
  const m = a.valuation.multiples
  const cur = a.quote.currency
  return (
    <Card title="Valuation multiples" subtitle="Each value shows its basis period; hover ⓘ for the formula and data type.">
      <div className="scroll-x">
        <table className="w-full text-[13px]">
          <thead><tr className="border-b border-line text-left text-muted">
            <th className="py-2 font-medium">Measure</th><th className="py-2 text-right font-medium">Value</th>
            <th className="hidden py-2 pl-4 font-medium sm:table-cell">Basis</th><th className="py-2 pl-2 font-medium">Type</th></tr></thead>
          <tbody>
            {ORDER.filter((k) => m[k]).map((k) => {
              const x = m[k]
              return (
                <tr key={k} className="border-b border-line/60">
                  <td className="py-2 text-ink-2">{TERM[k] ? <Term k={TERM[k]}>{x.label}</Term> : x.label}</td>
                  <td className="num py-2 text-right font-medium">
                    {x.value == null ? <span className="text-muted" title={x.reason}>{x.status === 'not_meaningful' ? 'n/m' : '—'}</span>
                      : k === 'price' || k === 'dps_ttm' ? price(x.value, cur) : byUnit(x.value, x.unit, cur)}
                    {' '}<Provenance method={x.formula} period={x.basis} quality={x.quality} source={a.source_label} reason={x.reason || x.caveat} />
                  </td>
                  <td className="hidden py-2 pl-4 text-xs text-muted sm:table-cell">{x.value == null ? x.reason : k === 'price' ? `${dateTime(x.basis)} (delayed)` : x.basis}</td>
                  <td className="py-2 pl-2">
                    <Badge tone={x.quality === 'provider_estimate' ? 'warn' : x.quality === 'provider_reported' ? 'accent' : 'neutral'}>
                      {x.quality === 'provider_estimate' ? 'estimate' : x.quality === 'provider_reported' ? 'provider' : x.quality}
                    </Badge>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

function NumInput({ label, value, onChange, step = 0.5, min, max, suffix, hint }: {
  label: string; value: number; onChange: (v: number) => void; step?: number; min?: number; max?: number; suffix?: string; hint?: string
}) {
  return (
    <label className="block text-xs">
      <span className="text-ink-2">{label}</span>
      <span className="mt-1 flex items-center rounded-lg border border-line bg-surface focus-within:border-accent">
        <input type="number" value={Number.isFinite(value) ? value : ''} step={step} min={min} max={max}
          onChange={(e) => onChange(parseFloat(e.target.value))}
          className="num w-full bg-transparent px-2 py-1.5 text-sm outline-none" />
        {suffix && <span className="pr-2 text-muted">{suffix}</span>}
      </span>
      {hint && <span className="mt-0.5 block text-[11px] text-muted">{hint}</span>}
    </label>
  )
}

function Dcf({ a }: { a: A }) {
  const base = a.valuation.dcf
  const cur = a.quote.currency
  const div = cur === 'INR' ? 1e7 : 1e6
  const unit = cur === 'INR' ? '₹ Cr' : `${cur} M`
  const [inp, setInp] = useState(() => base.applicable ? {
    growth: +base.assumptions.growth.toFixed(1), discount: base.assumptions.discount, terminal: base.assumptions.terminal,
    years: base.assumptions.years, fade_years: base.assumptions.fade_years, base_fcf: Math.round(base.assumptions.base_fcf / div),
  } : null)
  const [res, setRes] = useState<any>(base)
  const mut = useMutation({ mutationFn: (body: any) => api.dcf(a.symbol, body), onSuccess: (d) => setRes(d.dcf) })
  const first = useRef(true)
  useEffect(() => {
    if (!inp) return
    if (first.current) { first.current = false; return }
    const valid = Object.values(inp).every((v) => Number.isFinite(v))
    if (!valid) return
    const t = setTimeout(() => mut.mutate({ ...inp, base_fcf: inp.base_fcf * div }), 400)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inp])

  if (!base.applicable) {
    return (
      <Card title={<Term k="dcf">Discounted cash flow (DCF)</Term>}>
        <EmptyState title="DCF not applicable">{base.reason}</EmptyState>
      </Card>
    )
  }
  const d = base.defaults
  const r = res?.result || base.result
  const sens = res?.sensitivity || base.sensitivity
  const set = (k: string) => (v: number) => setInp((s: any) => ({ ...s, [k]: v }))
  const p = a.quote.price
  return (
    <Card title={<Term k="dcf">Discounted cash flow (DCF)</Term>} subtitle="Edit the assumptions; the value recalculates on the server. This is an estimate under assumptions, not a price target."
      actions={<button onClick={() => setInp({ growth: +d.growth.toFixed(1), discount: d.discount, terminal: d.terminal, years: d.years, fade_years: d.fade_years, base_fcf: Math.round(d.base_fcf / div) })}
        className="inline-flex items-center gap-1 rounded-md border border-line px-2 py-1 text-xs text-muted hover:text-ink"><RotateCcw size={12} aria-hidden /> Reset</button>}>
      <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-1">
          <NumInput label={`Base free cash flow (${unit})`} value={inp!.base_fcf} onChange={set('base_fcf')} step={10} hint={base.assumption_notes.base_fcf} />
          <NumInput label="Growth, stage 1" value={inp!.growth} onChange={set('growth')} suffix="%/yr" min={-20} max={50} hint={base.assumption_notes.growth} />
          <NumInput label="Stage-1 years" value={inp!.years} onChange={set('years')} step={1} min={1} max={15} />
          <NumInput label="Fade-to-terminal years" value={inp!.fade_years} onChange={set('fade_years')} step={1} min={1} max={15} />
          <NumInput label="Discount rate" value={inp!.discount} onChange={set('discount')} suffix="%" min={4} max={30} hint={base.assumption_notes.discount} />
          <NumInput label="Terminal growth" value={inp!.terminal} onChange={set('terminal')} suffix="%" min={-2} max={10} hint={base.assumption_notes.terminal} />
        </div>
        <div className="min-w-0 space-y-4">
          {mut.isError && <p className="text-sm text-neg">{(mut.error as Error).message}</p>}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div className="rounded-lg bg-surface-2 p-3">
              <div className="text-xs text-muted">Value per share</div>
              <div className={cx('num text-xl font-semibold', mut.isPending && 'opacity-50')}>{r?.value_per_share != null ? price(r.value_per_share, cur) : '—'}</div>
              {r?.value_per_share != null && isNum(p) && <div className="text-xs text-muted">{pct((r.value_per_share / p - 1) * 100, 0, true)} vs price</div>}
            </div>
            <div className="rounded-lg bg-surface-2 p-3"><div className="text-xs text-muted">Enterprise value</div><div className="num text-base font-semibold">{byUnit(r?.enterprise_value, 'currency', cur)}</div></div>
            <div className="rounded-lg bg-surface-2 p-3"><div className="text-xs text-muted">Less net debt + minorities</div><div className="num text-base font-semibold">{byUnit(base.net_debt_used, 'currency', cur)}</div></div>
            <div className="rounded-lg bg-surface-2 p-3"><div className="text-xs text-muted">Terminal value share</div><div className="num text-base font-semibold">{pct(r?.terminal_share_pct, 0)}</div></div>
          </div>
          <div>
            <h3 className="mb-1 text-[13px] font-semibold">Sensitivity: value per share</h3>
            <p className="mb-2 text-xs text-muted">Rows: discount rate. Columns: terminal growth. The centre cell is your current assumption.</p>
            <div className="scroll-x">
              <table className="text-xs">
                <thead><tr><th className="px-2 py-1 text-left text-muted">r \ g</th>
                  {sens.terminal_growths.map((g: number) => <th key={g} className="num px-2 py-1 text-right text-muted">{g.toFixed(1)}%</th>)}</tr></thead>
                <tbody>
                  {sens.discount_rates.map((dr: number, i: number) => (
                    <tr key={dr}>
                      <th className="num px-2 py-1 text-left font-normal text-muted">{dr.toFixed(1)}%</th>
                      {sens.values[i].map((v: number | null, j: number) => (
                        <td key={j} className={cx('num px-2 py-1 text-right', i === 2 && j === 2 && 'rounded bg-accent-soft font-semibold text-accent-ink',
                          isNum(v) && isNum(p) && (v > p ? 'text-ink' : 'text-muted'))}>
                          {isNum(v) ? price(v, cur).replace('.00', '') : 'n/a'}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-1 text-[11px] text-muted">Values above today’s price ({price(p, cur)}) in darker text.</p>
          </div>
          <div>
            <h3 className="mb-1 text-[13px] font-semibold">Limitations</h3>
            <ul className="list-disc space-y-0.5 pl-5 text-xs text-ink-2">{(res?.limitations || base.limitations).map((l: string, i: number) => <li key={i}>{l}</li>)}</ul>
          </div>
        </div>
      </div>
    </Card>
  )
}

const FAMILY_LABELS: Record<string, string> = { cash_flow: 'cash-flow model', peers: 'peer multiples', history: 'own history' }

export default function Valuation({ a }: { a: A }) {
  const v = a.valuation
  const cur = a.quote.currency
  const fv = v.fair_value
  const fyRows = (v.history.fiscal_year_end || []).map((r: any) => ({ label: r.period, pe: r.pe, pb: r.pb }))
  return (
    <div className="space-y-4">
      <FinancialNotice a={a} />
      <Card title="Estimated fair-value range" subtitle="Combines the applicable methods below. A range under stated assumptions, never a certain price.">
        <div className="grid gap-4 lg:grid-cols-2">
          <div>
            <p className="text-lg font-semibold">{fv.label}</p>
            {fv.reason && <p className="text-xs text-warn">{fv.reason}</p>}
            <FairValueBar fv={fv} priceNow={a.quote.price} currency={cur} />
          </div>
          <div>
            <table className="w-full text-[13px]">
              <thead><tr className="border-b border-line text-left text-muted"><th className="py-1.5 font-medium">Method</th><th className="py-1.5 text-right font-medium">Value / share</th><th className="py-1.5 text-right font-medium">vs price</th></tr></thead>
              <tbody>
                {v.estimates.length === 0 && <tr><td colSpan={3} className="py-2 text-muted">No method was applicable with the available data.</td></tr>}
                {v.estimates.map((e: any, i: number) => (
                  <tr key={i} className="border-b border-line/60">
                    <td className="py-1.5 text-ink-2">{e.method}{e.inputs && <Tip content={e.inputs} />}
                      {e.family && <span className="ml-1.5 text-[11px] text-muted">· {FAMILY_LABELS[e.family] ?? e.family}</span>}</td>
                    <td className="num py-1.5 text-right">{price(e.value_per_share, cur)}</td>
                    <td className="num py-1.5 text-right text-muted">{isNum(a.quote.price) ? pct((e.value_per_share / a.quote.price - 1) * 100, 0, true) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-[11px] text-muted">Methods of the same kind (e.g. the peer multiples, which share one set of peers) are first reduced to their median, so each independent view counts once. Range = lowest to highest of those views (interquartile range when there are 4 or more). Needs at least 2 kinds{isNum(fv.n_families) ? ` — ${fv.n_families} used here` : ''}.</p>
          </div>
        </div>
      </Card>
      <div className="grid gap-4 xl:grid-cols-2">
        <Multiples a={a} />
        <div className="space-y-4">
          <PeBandChart band={v.history.pe_band} stats={v.history.pe_stats} currentPe={v.multiples.pe.value} />
          <SeriesChart title="Multiples at fiscal year-end" subtitle="Year-end price ÷ that year’s EPS and book value per share" rows={fyRows}
            series={[{ key: 'pe', name: 'P/E', type: 'line', color: 's1' }, { key: 'pb', name: 'P/B', type: 'line', color: 's2' }]}
            fmt={(x) => (isNum(x) ? `${x.toFixed(1)}×` : '—')} />
        </div>
      </div>
      <Dcf a={a} />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Peer comparables">
          {v.comps.methods.length === 0 ? <p className="text-sm text-muted">Needs at least 3 peers with valid multiples (see the Peers tab).</p> : (
            <ul className="space-y-2 text-[13px]">{v.comps.methods.map((m: any, i: number) => (
              <li key={i}><b>{m.method}</b>: {price(m.value_per_share, cur)}<span className="block text-xs text-muted">{m.inputs}</span></li>))}</ul>
          )}
          <ul className="mt-2 list-disc pl-5 text-xs text-muted">{v.comps.limitations.map((l: string, i: number) => <li key={i}>{l}</li>)}</ul>
        </Card>
        <Card title={<Term k="ddm">Dividend discount model</Term>}>
          {!v.ddm.applicable ? <p className="text-sm text-muted">Not applicable: {v.ddm.reason}.</p> : (
            <div className="text-[13px]">
              <p><b>{price(v.ddm.value_per_share, cur)}</b> per share</p>
              <p className="text-xs text-muted">{v.ddm.formula}; D₀ {price(v.ddm.assumptions.d0, cur)}, g {v.ddm.assumptions.growth}%, kₑ {v.ddm.assumptions.cost_of_equity}%</p>
              {v.ddm.low_payout_warning && <p className="mt-1 text-xs text-warn">Payout below 30%: excluded from the fair-value range because dividends understate earning power.</p>}
              <p className="mt-1 text-xs text-muted">{v.ddm.limitations[0]}</p>
            </div>
          )}
        </Card>
        <Card title="Justified P/B">
          {!v.justified_pb.applicable ? <p className="text-sm text-muted">Not applicable: {v.justified_pb.reason}.</p> : (
            <div className="text-[13px]">
              <p>Justified P/B <b>{v.justified_pb.justified_pb.toFixed(2)}×</b> → {price(v.justified_pb.value_per_share, cur)}</p>
              <p className="text-xs text-muted">{v.justified_pb.formula}; avg ROE {v.justified_pb.assumptions.avg_roe.toFixed(1)}%, kₑ {v.justified_pb.assumptions.cost_of_equity}%, g {v.justified_pb.assumptions.growth}%</p>
              <p className="mt-1 text-xs text-muted">{a.metrics.is_financial ? 'Used in the fair-value range for financial companies.' : 'Shown for reference; the range uses DCF and comparables for non-financial companies.'}</p>
            </div>
          )}
        </Card>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Reconciliation with provider-reported figures" subtitle="Independent calculations vs the provider’s own numbers. Differences above 10% are flagged.">
          {v.reconciliation.length === 0 ? <p className="text-sm text-muted">No provider figures available to compare.</p> : (
            <table className="w-full text-[13px]">
              <thead><tr className="border-b border-line text-left text-muted"><th className="py-1.5 font-medium">Metric</th><th className="py-1.5 text-right font-medium">Calculated</th><th className="py-1.5 text-right font-medium">Provider</th><th className="py-1.5 text-right font-medium">Diff</th></tr></thead>
              <tbody>{v.reconciliation.map((r: any) => (
                <tr key={r.metric} className="border-b border-line/60">
                  <td className="py-1.5">{r.metric}{r.explanation && <Tip content={r.explanation} />}</td>
                  <td className="num py-1.5 text-right">{r.metric.includes('cap') || r.metric.includes('value') ? byUnit(r.calculated, 'currency', cur) : r.calculated.toFixed(2)}</td>
                  <td className="num py-1.5 text-right">{r.metric.includes('cap') || r.metric.includes('value') ? byUnit(r.provider, 'currency', cur) : r.provider.toFixed(2)}</td>
                  <td className={cx('num py-1.5 text-right', r.flag && 'font-semibold text-warn')}>{r.flag ? '⚠ ' : ''}{pct(r.diff_pct, 1, true)}</td>
                </tr>))}</tbody>
            </table>
          )}
        </Card>
        <Card title={<Term k="tsr">Shareholder returns</Term>} subtitle="Price return vs total return including dividends (adjusted close)">
          <table className="w-full text-[13px]">
            <thead><tr className="border-b border-line text-left text-muted"><th className="py-1.5 font-medium">Period</th><th className="py-1.5 text-right font-medium">Price return</th><th className="py-1.5 text-right font-medium">Total return</th><th className="py-1.5 text-right font-medium">TSR / yr</th></tr></thead>
            <tbody>{['1y', '3y', '5y', '10y'].map((k) => {
              const r = a.returns?.[k]
              return (
                <tr key={k} className="border-b border-line/60">
                  <td className="py-1.5">{k.toUpperCase()}</td>
                  <td className="num py-1.5 text-right">{r ? pct(r.price_return_pct, 1, true) : '—'}</td>
                  <td className="num py-1.5 text-right">{r ? pct(r.tsr_pct, 1, true) : '—'}</td>
                  <td className="num py-1.5 text-right">{r ? pct(r.tsr_cagr_pct, 1, true) : '—'}</td>
                </tr>)
            })}</tbody>
          </table>
          <p className="mt-2 text-xs text-muted">Splits and bonus issues are adjusted out of prices, so they never show up as returns. Last price {dateTime(a.quote.market_time)}.</p>
        </Card>
      </div>
      <SeriesChart title="Dividend per share by fiscal year" subtitle={`${cur}; ex-dates within each fiscal year`}
        rows={(a.dividends.per_fy || []).map((d: any) => ({ label: d.period, dps: d.dps }))}
        series={[{ key: 'dps', name: 'DPS', type: 'bar', color: 's1' }]} fmt={(x) => (isNum(x) ? x.toFixed(2) : '—')}
        emptyText="No dividends recorded in these years." />
    </div>
  )
}
