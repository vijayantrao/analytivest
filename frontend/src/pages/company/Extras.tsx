import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CircleCheck, FileSearch, FileSpreadsheet, FileUp, Info, Loader2, Minus, Plus, Trash2, AlertTriangle } from 'lucide-react'
import { useRef, useState } from 'react'
import { Badge, Card, Severity, Tip, cx } from '../../components/ui'
import { api } from '../../lib/api'
import { byUnit, dateTime, isNum, pct } from '../../lib/format'
import type { A } from './shared'

// ---------------- Quarterly results check ----------------
const Q_TONE: Record<string, 'pos' | 'neg' | 'warn' | 'neutral'> = {
  'Strong quarter': 'pos', 'Steady quarter': 'neutral', 'Mixed quarter': 'warn', 'Soft quarter': 'warn', 'Weak quarter': 'neg',
}

export function QuarterlyCard({ a, compact }: { a: A; compact?: boolean }) {
  const q = a.quarterly
  const cur = a.quote?.currency || 'INR'
  if (!q?.available) {
    return compact ? null : <Card title="Latest quarterly results"><p className="text-sm text-muted">{q?.reason || 'No quarterly data.'}</p></Card>
  }
  return (
    <Card title={<span className="inline-flex items-center gap-2">Latest quarter: {q.latest} <Badge tone={Q_TONE[q.verdict] || 'neutral'}>{q.verdict}</Badge></span>}
      subtitle={`${q.method} Quarter ended ${q.age_days} days ago.`}>
      <div className="scroll-x">
        <table className="w-full min-w-[520px] text-[13px]">
          <thead><tr className="border-b border-line text-left text-muted">
            <th className="py-1.5 font-medium">Metric</th><th className="py-1.5 text-right font-medium">{q.latest}</th>
            <th className="py-1.5 text-right font-medium">YoY{q.year_ago ? ` vs ${q.year_ago}` : ''}</th>
            {!compact && <th className="py-1.5 text-right font-medium">QoQ{q.prev ? ` vs ${q.prev}` : ''}</th>}</tr></thead>
          <tbody>
            {q.rows.map((r: any) => (
              <tr key={r.key} className="border-b border-line/60">
                <td className="py-1.5 text-ink-2">{r.label}</td>
                <td className="num py-1.5 text-right">{byUnit(r.latest, r.unit, cur)}</td>
                <td className="num py-1.5 text-right">{isNum(r.yoy_pct) ? pct(r.yoy_pct, 1, true) : <span className="text-muted" title={r.yoy_reason}>—</span>}</td>
                {!compact && <td className="num py-1.5 text-right">{isNum(r.qoq_pct) ? pct(r.qoq_pct, 1, true) : <span className="text-muted" title={r.qoq_reason}>—</span>}</td>}
              </tr>
            ))}
            {q.margins.map((m: any) => (
              <tr key={m.label} className="border-b border-line/60">
                <td className="py-1.5 text-ink-2">{m.label}</td>
                <td className="num py-1.5 text-right">{pct(m.latest)}</td>
                <td className="num py-1.5 text-right">{isNum(m.change_pp) ? `${m.change_pp > 0 ? '+' : ''}${m.change_pp.toFixed(1)} pp` : '—'}</td>
                {!compact && <td />}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {q.signals.length > 0 && (
        <ul className="mt-3 space-y-1">
          {q.signals.map((s: any, i: number) => (
            <li key={i} className="flex gap-2 text-[13px]">
              {s.kind === 'positive'
                ? <Plus size={15} className="mt-0.5 shrink-0" style={{ color: 'var(--status-good)' }} aria-label="Positive" />
                : <Minus size={15} className="mt-0.5 shrink-0" style={{ color: 'var(--status-critical)' }} aria-label="Negative" />}
              <span><b className="font-medium">{s.title}.</b> <span className="text-muted">{s.evidence}</span></span>
            </li>
          ))}
        </ul>
      )}
      {q.note && <p className="mt-2 text-xs text-warn">{q.note}</p>}
    </Card>
  )
}

// ---------------- Screener.in import ----------------
export function ImportPanel({ a }: { a: A }) {
  const qc = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const imp = a.imported
  const base = a.symbol.split('.')[0]
  const up = useMutation({
    mutationFn: (f: File) => api.upload(`/api/company/${encodeURIComponent(a.symbol)}/import`, f, f.name),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['analysis', a.symbol] }),
  })
  const del = useMutation({ mutationFn: () => api.importDelete(a.symbol), onSuccess: () => qc.invalidateQueries({ queryKey: ['analysis', a.symbol] }) })
  if (a.is_sample) return null
  return (
    <Card title={<span className="inline-flex items-center gap-2"><FileSpreadsheet size={16} aria-hidden /> 10-year history</span>}
      subtitle={imp ? `Imported from ${imp.source}: ${imp.range} (${imp.years} years), ${dateTime(imp.imported_at)}.`
        : `The free data source covers about ${a.metrics.years_available} years. Import Screener.in's Excel export for about 10.`}
      actions={imp
        ? <button onClick={() => del.mutate()} className="inline-flex items-center gap-1 rounded-lg border border-line px-2.5 py-1.5 text-xs text-muted hover:text-neg"><Trash2 size={13} aria-hidden /> Remove import</button>
        : <button onClick={() => input.current?.click()} disabled={up.isPending}
            className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white disabled:opacity-60">
            {up.isPending ? <Loader2 size={13} className="animate-spin" aria-hidden /> : <FileUp size={13} aria-hidden />} Import Excel
          </button>}>
      <input ref={input} type="file" className="sr-only" aria-label="Screener.in Excel export"
        onChange={(e) => { const f = e.target.files?.[0]; if (f) up.mutate(f); e.target.value = '' }} />
      {!imp && (
        <ol className="list-decimal space-y-0.5 pl-5 text-xs text-ink-2">
          <li>Log in to Screener.in (free), open <a className="text-accent underline" href={`https://www.screener.in/company/${base}/consolidated/`} target="_blank" rel="noopener noreferrer">{base}</a>, and click <b>Export to Excel</b>.</li>
          <li>Import the downloaded file here. Imported years replace the provider's for the same dates; newer years still come from live data.</li>
        </ol>
      )}
      {up.isError && <p role="alert" className="mt-2 text-sm text-neg">{(up.error as Error).message}</p>}
      {up.data?.warnings?.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-xs text-muted">{up.data.warnings.map((w: string, i: number) => <li key={i}>• {w}</li>)}</ul>
      )}
    </Card>
  )
}

