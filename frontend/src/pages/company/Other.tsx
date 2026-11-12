import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ExternalLink, Save } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { PeerBars } from '../../components/charts'
import { Badge, Card, EmptyState, ScoreBar, Segmented, Severity, Term, cx } from '../../components/ui'
import { api } from '../../lib/api'
import { byUnit, dateTime, isNum, money, pct, ratio } from '../../lib/format'
import { AnnualReportPanel, MlAnomalyCard } from './Extras'
import { type A, KV } from './shared'

// ---------------- Management & shareholding ----------------
const BOOL_FIELDS = [
  ['auditor_qualification', 'Auditor qualification / emphasis of matter'],
  ['auditor_resigned', 'Auditor resigned mid-term'],
  ['material_litigation', 'Material litigation or regulatory action'],
  ['rpt_concern', 'Large or unusual related-party transactions'],
] as const

const NUMERIC_NOTES = ['promoter_holding_pct', 'promoter_pledge_pct', 'fii_pct', 'dii_pct', 'public_pct', 'gnpa_pct', 'nnpa_pct',
  'car_pct', 'pcr_pct', 'contingent_liabilities_cr']

export function Shareholding({ a }: { a: A }) {
  const qc = useQueryClient()
  const h = a.holders || {}
  const [n, setN] = useState<any>(() => ({ ...(a.notes || {}) }))
  const save = useMutation({
    mutationFn: () => {
      const body: any = {}
      for (const [k, v] of Object.entries(n)) {
        if (k === 'updated_at' || v === '' || v == null) continue
        body[k] = NUMERIC_NOTES.includes(k) ? Number(v) : v
      }
      return api.saveNotes(a.symbol, body)
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['analysis', a.symbol] }),
  })
  const gov = a.scores.categories.governance
  const numField = (k: string, label: string) => (
    <label className="block text-xs">
      <span className="text-ink-2">{label}</span>
      <input type="number" min={0} max={100} step={0.01} value={n[k] ?? ''} onChange={(e) => setN({ ...n, [k]: e.target.value })}
        className="num mt-1 w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-sm outline-none focus:border-accent" />
    </label>
  )
  const tri = (k: string) => (n[k] === true ? 'yes' : n[k] === false ? 'no' : 'unknown') as 'yes' | 'no' | 'unknown'
  const [applied, setApplied] = useState(false)
  const fin = a.metrics.is_financial
  return (
    <div className="space-y-4">
      <AnnualReportPanel a={a} onApply={(facts) => { setN({ ...n, ...facts }); setApplied(true) }} />
      {applied && <p role="status" className="rounded-lg bg-accent-soft px-3 py-2 text-[13px] text-accent-ink">Facts applied to the form below. Check them, then press <b>Save</b>.</p>}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Ownership (provider)" subtitle="Yahoo classifies holders as insiders and institutions. For Indian companies “insiders” approximates the promoter group.">
          <KV label="Insiders / promoter group (approx.)">{pct(h.insiders_pct)}</KV>
          <KV label="Institutions (FII + DII combined)">{pct(h.institutions_pct)}</KV>
          <KV label="Public & others (residual)">{isNum(h.insiders_pct) && isNum(h.institutions_pct) ? pct(100 - h.insiders_pct - h.institutions_pct) : '—'}</KV>
          {isNum(h.insiders_pct) && isNum(h.institutions_pct) && (
            <div className="mt-3">
              <div className="flex h-3 overflow-hidden rounded-full" role="img" aria-label="Ownership split">
                <div style={{ width: `${h.insiders_pct}%`, background: 'var(--series-1)' }} />
                <div style={{ width: `${h.institutions_pct}%`, background: 'var(--series-2)', marginLeft: 2 }} />
                <div className="flex-1" style={{ background: 'var(--surface-2)', marginLeft: 2 }} />
              </div>
              <div className="mt-1.5 flex flex-wrap gap-3 text-xs text-ink-2">
                <span className="inline-flex items-center gap-1"><i className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: 'var(--series-1)' }} />Insiders</span>
                <span className="inline-flex items-center gap-1"><i className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: 'var(--series-2)' }} />Institutions</span>
                <span className="inline-flex items-center gap-1"><i className="inline-block h-2.5 w-2.5 rounded-sm border border-line" style={{ background: 'var(--surface-2)' }} />Others</span>
              </div>
            </div>
          )}
          <p className="mt-3 text-xs text-muted">
            Quarterly shareholding history, the FII vs DII split, <Term k="promoter_pledge">promoter pledging</Term>, executive pay and related-party
            transactions are not available from free, terms-compliant sources. Read them in the exchange filings (links on the News tab) and record them on the right.
          </p>
        </Card>
        <Card title="Governance facts you entered" subtitle="Stored locally, labelled “user-entered”. They feed the governance score and red flags."
          actions={<button onClick={() => save.mutate()} disabled={save.isPending}
            className="inline-flex items-center gap-1 rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"><Save size={13} aria-hidden /> Save</button>}>
          <div className="grid grid-cols-2 gap-3">
            {numField('promoter_holding_pct', 'Promoter holding %')}
            {numField('promoter_pledge_pct', 'Pledged % of promoter holding')}
            {numField('fii_pct', 'FII/FPI %')}
            {numField('dii_pct', 'DII %')}
            {numField('contingent_liabilities_cr', 'Contingent liabilities (₹ Cr)')}
          </div>
          {fin && (
            <div className="mt-3 rounded-lg border border-line p-3">
              <p className="mb-2 text-xs font-semibold text-ink">Bank / NBFC asset quality & capital <span className="font-normal text-muted">(from quarterly results or the annual report)</span></p>
              <div className="grid grid-cols-2 gap-3">
                {numField('gnpa_pct', 'Gross NPA %')}
                {numField('nnpa_pct', 'Net NPA %')}
                {numField('car_pct', 'Capital adequacy (CRAR) %')}
                {numField('pcr_pct', 'Provision coverage %')}
                <label className="col-span-2 block text-xs"><span className="text-ink-2">These figures are as of</span>
                  <input value={n.bank_as_of ?? ''} maxLength={40} placeholder="e.g. Q2 FY27 results" onChange={(e) => setN({ ...n, bank_as_of: e.target.value })}
                    className="mt-1 w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-sm outline-none focus:border-accent" /></label>
              </div>
            </div>
          )}
          <div className="mt-3 space-y-2">
            {BOOL_FIELDS.map(([k, label]) => (
              <div key={k} className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-[13px] text-ink-2">{label}</span>
                <Segmented label={label} value={tri(k)} onChange={(v) => setN({ ...n, [k]: v === 'unknown' ? undefined : v === 'yes' })}
                  options={[{ value: 'unknown', label: 'Unknown' }, { value: 'no', label: 'No' }, { value: 'yes', label: 'Yes' }]} />
              </div>
            ))}
          </div>
          <div className="mt-3 grid grid-cols-2 gap-3">
            <label className="col-span-2 block text-xs sm:col-span-1"><span className="text-ink-2">Source (filing / page)</span>
              <input value={n.source ?? ''} maxLength={300} onChange={(e) => setN({ ...n, source: e.target.value })} placeholder="e.g. Shareholding pattern Q2 FY27, BSE"
                className="mt-1 w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-sm outline-none focus:border-accent" /></label>
            <label className="col-span-2 block text-xs sm:col-span-1"><span className="text-ink-2">As of</span>
              <input type="date" value={n.as_of ?? ''} onChange={(e) => setN({ ...n, as_of: e.target.value })}
                className="mt-1 w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-sm outline-none focus:border-accent" /></label>
            <label className="col-span-2 block text-xs"><span className="text-ink-2">Notes</span>
              <textarea value={n.free_text ?? ''} maxLength={4000} rows={2} onChange={(e) => setN({ ...n, free_text: e.target.value })}
                className="mt-1 w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-sm outline-none focus:border-accent" /></label>
          </div>
          {save.isSuccess && <p className="mt-2 text-xs text-pos">Saved. Scores updated.</p>}
          {save.isError && <p className="mt-2 text-xs text-neg">{(save.error as Error).message}</p>}
          {a.notes?.updated_at && <p className="mt-1 text-[11px] text-muted">Last saved {dateTime(a.notes.updated_at)}</p>}
        </Card>
      </div>
      <Card title="Governance score inputs">
        <ItemsTable items={gov.items} cur={a.quote.currency} />
        {gov.note && <p className="mt-2 text-xs text-warn">{gov.note}</p>}
      </Card>
    </div>
  )
}

