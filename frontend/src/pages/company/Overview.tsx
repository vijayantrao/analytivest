import { ChevronDown, Minus, Plus } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { PriceChart, SeriesChart } from '../../components/charts'
import { Badge, Card, GoodIcon, MetricTile, ScoreBar, Severity, cx } from '../../components/ui'
import { byUnit, dateTime, isNum, pct, price } from '../../lib/format'
import { QuarterlyCard } from './Extras'
import { type A, FinancialNotice, MetricValue, latest, rowsFrom, scaleFor } from './shared'

const CAT_LABEL: Record<string, string> = {
  growth: 'Growth', profitability: 'Profitability', balance_sheet: 'Balance sheet', cash_flow: 'Cash flow & earnings quality',
  valuation: 'Valuation', governance: 'Governance', industry: 'Industry position', asset_quality: 'Asset quality',
}

function Why({ a, cats }: { a: A; cats: string[] }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="mt-3">
      <button onClick={() => setOpen((o) => !o)} aria-expanded={open} className="inline-flex items-center gap-1 text-xs font-medium text-accent">
        Why this score <ChevronDown size={14} className={cx('transition-transform', open && 'rotate-180')} aria-hidden />
      </button>
      {open && (
        <ul className="mt-2 space-y-1.5">
          {cats.map((c) => {
            const cat = a.scores.categories[c]
            if (!cat) return null
            return (
              <li key={c} className="text-xs">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-ink-2">{CAT_LABEL[c] || c}</span>
                  <span className="num font-medium text-ink">{cat.score != null ? `${cat.score.toFixed(0)}/100` : cat.not_applicable ? 'n/a' : 'insufficient data'}</span>
                </div>
                <ScoreBar score={cat.score} label={`${CAT_LABEL[c]} score`} />
              </li>
            )
          })}
          <li><Link to={`/c/${a.symbol}/analysis`} className="text-xs text-accent underline">Full breakdown with inputs and thresholds</Link></li>
        </ul>
      )}
    </div>
  )
}

export function FairValueBar({ fv, priceNow, currency }: { fv: any; priceNow: number; currency: string }) {
  if (!fv?.low || !isNum(priceNow)) {
    return <p className="text-xs text-muted">{fv?.reason || 'Fair-value range not available.'}</p>
  }
  const lo = Math.min(fv.low, priceNow) * 0.85
  const hi = Math.max(fv.high, priceNow) * 1.15
  const pos = (v: number) => `${((v - lo) / (hi - lo)) * 100}%`
  const pp = ((priceNow - lo) / (hi - lo)) * 100
  return (
    <div>
      <div className="relative mt-6 h-2 rounded-full bg-surface-2" role="img"
        aria-label={`Estimated range ${price(fv.low, currency)} to ${price(fv.high, currency)}; current price ${price(priceNow, currency)}`}>
        <div className="absolute top-0 h-2 rounded-full" style={{ left: pos(fv.low), width: `calc(${pos(fv.high)} - ${pos(fv.low)})`, background: 'var(--series-1)', opacity: 0.35 }} />
        <div className="absolute -top-1 h-4 w-0.5 bg-ink-2" style={{ left: pos(fv.mid) }} title="Midpoint" />
        <div className={cx('absolute -top-6 whitespace-nowrap text-[11px] font-semibold text-ink', pp < 15 ? '' : pp > 85 ? '-translate-x-full' : '-translate-x-1/2')} style={{ left: pos(priceNow) }}>
          Price {price(priceNow, currency)}
        </div>
        <div className="absolute -top-1.5 h-5 w-5 -translate-x-1/2 rounded-full border-2 bg-ink" style={{ left: pos(priceNow), borderColor: 'var(--surface)' }} />
      </div>
      <div className="num mt-2 flex justify-between text-[11px] text-muted">
        <span>Low {price(fv.low, currency)}</span>
        <span>Mid {price(fv.mid, currency)}</span>
        <span>High {price(fv.high, currency)}</span>
      </div>
    </div>
  )
}