// ---------------- Annual report facts ----------------
const FACT_LABELS: Record<string, string> = {
  as_of: 'Fiscal year', auditor_qualification: 'Auditor qualification / modified opinion', auditor_resigned: 'Auditor resigned',
  promoter_holding_pct: 'Promoter holding %', promoter_pledge_pct: 'Pledged % of promoter holding',
  contingent_liabilities_cr: 'Contingent liabilities (₹ Cr)', gnpa_pct: 'Gross NPA %', nnpa_pct: 'Net NPA %',
  car_pct: 'Capital adequacy %', pcr_pct: 'Provision coverage %',
}
const EXTRA_EVIDENCE: Record<string, string> = {
  emphasis_of_matter: 'Emphasis of matter (auditor)', related_party: 'Related-party disclosure', litigation: 'Litigation disclosure',
}

function fmtFact(k: string, v: any) {
  if (typeof v === 'boolean') return v ? 'Yes' : 'No'
  if (k.endsWith('_pct')) return `${v}%`
  if (k.endsWith('_cr')) return `₹${Number(v).toLocaleString('en-IN')} Cr`
  return String(v)
}

export function AnnualReportPanel({ a, onApply }: { a: A; onApply: (facts: Record<string, any>) => void }) {
  const input = useRef<HTMLInputElement>(null)
  const [picked, setPicked] = useState<Record<string, boolean>>({})
  const up = useMutation({
    mutationFn: (f: File) => api.upload(`/api/company/${encodeURIComponent(a.symbol)}/annual-report`, f, f.name),
    onSuccess: (d) => setPicked(Object.fromEntries(Object.keys(d.facts).filter((k) => k !== 'auditor_note').map((k) => [k, true]))),
  })
  const r = up.data
  const apply = () => {
    const facts: Record<string, any> = {}
    for (const [k, v] of Object.entries(r.facts)) if (picked[k] || k === 'auditor_note') facts[k] = v
    facts.source = `Annual report (${r.document.filename})${r.facts.as_of ? `, ${r.facts.as_of}` : ''}`
    facts.annual_report = { filename: r.document.filename, pages: r.document.pages, uploaded: Date.now() / 1000 }
    if (facts.auditor_qualification === undefined) delete facts.auditor_note
    onApply(facts)
  }
  return (
    <Card title={<span className="inline-flex items-center gap-2"><FileSearch size={16} aria-hidden /> Read facts from the annual report</span>}
      subtitle="Upload the annual report (any format) to fill auditor opinion, pledges, contingent liabilities and, for banks, NPAs and capital adequacy. Review, then apply to the form."
      actions={<button onClick={() => input.current?.click()} disabled={up.isPending}
        className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white disabled:opacity-60">
        {up.isPending ? <Loader2 size={13} className="animate-spin" aria-hidden /> : <FileUp size={13} aria-hidden />} {up.isPending ? 'Reading…' : 'Upload report'}
      </button>}>
      <input ref={input} type="file" className="sr-only" aria-label="Annual report file"
        onChange={(e) => { const f = e.target.files?.[0]; if (f) up.mutate(f); e.target.value = '' }} />
      {up.isPending && <p role="status" className="text-xs text-muted">Reading the document; large reports take 10–60 seconds.</p>}
      {up.isError && <p role="alert" className="text-sm text-neg">{(up.error as Error).message}</p>}
      {r && (
        <div className="space-y-3">
          <p className="text-xs text-muted">{r.document.filename} · {r.document.pages} pages{r.document.ocr_pages ? ` · ${r.document.ocr_pages} via OCR` : ''}. {r.note}</p>
          {r.found.length === 0 ? <p className="text-sm text-warn">No facts recognised.</p> : (
            <ul className="divide-y divide-line">
              {Object.entries(r.facts).filter(([k]) => k !== 'auditor_note' && k !== 'bank_as_of').map(([k, v]) => {
                const e = r.evidence[k]
                return (
                  <li key={k} className="flex flex-wrap items-center gap-2 py-1.5 text-[13px]">
                    <input type="checkbox" checked={!!picked[k]} onChange={(ev) => setPicked({ ...picked, [k]: ev.target.checked })} aria-label={`Use ${FACT_LABELS[k] || k}`} />
                    <span className="text-ink-2">{FACT_LABELS[k] || k}</span>
                    <b className="num">{fmtFact(k, v)}</b>
                    {e && <Tip wide label={`Source page ${e.page}`} content={<span className="block space-y-1"><b className="text-ink">Page {e.page}</b> · {e.confidence} confidence
                      {e.snippet && <span className="block rounded bg-surface-2 px-1.5 py-1 italic">“{e.snippet}”</span>}{e.note && <span className="block text-muted">{e.note}</span>}</span>}>
                      <span className="inline-flex items-center gap-0.5 rounded bg-surface-2 px-1 text-[10px]">
                        {e.confidence === 'low' ? <AlertTriangle size={10} style={{ color: 'var(--status-serious)' }} aria-hidden /> : e.confidence === 'high' ? <CircleCheck size={10} style={{ color: 'var(--status-good)' }} aria-hidden /> : <Info size={10} aria-hidden />} p.{e.page}
                      </span></Tip>}
                  </li>
                )
              })}
            </ul>
          )}
          {Object.keys(EXTRA_EVIDENCE).some((k) => r.evidence[k]) && (
            <div className="rounded-lg bg-surface-2 p-2.5 text-xs">
              <p className="mb-1 font-medium text-ink">Also worth reading</p>
              <ul className="space-y-1">{Object.entries(EXTRA_EVIDENCE).filter(([k]) => r.evidence[k]).map(([k, l]) => (
                <li key={k}><b>{l}</b> (page {r.evidence[k].page}): <span className="text-muted">{r.evidence[k].snippet}</span></li>))}</ul>
            </div>
          )}
          {r.warnings?.map((w: string, i: number) => <p key={i} className="text-xs text-warn">{w}</p>)}
          {r.found.length > 0 && (
            <button onClick={apply} className={cx('rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white')}>Apply selected to the form below</button>
          )}
        </div>
      )}
    </Card>
  )
}