// ---------------- Peers ----------------
const PEER_METRICS = [
  { k: 'pe', l: 'P/E', f: (v: any) => ratio(v, 1) }, { k: 'pb', l: 'P/B', f: (v: any) => ratio(v, 2) },
  { k: 'ev_ebitda', l: 'EV/EBITDA', f: (v: any) => ratio(v, 1) }, { k: 'roe', l: 'ROE', f: (v: any) => pct(v) },
  { k: 'net_margin', l: 'Net margin', f: (v: any) => pct(v) }, { k: 'revenue_growth', l: 'Revenue growth', f: (v: any) => pct(v) },
  { k: 'debt_to_equity', l: 'Debt/equity', f: (v: any) => ratio(v, 2) },
] as const

export function Peers({ a }: { a: A }) {
  const p = a.peers || {}
  const peers = p.peers || []
  const cur = a.quote.currency
  const [metric, setMetric] = useState<string>(a.metrics.is_financial ? 'pb' : 'pe')
  const m = a.valuation.multiples
  const L = a.metrics.latest
  const self: any = {
    name: a.profile.name, symbol: a.symbol, market_cap: a.valuation.market_cap, pe: m.pe.value, pb: m.pb.value,
    ev_ebitda: m.ev_ebitda.value, roe: L.roe?.value, net_margin: L.net_margin?.value, revenue_growth: L.revenue_growth?.value,
    debt_to_equity: L.debt_to_equity?.value, isSubject: true,
  }
  const med = a.valuation.comps.medians
  const def = PEER_METRICS.find((x) => x.k === metric)!
  if (!peers.length) {
    return <EmptyState title="No peer set available">{p.note || 'Peer discovery uses the provider’s industry screener and is unavailable for sample companies or in offline mode.'}</EmptyState>
  }
  const all = [self, ...peers]
  return (
    <div className="space-y-4">
      <Card title="Peer comparison" subtitle={p.method}
        actions={<Link to={`/compare?s=${[a.symbol, ...peers.slice(0, 4).map((x: any) => x.symbol)].join(',')}`} className="text-xs text-accent">Open in Compare →</Link>}>
        <div className="scroll-x">
          <table className="w-full min-w-[760px] text-[13px]">
            <thead><tr className="border-b border-line text-left text-muted">
              <th className="sticky left-0 bg-surface py-2 pr-3 font-medium">Company</th><th className="py-2 text-right font-medium">Market cap</th>
              {PEER_METRICS.map((x) => <th key={x.k} className="py-2 pl-3 text-right font-medium">{x.l}</th>)}</tr></thead>
            <tbody>
              {all.map((r: any) => (
                <tr key={r.symbol} className={cx('border-b border-line/60', r.isSubject && 'bg-accent-soft/60')}>
                  <td className="sticky left-0 bg-inherit py-2 pr-3">
                    {r.isSubject ? <b>{r.name}</b> : <Link to={`/c/${r.symbol}`} className="hover:text-accent">{r.name}</Link>}
                    <span className="block text-[11px] text-muted">{r.symbol}{r.isSubject ? ' · this company (fiscal-year basis)' : ''}</span>
                  </td>
                  <td className="num py-2 text-right">{money(r.market_cap, cur)}</td>
                  {PEER_METRICS.map((x) => <td key={x.k} className="num py-2 pl-3 text-right">{r.excluded?.[x.k]
                    ? <span className="cursor-help text-xs text-warn underline decoration-dotted" title={`Excluded from medians: ${r.excluded[x.k]}`}>excl.</span>
                    : x.f(r[x.k])}</td>)}
                </tr>
              ))}
              <tr className="text-muted">
                <td className="sticky left-0 bg-surface py-2 pr-3 text-xs font-medium">Peer median</td><td />
                {PEER_METRICS.map((x) => <td key={x.k} className="num py-2 pl-3 text-right text-xs">{x.f(med[x.k]?.value)}</td>)}
              </tr>
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-muted">{p.note} Source: {p.source}. Values marked “excl.” were implausible or extreme outliers and are left out of the medians (hover for the reported value).</p>
      </Card>
      <Card title={`${def.l}: this company vs peers`}
        actions={<label className="text-xs text-muted">Metric{' '}
          <select value={metric} onChange={(e) => setMetric(e.target.value)} className="ml-1 rounded-md border border-line bg-surface px-2 py-1 text-xs text-ink">
            {PEER_METRICS.map((x) => <option key={x.k} value={x.k}>{x.l}</option>)}
          </select></label>}>
        <PeerBars rows={all.map((r: any) => ({ name: r.name, value: r[metric], isSubject: r.isSubject }))} metricLabel={def.l} fmt={def.f as any} subject={a.profile.name} />
      </Card>
    </div>
  )
}