function Verdicts({ a }: { a: A }) {
  const v = a.scores.verdicts
  const fv = a.valuation.fair_value
  const cur = a.quote.currency
  const bqCats = Object.keys(a.scores.verdicts.business_quality.components || {})
  const vt = v.valuation.label
  return (
    <div className="grid gap-4 md:grid-cols-3">
      <Card className="flex flex-col">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted">Business quality</p>
        <p className="mt-0.5 text-xs text-muted">{v.business_quality.question}</p>
        <div className="mt-3 flex items-baseline gap-2">
          <span className="num text-3xl font-semibold">{isNum(v.business_quality.score) ? v.business_quality.score.toFixed(0) : '—'}</span>
          <span className="text-sm text-muted">/ 100</span>
          <span className="ml-auto text-sm font-semibold">{v.business_quality.label}</span>
        </div>
        <div className="mt-2"><ScoreBar score={v.business_quality.score} label="Business quality score" /></div>
        <Why a={a} cats={bqCats} />
      </Card>
      <Card className="flex flex-col">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted">Financial risk</p>
        <p className="mt-0.5 text-xs text-muted">{v.financial_risk.question}</p>
        <div className="mt-3 flex items-baseline gap-2">
          <span className="num text-3xl font-semibold">{isNum(v.financial_risk.score) ? v.financial_risk.score.toFixed(0) : '—'}</span>
          <span className="text-sm text-muted">/ 100 · higher = riskier</span>
          <span className="ml-auto text-sm font-semibold">{v.financial_risk.label}</span>
        </div>
        <div className="mt-2"><ScoreBar score={v.financial_risk.score} invert label="Financial risk score" /></div>
        <p className="mt-2 text-xs text-muted">
          Balance-sheet & cash resilience {isNum(v.financial_risk.resilience) ? `${v.financial_risk.resilience.toFixed(0)}/100` : 'n/a'}; red-flag points +{v.financial_risk.flag_points}.
        </p>
        <Why a={a} cats={a.scores.model === 'financial' ? ['balance_sheet', 'asset_quality'] : ['balance_sheet', 'cash_flow']} />
      </Card>
      <Card className="flex flex-col">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted">Valuation</p>
        <p className="mt-0.5 text-xs text-muted">{v.valuation.question}</p>
        <div className="mt-3 flex items-baseline gap-2">
          <span className="text-lg font-semibold leading-tight">{vt}</span>
        </div>
        <p className="text-xs text-muted">
          Attractiveness score {isNum(v.valuation.score) ? `${v.valuation.score.toFixed(0)}/100 (${v.valuation.score_label})` : 'n/a'} · {fv.n_methods} method(s)
          {fv.wide && ' · wide range'}
        </p>
        <FairValueBar fv={fv} priceNow={a.quote.price} currency={cur} />
        {fv.data_warning && <p className="mt-2 text-xs text-warn">{fv.data_warning}</p>}
        <Link to={`/c/${a.symbol}/valuation`} className="mt-3 text-xs font-medium text-accent">Assumptions & methods →</Link>
      </Card>
    </div>
  )
}

