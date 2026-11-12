import { useMutation, useQuery } from '@tanstack/react-query'
import { AlertTriangle, Pencil, Trash2 } from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { SeriesChart } from '../components/charts'
import { Badge, Card, ErrorState, PageSkeleton, SampleBanner, ScoreBar, Term, cx } from '../components/ui'
import { api } from '../lib/api'
import { DecisionCard } from './IpoDecision'
import { isNum, pct, price, ratio, shortDate } from '../lib/format'

const cr = (v: any) => (isNum(v) ? `${v < 0 ? '−' : ''}₹${Math.abs(Math.round(v)).toLocaleString('en-IN')} Cr` : '—')

const ASSESS = [
  ['business_quality', 'Business quality'], ['financial_strength', 'Financial strength'], ['valuation_attractiveness', 'Valuation attractiveness'],
  ['governance_disclosure_risk', 'Governance & disclosure risk'], ['ipo_specific_risk', 'IPO-specific risk'],
] as const

export default function IpoDetail() {
  const { id = '' } = useParams()
  const nav = useNavigate()
  const q = useQuery({ queryKey: ['ipo-analysis', id], queryFn: () => api.ipoAnalysis(id) })
  const del = useMutation({ mutationFn: () => api.ipoDelete(id), onSuccess: () => nav('/ipo') })
  if (q.isLoading) return <PageSkeleton />
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />
  const { input: p, analysis: r, is_sample } = q.data
  if (r.error) return <ErrorState error={new Error(r.error)} />
  const s = r.structure
  const v = r.valuation
  const pe = r.peers
  return (
    <div className="space-y-4">
      {is_sample && <SampleBanner />}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">{p.company_name}</h1>
          <p className="text-[13px] text-muted">{[p.industry, p.exchange, p.open_date && `Opens ${shortDate(p.open_date)}`, p.listing_date && `Listing ${shortDate(p.listing_date)}`].filter(Boolean).join(' · ')}</p>
          {p.source_note && <p className="text-xs text-muted">Source: {p.source_note}</p>}
        </div>
        {!is_sample && (
          <div className="flex gap-2">
            <Link to={`/ipo/${id}/edit`} className="inline-flex items-center gap-1 rounded-lg border border-line px-2.5 py-1.5 text-xs"><Pencil size={13} aria-hidden /> Edit</Link>
            <button onClick={() => { if (confirm('Delete this IPO record?')) del.mutate() }} className="inline-flex items-center gap-1 rounded-lg border border-line px-2.5 py-1.5 text-xs text-neg"><Trash2 size={13} aria-hidden /> Delete</button>
          </div>
        )}
      </div>

      <DecisionCard d={r.decision} upperBand={s.price_band?.[1]} extraction={p.extraction} editHref={is_sample ? undefined : `/ipo/${id}/edit`} />

      {r.warnings.length > 0 && (
        <div className="space-y-1.5">
          {r.warnings.map((w: string, i: number) => (
            <div key={i} role="note" className="flex items-start gap-2 rounded-lg border border-line bg-surface px-3 py-2 text-[13px] text-ink-2">
              <AlertTriangle size={15} className="mt-0.5 shrink-0" style={{ color: 'var(--status-serious)' }} aria-hidden /> {w}
            </div>
          ))}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Issue structure" subtitle={s.explanation}>
          <div className="mb-3">
            <div className="flex h-3 overflow-hidden rounded-full" role="img" aria-label={`Fresh issue ${pct(s.fresh_pct, 0)}, offer for sale ${pct(s.ofs_pct, 0)}`}>
              <div style={{ width: `${s.fresh_pct || 0}%`, background: 'var(--series-1)' }} />
              <div style={{ width: `${s.ofs_pct || 0}%`, background: 'var(--series-2)', marginLeft: s.fresh_pct && s.ofs_pct ? 2 : 0 }} />
            </div>
            <div className="mt-1.5 flex flex-wrap gap-4 text-xs text-ink-2">
              <span className="inline-flex items-center gap-1"><i className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: 'var(--series-1)' }} /><Term k="fresh_issue">Fresh issue</Term> {cr(s.fresh_issue_cr)} ({pct(s.fresh_pct, 0)})</span>
              <span className="inline-flex items-center gap-1"><i className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: 'var(--series-2)' }} /><Term k="ofs">Offer for sale</Term> {cr(s.ofs_cr)} ({pct(s.ofs_pct, 0)})</span>
            </div>
          </div>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-[13px]">
            <dt className="text-ink-2">Price band</dt><dd className="num text-right">₹{s.price_band[0]}–{s.price_band[1]}</dd>
            <dt className="text-ink-2">Issue size</dt><dd className="num text-right">{cr(s.issue_size_cr)}</dd>
            <dt className="text-ink-2">Lot / minimum investment</dt><dd className="num text-right">{s.lot_size ?? '—'} / {price(s.min_investment)}</dd>
            <dt className="text-ink-2">Pre → post-issue shares</dt><dd className="num text-right">{(s.pre_issue_shares / 1e7).toFixed(2)} → {(s.post_issue_shares / 1e7).toFixed(2)} Cr</dd>
            <dt className="text-ink-2">Dilution from fresh issue</dt><dd className="num text-right">{pct(s.dilution_pct)}</dd>
            <dt className="text-ink-2">Post-issue market cap (upper band)</dt><dd className="num text-right font-semibold">{cr(s.post_issue_mcap_cr)}</dd>
            <dt className="text-ink-2">Promoter holding pre → post</dt><dd className="num text-right">{pct(p.promoter_pre_pct)} → {pct(p.promoter_post_pct)}</dd>
          </dl>
        </Card>
        <Card title="Implied valuation at the upper band" subtitle="Compared with listed peers">
          <table className="w-full text-[13px]">
            <thead><tr className="border-b border-line text-left text-muted"><th className="py-1.5 font-medium">Multiple</th><th className="py-1.5 text-right font-medium">IPO</th><th className="py-1.5 text-right font-medium">Peer median</th><th className="py-1.5 text-right font-medium">Premium</th></tr></thead>
            <tbody>
              <tr className="border-b border-line/60"><td className="py-1.5"><Term k="pe">P/E (post-issue)</Term></td><td className="num py-1.5 text-right">{ratio(v.pe_post, 1)}</td><td className="num py-1.5 text-right">{ratio(pe.pe_median, 1)}</td><td className="num py-1.5 text-right">{pct(pe.pe_premium_pct, 0, true)}</td></tr>
              <tr className="border-b border-line/60"><td className="py-1.5"><Term k="ev_ebitda">EV/EBITDA</Term></td><td className="num py-1.5 text-right">{ratio(v.ev_ebitda, 1)}</td><td className="num py-1.5 text-right">{ratio(pe.ev_ebitda_median, 1)}</td><td className="num py-1.5 text-right">{pct(pe.ev_ebitda_premium_pct, 0, true)}</td></tr>
              <tr className="border-b border-line/60"><td className="py-1.5"><Term k="pb">P/B (post-issue)</Term></td><td className="num py-1.5 text-right">{ratio(v.pb_post, 1)}</td><td className="num py-1.5 text-right">{ratio(pe.pb_median, 1)}</td><td /></tr>
              <tr className="border-b border-line/60"><td className="py-1.5">P/E on pre-issue shares</td><td className="num py-1.5 text-right">{ratio(v.pe_pre, 1)}</td><td colSpan={2} className="py-1.5 pl-2 text-xs text-muted">how some RHPs quote it</td></tr>
              <tr><td className="py-1.5">EPS pre / post issue</td><td className="num py-1.5 text-right" colSpan={3}>{price(v.eps_pre)} / {price(v.eps_post)}</td></tr>
            </tbody>
          </table>
          <ul className="mt-2 list-disc pl-5 text-[11px] text-muted">{v.notes.map((n: string, i: number) => <li key={i}>{n}</li>)}</ul>
        </Card>
      </div>

      <Card title="Assessments" subtitle="Five separate judgements. Risk cards: higher = riskier.">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {ASSESS.map(([k, l]) => {
            const x = r.assessments[k]
            return (
              <div key={k} className="rounded-lg border border-line p-3">
                <div className="text-xs font-semibold uppercase tracking-wide text-muted">{l}</div>
                <div className="mt-1 flex items-baseline gap-1"><span className="num text-2xl font-semibold">{isNum(x.score) ? x.score.toFixed(0) : '—'}</span><span className="text-xs text-muted">/100</span></div>
                <div className="text-sm font-medium">{x.label}</div>
                <div className="mt-1.5"><ScoreBar score={x.score} invert={x.higher_is_riskier} label={l} /></div>
                <ul className="mt-2 space-y-1 text-[11px] text-ink-2">
                  {x.items.map((it: any, i: number) => (
                    <li key={i} className="flex justify-between gap-2"><span>{it.label}</span><span className="num shrink-0 text-muted">{isNum(it.input) ? `${it.input.toFixed(it.display === 'share' ? 2 : 1)}${it.display === '%' || it.display === 'pp' ? (it.display === 'pp' ? ' pp' : '%') : it.display === '×' ? '×' : ''}` : 'n/a'}</span></li>
                  ))}
                </ul>
              </div>
            )
          })}
        </div>
      </Card>

      <Card title="Valuation scenarios" subtitle="Forward value per share = next-year PAT × P/E ÷ post-issue shares. Assumptions are stated; none is a forecast.">
        {r.scenarios.length === 0 ? <p className="text-sm text-muted">Not available: needs positive profit and peer multiples.</p> : (
          <div className="grid gap-3 md:grid-cols-3">
            {r.scenarios.map((sc: any) => (
              <div key={sc.name} className={cx('rounded-lg border p-3', sc.name === 'Base case' ? 'border-accent' : 'border-line')}>
                <div className="text-sm font-semibold">{sc.name}</div>
                <div className="num mt-1 text-2xl font-semibold">{price(sc.value_per_share)}</div>
                <div className="num text-xs text-muted">{pct(sc.vs_issue_price_pct, 0, true)} vs upper band ₹{s.price_band[1]}</div>
                <div className="mt-2 text-xs text-ink-2">PAT growth {pct(sc.pat_growth_pct)} · P/E {ratio(sc.pe_multiple, 1)} · fwd PAT {cr(sc.forward_pat_cr)}</div>
                <p className="mt-1 text-[11px] text-muted">{sc.assumptions}</p>
              </div>
            ))}
          </div>
        )}
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <SeriesChart title="Financial history (from RHP)" subtitle={`₹ Cr; revenue CAGR ${pct(r.rev_cagr)}, PAT CAGR ${pct(r.pat_cagr)} (${r.cagr_period || 'n/a'})`}
          rows={r.history.map((h: any) => ({ label: h.fy, revenue: h.revenue_cr, pat: h.pat_cr }))}
          series={[{ key: 'revenue', name: 'Revenue', type: 'bar', color: 's1' }, { key: 'pat', name: 'PAT', type: 'bar', color: 's2' }]}
          fmt={(x) => cr(x)} />
        <Card title="Key ratios by year">
          <div className="scroll-x">
            <table className="w-full text-[13px]">
              <thead><tr className="border-b border-line text-left text-muted"><th className="py-1.5 font-medium">FY</th><th className="py-1.5 text-right font-medium">EBITDA m.</th><th className="py-1.5 text-right font-medium">PAT m.</th><th className="py-1.5 text-right font-medium">RoNW</th><th className="py-1.5 text-right font-medium">D/E</th><th className="py-1.5 text-right font-medium">CFO/PAT</th><th className="py-1.5 text-right font-medium">FCF</th></tr></thead>
              <tbody>{r.history.map((h: any) => (
                <tr key={h.fy} className="border-b border-line/60"><td className="py-1.5">{h.fy}</td><td className="num py-1.5 text-right">{pct(h.ebitda_margin)}</td><td className="num py-1.5 text-right">{pct(h.pat_margin)}</td><td className="num py-1.5 text-right">{pct(h.ronw)}</td><td className="num py-1.5 text-right">{ratio(h.debt_to_equity)}</td><td className="num py-1.5 text-right">{ratio(h.cfo_to_pat)}</td><td className="num py-1.5 text-right">{cr(h.fcf_cr)}</td></tr>))}</tbody>
            </table>
          </div>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Use of proceeds (fresh issue)">
          {r.use_of_proceeds.length === 0 ? <p className="text-sm text-muted">Not entered.</p> : (
            <ul className="space-y-1 text-[13px]">{r.use_of_proceeds.map((u: any, i: number) => (
              <li key={i} className="flex justify-between gap-2"><span className="text-ink-2">{u.purpose}</span><span className="num">{cr(u.amount_cr)}</span></li>))}</ul>
          )}
          <p className="mt-2 text-xs text-muted">OFS proceeds ({cr(s.ofs_cr)}) go to selling shareholders, not the company.</p>
        </Card>
        <Card title="Peers used">
          <ul className="space-y-1 text-[13px]">
            {pe.peers.map((x: any, i: number) => (
              <li key={i} className="flex justify-between gap-2"><span className="truncate text-ink-2">{x.name}{x.source === 'user-entered' && <span className="text-[11px] text-muted"> (entered)</span>}{x.is_sample && <span className="text-[11px] text-warn"> (sample)</span>}</span>
                <span className="num shrink-0 text-muted">P/E {ratio(x.pe, 1)}</span></li>))}
          </ul>
          {r.peer_errors?.length > 0 && <p className="mt-2 text-xs text-warn">Could not load: {r.peer_errors.map((e: any) => e.symbol).join(', ')}</p>}
        </Card>
        <Card title="Subscription, GMP & lock-ins">
          {r.subscription && Object.keys(r.subscription).length > 0 && (
            <p className="text-[13px]">Subscription (×): QIB {r.subscription.qib ?? '—'}, NII {r.subscription.nii ?? '—'}, Retail {r.subscription.retail ?? '—'}, Total {r.subscription.total ?? '—'} <span className="text-xs text-muted">({r.subscription.as_of})</span></p>
          )}
          {r.gmp && (
            <p className="mt-2 text-[13px]"><Badge tone="warn">Unofficial</Badge> <Term k="gmp">GMP</Term> ₹{r.gmp.value} <span className="block text-xs text-muted">{r.gmp.label}</span></p>
          )}
          <h3 className="mt-3 text-xs font-semibold">Lock-in expiries (potential selling pressure)</h3>
          {r.lockins.length === 0 ? <p className="text-xs text-muted">Enter a listing date to estimate lock-in dates.</p> : (
            <ul className="mt-1 space-y-0.5 text-xs text-ink-2">{r.lockins.map((l: any, i: number) => <li key={i} className="flex justify-between gap-2"><span>{l.who}</span><span className="num shrink-0">{shortDate(l.date)}</span></li>)}</ul>
          )}
          <p className="mt-1 text-[11px] text-muted">{r.lockin_note}</p>
        </Card>
      </div>

      <Card title="Risks from the offer document">
        {r.risk_factors.length === 0 ? <p className="text-sm text-muted">No risk factors entered.</p> : (
          <ul className="list-disc space-y-1 pl-5 text-[13px] text-ink-2">{r.risk_factors.map((x: string, i: number) => <li key={i}>{x}</li>)}</ul>
        )}
        {p.litigation_notes && <p className="mt-2 text-[13px]"><b>Litigation:</b> {p.litigation_notes}</p>}
        {isNum(p.contingent_liabilities_cr) && <p className="text-[13px]"><b>Contingent liabilities:</b> {cr(p.contingent_liabilities_cr)}</p>}
        {isNum(p.top_customer_concentration_pct) && <p className="text-[13px]"><b>Top-customer concentration:</b> {pct(p.top_customer_concentration_pct)}</p>}
      </Card>
      <p className="text-xs text-muted">{q.data.disclaimer}</p>
    </div>
  )
}
