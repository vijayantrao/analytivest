import { useQuery } from '@tanstack/react-query'
import { Card, ErrorState, PageSkeleton, Segmented } from '../components/ui'
import { api } from '../lib/api'
import { useState } from 'react'

const CAT: Record<string, string> = {
  growth: 'Growth', profitability: 'Profitability', balance_sheet: 'Balance sheet & debt', cash_flow: 'Cash flow & earnings quality',
  valuation: 'Valuation', governance: 'Governance & management', industry: 'Industry position', asset_quality: 'Asset quality',
}

export default function Methodology() {
  const q = useQuery({ queryKey: ['methodology'], queryFn: api.methodology, staleTime: Infinity })
  const [model, setModel] = useState<'standard' | 'financial'>('standard')
  if (q.isLoading) return <PageSkeleton />
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />
  const { scoring: s, metrics, principles } = q.data
  const r = s.risk
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Methodology</h1>
        <p className="max-w-3xl text-[13px] text-ink-2">Every score in Analytivest comes from the rules on this page, read live from <code>backend/app/engine/scoring_config.json</code>. {s.notes}</p>
      </div>
      <Card title="Principles">
        <ul className="list-disc space-y-1 pl-5 text-[13px] text-ink-2">{principles.map((p: string, i: number) => <li key={i}>{p}</li>)}</ul>
      </Card>
      <Card title="Three verdicts" subtitle="Kept separate on purpose: a high-quality business can be an expensive stock.">
        <ul className="space-y-2 text-[13px] text-ink-2">
          <li><b className="text-ink">Business quality</b> (0–100): weighted average of category scores. Standard weights: {Object.entries(s.business_quality_weights.standard).map(([k, v]) => `${CAT[k]} ${v}`).join(', ')}. Financial-sector weights: {Object.entries(s.business_quality_weights.financial).map(([k, v]) => `${CAT[k]} ${v}`).join(', ')}. Needs growth and profitability to be scored.</li>
          <li><b className="text-ink">Financial risk</b> (0–100, higher = riskier) = {r.base_share} × (100 − resilience) + red-flag points (high {r.flag_points.high}, medium {r.flag_points.medium}, low {r.flag_points.low}; capped at {r.flag_points_cap}). Resilience weights: {Object.entries(r.resilience_weights.standard).map(([k, v]) => `${CAT[k]} ${v}`).join(', ')}. Labels: {r.labels.map((l: any) => `<${l[0]} ${l[1]}`).join(', ')}.</li>
          <li><b className="text-ink">Valuation</b>: the label comes from where the price sits against the fair-value range (DCF, peer multiples, DDM, justified P/B; at least two methods). The attractiveness score uses the category rules below.</li>
          <li><b className="text-ink">Decision-support label</b>: “Insufficient evidence” if completeness &lt; 50% or business quality cannot be scored; “Elevated financial risk” if risk ≥ 55; “Strong fundamentals” if quality ≥ 70 and risk &lt; 35 and valuation not stretched; “Fundamentally sound, valuation needs scrutiny” if quality is good but valuation is unattractive; otherwise “Mixed financial picture”.</li>
          <li><b className="text-ink">Confidence</b> starts at 100, then loses 0.6 × (100 − completeness), 15 for under 4 years of data, 10 for stale data, and points for provider discrepancies or widely disagreeing valuation methods.</li>
        </ul>
      </Card>
      <Card title="Composite weights (out of 100)" actions={<Segmented label="Model" value={model} onChange={setModel} options={[{ value: 'standard', label: 'Standard' }, { value: 'financial', label: 'Banks / financials' }]} />}>
        <div className="flex flex-wrap gap-2 text-[13px]">
          {Object.entries(s.composite_weights[model]).map(([k, v]: any) => <span key={k} className="rounded-lg bg-surface-2 px-3 py-1.5">{CAT[k]} <b className="num">{v}</b></span>)}
        </div>
      </Card>
      {Object.entries(s.categories[model]).map(([cat, rules]: any) => (
        <Card key={cat} title={CAT[cat] || cat}>
          <div className="scroll-x">
            <table className="w-full min-w-[560px] text-[13px]">
              <thead><tr className="border-b border-line text-left text-muted"><th className="py-1.5 font-medium">Input</th><th className="py-1.5 text-right font-medium">Weight</th><th className="py-1.5 pl-4 font-medium">Scoring points (input → score, linear between)</th></tr></thead>
              <tbody>{rules.map((r: any) => (
                <tr key={r.key} className="border-b border-line/60"><td className="py-1.5 text-ink-2">{r.label}</td><td className="num py-1.5 text-right">{r.weight}</td>
                  <td className="num py-1.5 pl-4 text-xs text-muted">{r.points.map((p: number[]) => `${p[0]} → ${p[1]}`).join(' · ')}</td></tr>))}</tbody>
            </table>
          </div>
        </Card>
      ))}
      <Card title="Sector profiles" subtitle="Adjust leverage thresholds for industries where debt is normal">
        <ul className="space-y-1 text-[13px] text-ink-2">
          {Object.entries(s.profiles).map(([k, p]: any) => (
            <li key={k}><b className="text-ink">{k}</b>: leverage tolerance {p.leverage_tolerance}×; D/E flags at {p.de_medium}×/{p.de_high}×; net debt/EBITDA flags at {p.nd_ebitda_medium}×/{p.nd_ebitda_high}×{p.description ? `. ${p.description}` : ''}{p.match_industries ? ` Industries: ${p.match_industries.join(', ')}.` : ''}</li>
          ))}
        </ul>
      </Card>
      <Card title="Metric formulas">
        <div className="scroll-x">
          <table className="w-full min-w-[560px] text-[13px]">
            <tbody>{Object.entries(metrics).map(([k, m]: any) => (
              <tr key={k} className="border-b border-line/60"><td className="py-1.5 pr-4 font-medium text-ink">{m.label}</td><td className="py-1.5 text-ink-2">{m.formula}</td></tr>))}</tbody>
          </table>
        </div>
        <p className="mt-3 text-xs text-muted">YoY growth and CAGR are blank when the base is zero or negative. ROE/ROCE/ROIC use averages of opening and closing balances (closing only when the prior year is missing, noted). Historical per-share data is restated for later splits and bonus issues. Quarterly growth compares with the same quarter a year earlier. TTM figures are only built from four consecutive quarters.</p>
      </Card>
    </div>
  )
}