export function SeverityList({ items }: { items: { severity: 'high' | 'medium' | 'low'; title: string; message: string }[] }) {
  return (
    <ul className="space-y-1">{items.map((x, i) => (
      <li key={i} className="text-[13px]"><Severity level={x.severity} /> <b className="font-medium">{x.title}</b> <span className="text-muted">{x.message}</span></li>))}</ul>
  )
}

// ---------------- ML earnings-quality anomaly check ----------------
export const ML_LEVEL: Record<string, { label: string; tone: 'pos' | 'neg' | 'warn' | 'neutral' }> = {
  typical: { label: 'Typical', tone: 'neutral' },
  unusual: { label: 'Unusual', tone: 'warn' },
  highly_unusual: { label: 'Highly unusual', tone: 'neg' },
}

function mlFmt(v: number | null | undefined, unit: string) {
  if (!isNum(v)) return '—'
  if (unit === 'x') return `${v.toFixed(2)}x`
  if (unit === 'pp' || unit === 'days') return `${v > 0 ? '+' : ''}${v.toFixed(1)} ${unit}`
  return unit === '%' ? `${v.toFixed(1)}%` : `${v.toFixed(1)} ${unit}`
}

export function MlAnomalyCard({ symbol }: { symbol: string }) {
  const q = useQuery({ queryKey: ['anomaly', symbol], queryFn: () => api.companyAnomaly(symbol), staleTime: 10 * 60_000 })
  const [open, setOpen] = useState(false)
  const d = q.data
  const card = d?.model
  return (
    <Card title="Earnings-quality check (machine learning)"
      subtitle="Isolation Forest trained on the companies in your latest screener scan"
      actions={card && <Tip wide content={<span>{card.algorithm}. Trained on {card.trained_on}. {card.levels}. {card.limits}</span>}><Info size={14} aria-hidden /></Tip>}>
      {q.isLoading ? <p className="text-sm text-muted"><Loader2 size={14} className="mr-1 inline animate-spin" aria-hidden />Scoring…</p>
        : q.isError ? <p className="text-sm text-neg">{(q.error as Error).message}</p>
        : !d.available ? <p className="text-[13px] text-ink-2">{d.reason}</p> : (
          <div className="space-y-3 text-[13px]">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={ML_LEVEL[d.level].tone}>{ML_LEVEL[d.level].label}</Badge>
              <span className="text-ink-2">Its accounting signals are more unusual than {Math.floor(d.percentile)}% of the {d.n} companies the model learned from.</span>
            </div>
            {d.reasons.length > 0 ? (
              <div>
                <p className="text-xs text-muted">What made the model {d.level === 'typical' ? 'take notice' : 'flag it'} (largest effect first):</p>
                <ul className="mt-1 list-disc space-y-1 pl-5">{d.reasons.map((r: any) => <li key={r.feature}>{r.text}</li>)}</ul>
              </div>
            ) : <p className="text-ink-2">No single signal stands out from its peers.</p>}
            <button type="button" onClick={() => setOpen(!open)} className="text-xs text-accent" aria-expanded={open}>{open ? 'Hide' : 'Show'} all signals vs peers</button>
            {open && (
              <table className="w-full text-xs">
                <thead><tr className="border-b border-line text-left text-muted"><th className="py-1 font-normal">Signal</th><th className="text-right font-normal">This company</th><th className="text-right font-normal">Peer median</th><th className="pl-3 font-normal">Rule-based check</th></tr></thead>
                <tbody>{card.features.map((f: any) => (
                  <tr key={f.name} className="border-b border-line/60">
                    <td className="py-1">{f.label}</td>
                    <td className="num text-right">{mlFmt(d.features[f.name], f.unit)}</td>
                    <td className="num text-right">{mlFmt(d.peer_median[f.name], f.unit)}</td>
                    <td className="pl-3 text-muted">{f.rule || 'none (model only)'}</td>
                  </tr>))}
                </tbody>
              </table>
            )}
            <p className="text-xs text-muted">"Unusual" means unlike its peers, not "wrong": growth companies, restructurings and sector quirks also stand out. Use it to decide what to read in the annual report.</p>
          </div>
        )}
    </Card>
  )
}