// ---------------- Risks ----------------
export function Risks({ a }: { a: A }) {
  const flags = a.flags || []
  const dq = a.data_quality || []
  const insufficient = Object.entries(a.scores.categories).filter(([, c]: any) => !c.sufficient && !c.not_applicable)
  return (
    <div className="space-y-4">
      <div role="note" className="rounded-lg border border-line bg-surface px-3 py-2 text-[13px] text-ink-2">
        These warnings are <b>automated signals from reported numbers</b>. They point to things worth checking in the filings. They are not findings of fraud or wrongdoing.
      </div>
      <Card title={`Red flags (${flags.length})`}>
        {flags.length === 0 ? <EmptyState title="No red flags triggered">Absence of a flag is not proof of absence of risk, especially for governance items the free data does not cover.</EmptyState> : (
          <ul className="divide-y divide-line">
            {flags.map((f: any) => (
              <li key={f.id} className="py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Severity level={f.severity} />
                  <span className="font-semibold">{f.title}</span>
                  <Badge>{f.category}</Badge>
                  <span className="text-xs text-muted">{f.period}</span>
                </div>
                <p className="mt-1 text-[13px] text-ink"><b className="font-medium">Evidence:</b> {f.evidence}</p>
                <p className="mt-0.5 text-[13px] text-ink-2"><b className="font-medium">Possible implications:</b> {f.implication}</p>
                <p className="mt-0.5 text-xs text-muted">Rule: {f.rule}</p>
              </li>
            ))}
          </ul>
        )}
      </Card>
      {!a.is_sample && <MlAnomalyCard symbol={a.symbol} />}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={`Data-quality notes (${dq.length})`}>
          {dq.length === 0 ? <p className="text-sm text-muted">No data-quality issues detected.</p> : (
            <ul className="space-y-2">{dq.map((d: any, i: number) => (
              <li key={i} className="text-[13px]"><Severity level={d.severity} /> <span className="text-muted">{d.period}</span><p className="text-ink-2">{d.message}</p></li>))}</ul>
          )}
        </Card>
        <Card title="What could not be assessed">
          <ul className="list-disc space-y-1 pl-5 text-[13px] text-ink-2">
            {insufficient.map(([k, c]: any) => <li key={k}><b>{k.replace('_', ' ')}</b>: {c.note}</li>)}
            <li>Material litigation, contingent liabilities, auditor remarks and pledging unless you record them on the Shareholding tab.</li>
            <li>Industry structure, market share, customer/supplier concentration, regulatory and technology risks: qualitative, read the annual report’s risk section.</li>
            {a.metrics.is_financial && a.scores.categories.asset_quality?.score == null && <li>Asset quality (GNPA/NNPA) and capital adequacy, until you enter them or read them from the annual report on the Management & shareholding tab.</li>}
          </ul>
        </Card>
      </div>
    </div>
  )
}