export default function Overview({ a }: { a: A }) {
  const s = a.scores
  const cur = a.quote.currency
  const sc = scaleFor(cur)
  const fin = a.metrics.is_financial
  const flags = a.flags || []
  const g = a.metrics.growth
  const pickCagr = (base: string) => {
    for (const k of [`${base}_3y`, `${base}_max`]) if (isNum(g[k]?.value) && !g[k]?.base_effect) return g[k]
    return null
  }
  const rc = pickCagr(fin ? 'nii_cagr' : 'revenue_cagr')
  const m = a.valuation.multiples
  return (
    <div className="space-y-4">
      <FinancialNotice a={a} />
      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-line bg-surface px-4 py-3">
        <span className="text-xs uppercase tracking-wide text-muted">Summary</span>
        <span className="text-base font-semibold">{s.decision_label}</span>
        <span className="mx-1 hidden h-4 w-px bg-line sm:block" />
        <Badge tone={s.confidence.label === 'High' ? 'pos' : s.confidence.label === 'Medium' ? 'warn' : 'neg'} title={s.confidence.reasons.join('; ')}>
          Confidence: {s.confidence.label}
        </Badge>
        <Badge title="Share of scoring inputs backed by data">Data completeness {s.data_completeness.toFixed(0)}%</Badge>
        <Badge title="Configurable weights incl. valuation; see Methodology">Composite {isNum(s.composite.score) ? `${s.composite.score.toFixed(0)}/100` : 'n/a'}</Badge>
        {s.confidence.reasons.length > 0 && <span className="text-xs text-muted">({s.confidence.reasons.join('; ')})</span>}
      </div>

      <Verdicts a={a} />
      <p className="text-xs text-muted">
        A strong business is not automatically a good purchase: quality, risk and price are separate questions, and suitability depends on your own circumstances.
      </p>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 xl:grid-cols-8">
        <MetricTile label={fin ? 'NII CAGR' : 'Revenue CAGR'} term="cagr" value={rc ? pct(rc.value) : '—'} sub={rc?.period || 'n/a'} />
        <MetricTile label="ROE" term="roe" value={<MetricValue a={a} k="roe" />} sub={latest(a, 'roe').period} />
        {fin ? <MetricTile label="ROA" value={<MetricValue a={a} k="roa" />} sub={latest(a, 'roa').period} />
          : <MetricTile label="ROCE" term="roce" value={<MetricValue a={a} k="roce" />} sub={latest(a, 'roce').period} />}
        {fin ? <MetricTile label="NII / assets" term="nim" value={<MetricValue a={a} k="nim_proxy" />} sub="NIM proxy" />
          : <MetricTile label="Debt / equity" term="debt_to_equity" value={<MetricValue a={a} k="debt_to_equity" />} sub={latest(a, 'debt_to_equity').period} />}
        {fin ? <MetricTile label="Equity / assets" value={<MetricValue a={a} k="equity_to_assets" />} sub="capital proxy" />
          : <MetricTile label="FCF margin" term="fcf" value={<MetricValue a={a} k="fcf_margin" />} sub={latest(a, 'fcf_margin').period} />}
        <MetricTile label="P/E" term="pe" value={byUnit(m.pe.value, 'x')} sub={m.pe.value == null ? (m.pe.reason || 'n/a') : m.pe.basis} />
        <MetricTile label="P/B" term="pb" value={byUnit(m.pb.value, 'x')} sub={m.pb.basis} />
        <MetricTile label="Dividend yield" term="dividend_yield" value={pct(m.dividend_yield.value, 2)} sub="trailing 12 months" />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <PriceChart symbol={a.symbol} currency={cur} />
        <SeriesChart title={fin ? 'Revenue & net profit' : 'Revenue & net profit'} subtitle={`Annual, ${sc.unit}`}
          rows={rowsFrom(a, ['revenue', 'net_income'], { scale: sc.div })}
          series={[{ key: 'revenue', name: 'Revenue', type: 'bar', color: 's1' }, { key: 'net_income', name: 'Net profit', type: 'bar', color: 's2' }]}
          fmt={sc.fmt} axisFmt={sc.axis} />
      </div>

      <QuarterlyCard a={a} compact />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Positive factors" subtitle="Inputs that scored ≥75/100">
          {s.positives.length === 0 ? <p className="text-sm text-muted">No standout strengths in the available data.</p> : (
            <ul className="space-y-2">
              {s.positives.map((p: any, i: number) => (
                <li key={i} className="flex gap-2 text-[13px]">
                  <Plus size={16} className="mt-0.5 shrink-0" style={{ color: 'var(--status-good)' }} aria-label="Positive" />
                  <span><b className="font-medium text-ink">{p.label}:</b> <span className="num">{byUnit(p.input, p.unit, cur)}</span> <span className="text-muted">({p.basis}; scored {p.score.toFixed(0)})</span></span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Major risks" subtitle="Weak inputs (≤30/100) and automated red flags"
          actions={<Link to={`/c/${a.symbol}/risks`} className="text-xs text-accent">All risks →</Link>}>
          {flags.length === 0 && s.negatives.length === 0 ? (
            <p className="flex items-center gap-1.5 text-sm text-ink-2"><GoodIcon /> No red flags triggered by the available data (not proof of absence).</p>
          ) : (
            <ul className="space-y-2">
              {flags.slice(0, 4).map((f: any) => (
                <li key={f.id} className="text-[13px]">
                  <div className="flex items-center gap-2"><Severity level={f.severity} /><span className="font-medium">{f.title}</span></div>
                  <p className="text-muted">{f.evidence}</p>
                </li>
              ))}
              {s.negatives.slice(0, 4).map((p: any, i: number) => (
                <li key={i} className="flex gap-2 text-[13px]">
                  <Minus size={16} className="mt-0.5 shrink-0" style={{ color: 'var(--status-critical)' }} aria-label="Negative" />
                  <span><b className="font-medium text-ink">{p.label}:</b> <span className="num">{byUnit(p.input, p.unit, cur)}</span> <span className="text-muted">({p.basis}; scored {p.score.toFixed(0)})</span></span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      {!fin && (
        <div className="grid gap-4 lg:grid-cols-2">
          <SeriesChart title="Debt vs cash" subtitle={`Gross borrowings (incl. leases) vs cash & short-term investments, ${sc.unit}`}
            rows={rowsFrom(a, ['total_debt', 'cash_and_sti'], { scale: sc.div })}
            series={[{ key: 'total_debt', name: 'Total debt', type: 'bar', color: 's2' }, { key: 'cash_and_sti', name: 'Cash & ST investments', type: 'bar', color: 's1' }]}
            fmt={sc.fmt} axisFmt={sc.axis} />
          <SeriesChart title="Operating cash flow vs net profit" subtitle={`Do profits turn into cash? ${sc.unit}`}
            rows={rowsFrom(a, ['cfo', 'net_income'], { scale: sc.div })}
            series={[{ key: 'cfo', name: 'Cash from operations', type: 'bar', color: 's1' }, { key: 'net_income', name: 'Net profit', type: 'bar', color: 's2' }]}
            fmt={sc.fmt} axisFmt={sc.axis} />
        </div>
      )}

      <Card title="Data sources & freshness">
        <ul className="grid gap-1 text-[13px] text-ink-2 sm:grid-cols-2">
          <li><b className="text-ink">Source:</b> {a.source_label}</li>
          <li><b className="text-ink">Fundamentals retrieved:</b> {dateTime(a.freshness?.retrieved_at)} ({a.freshness?.served_from})</li>
          <li><b className="text-ink">Quote:</b> delayed, exchange time {dateTime(a.quote?.market_time)}</li>
          <li><b className="text-ink">Latest fiscal year:</b> {a.metrics.annual.labels.slice(-1)[0] || 'n/a'} ({a.metrics.years_available} years available)</li>
          <li><b className="text-ink">Model:</b> {a.scores.model === 'financial' ? 'Financial-sector (bank/NBFC/insurer)' : 'Standard'} · sector profile “{a.scores.profile.name}”</li>
          <li><b className="text-ink">Currency:</b> {a.profile.reported_currency ? `reported in ${a.profile.reported_currency}, converted to ${a.profile.financial_currency} at period-end FX rates` : a.profile.financial_currency}; statements in {scaleFor(cur).unit} on charts</li>
        </ul>
        {a.data_quality?.length > 0 && (
          <p className="mt-2 text-xs text-warn">{a.data_quality.length} data-quality note(s). See the Risks & flags tab.</p>
        )}
      </Card>
    </div>
  )
}