// ---------------- News & disclosures ----------------
export function News({ a }: { a: A }) {
  return (
    <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
      <Card title="Recent news" subtitle="Headlines from the data provider. Not verified by Analytivest.">
        {(a.news || []).length === 0 ? <EmptyState title="No headlines from the provider">Yahoo often returns no news for Indian listings. Use the official disclosure links.</EmptyState> : (
          <ul className="divide-y divide-line">
            {a.news.map((n: any, i: number) => (
              <li key={i} className="py-2">
                <a href={n.link} target="_blank" rel="noopener noreferrer" className="text-[13px] font-medium hover:text-accent">{n.title} <ExternalLink size={11} className="inline" aria-hidden /></a>
                <p className="text-xs text-muted">{[n.publisher, n.published_at && dateTime(n.published_at)].filter(Boolean).join(' · ')}</p>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card title="Official disclosures" subtitle="Primary sources: read filings here">
        <ul className="space-y-2">
          {(a.links || []).map((l: any) => (
            <li key={l.url}><a href={l.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-[13px] text-accent hover:underline">{l.label} <ExternalLink size={11} aria-hidden /></a></li>
          ))}
        </ul>
        <p className="mt-3 text-xs text-muted">Exchange websites are linked, not scraped: their terms restrict automated access.</p>
      </Card>
    </div>
  )
}

// ---------------- Analysis / breakdown ----------------
function ItemsTable({ items, cur }: { items: any[]; cur: string }) {
  if (!items?.length) return <p className="text-sm text-muted">No inputs for this category.</p>
  return (
    <div className="scroll-x">
      <table className="w-full min-w-[620px] text-[13px]">
        <thead><tr className="border-b border-line text-left text-muted">
          <th className="py-1.5 font-medium">Input</th><th className="py-1.5 text-right font-medium">Value</th><th className="py-1.5 pl-3 font-medium">Basis</th>
          <th className="py-1.5 text-right font-medium">Weight</th><th className="w-32 py-1.5 pl-3 font-medium">Score</th></tr></thead>
        <tbody>
          {items.map((it: any) => (
            <tr key={it.key} className="border-b border-line/60 align-top">
              <td className="py-1.5 text-ink-2">{it.label}
                <span className="block text-[11px] text-muted">Thresholds: {it.points.map((p: number[]) => `${p[0]}→${p[1]}`).join(', ')}</span></td>
              <td className="num py-1.5 text-right">{it.input == null ? '—' : byUnit(it.input, it.unit, cur)}</td>
              <td className="py-1.5 pl-3 text-xs text-muted">{it.score == null ? <span className="text-warn">{it.reason || 'missing'} (excluded)</span> : it.basis}</td>
              <td className="num py-1.5 text-right">{it.weight}</td>
              <td className="py-1.5 pl-3">{it.score == null ? <span className="text-xs text-muted">n/a</span> : (
                <div className="flex items-center gap-2"><span className="num w-7 text-right text-xs">{it.score.toFixed(0)}</span><ScoreBar score={it.score} label={`${it.label} score`} /></div>)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const CAT_NAMES: Record<string, string> = {
  growth: 'Growth', profitability: 'Profitability', balance_sheet: 'Balance sheet & debt', cash_flow: 'Cash flow & earnings quality',
  valuation: 'Valuation', governance: 'Governance & management', industry: 'Industry position', asset_quality: 'Asset quality',
}

export function AnalysisTab({ a }: { a: A }) {
  const nar = a.narrative
  const s = a.scores
  return (
    <div className="space-y-4">
      <Card title="Automated analysis" subtitle={nar.method}>
        <p className="text-[15px] font-medium text-ink">{nar.summary}</p>
        {nar.sections.map((sec: any) => (
          <dl key={sec.title} className="mt-4 space-y-3">
            {sec.qa.map((x: any, i: number) => (
              <div key={i}>
                <dt className="text-[13px] font-semibold text-ink">{x.q}</dt>
                <dd className="mt-0.5 text-[13px] text-ink-2">{x.a}</dd>
              </div>
            ))}
          </dl>
        ))}
        <p className="mt-4 text-xs text-muted">{nar.disclaimer}</p>
      </Card>
      <Card title="Score breakdown" subtitle={`Model: ${s.model}; sector profile “${s.profile.name}” (leverage tolerance ${s.profile.leverage_tolerance}×). Missing inputs are excluded and their weight redistributed. Never scored as zero.`}>
        <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="rounded-lg bg-surface-2 p-3"><div className="text-xs text-muted">Composite</div><div className="num text-lg font-semibold">{isNum(s.composite.score) ? s.composite.score.toFixed(0) : '—'}/100</div></div>
          <div className="rounded-lg bg-surface-2 p-3"><div className="text-xs text-muted">Data completeness</div><div className="num text-lg font-semibold">{s.data_completeness.toFixed(0)}%</div></div>
          <div className="rounded-lg bg-surface-2 p-3"><div className="text-xs text-muted">Confidence</div><div className="text-lg font-semibold">{s.confidence.label}</div></div>
          <div className="rounded-lg bg-surface-2 p-3"><div className="text-xs text-muted">Decision support</div><div className="text-sm font-semibold">{s.decision_label}</div></div>
        </div>
        <div className="space-y-5">
          {Object.entries(s.categories).map(([k, c]: any) => (
            <section key={k}>
              <div className="mb-1 flex flex-wrap items-center gap-2">
                <h3 className="text-[14px] font-semibold">{CAT_NAMES[k] || k}</h3>
                <span className="text-xs text-muted">weight in composite: {s.composite.weights[k] ?? 0}</span>
                <span className="ml-auto num text-sm font-semibold">{c.score != null ? `${c.score.toFixed(0)}/100` : c.not_applicable ? 'Not applicable' : 'Insufficient data'}</span>
                <span className="text-xs text-muted">({(c.completeness * 100).toFixed(0)}% of inputs available)</span>
              </div>
              {c.note && <p className="mb-1 text-xs text-warn">{c.note}</p>}
              <ItemsTable items={c.items} cur={a.quote.currency} />
            </section>
          ))}
        </div>
        <p className="mt-4 text-xs text-muted">Thresholds and weights live in <code>backend/app/engine/scoring_config.json</code> and are listed on the <Link to="/methodology" className="underline">Methodology</Link> page.</p>
      </Card>
    </div>
  )
}
