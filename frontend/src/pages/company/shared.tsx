import type { ReactNode } from 'react'
import { Provenance, StatusText } from '../../components/ui'
import { byUnit, isNum, money } from '../../lib/format'

export type A = any

/** Chart scaling for statement values: ₹ crore for INR, millions otherwise. */
export function scaleFor(currency: string) {
  if (currency === 'INR') {
    return {
      div: 1e7, unit: '₹ Cr',
      fmt: (v: number | null | undefined) => (isNum(v) ? `${v < 0 ? '−' : ''}₹${Math.abs(Math.round(v)).toLocaleString('en-IN')} Cr` : '—'),
      axis: (v: number | null | undefined) => (isNum(v) ? (Math.abs(v) >= 1e5 ? `${(v / 1e5).toFixed(1)}L` : Math.abs(v) >= 1e3 ? `${(v / 1e3).toFixed(0)}K` : `${Math.round(v)}`) : ''),
    }
  }
  return {
    div: 1e6, unit: `${currency} M`,
    fmt: (v: number | null | undefined) => (isNum(v) ? `${Math.round(v).toLocaleString('en-US')} M` : '—'),
    axis: (v: number | null | undefined) => (isNum(v) ? (Math.abs(v) >= 1e3 ? `${(v / 1e3).toFixed(0)}B` : `${Math.round(v)}`) : ''),
  }
}

export const pctFmt = (v: number | null | undefined) => (isNum(v) ? `${v.toFixed(1)}%` : '—')
export const xFmt = (v: number | null | undefined) => (isNum(v) ? `${v.toFixed(2)}×` : '—')

/** Rows for SeriesChart from annual (or quarterly) metric series. */
export function rowsFrom(a: A, keys: string[], opts: { quarterly?: boolean; scale?: number } = {}) {
  const block = opts.quarterly ? a.metrics.quarterly : a.metrics.annual
  return (block.labels as string[]).map((label, i) => {
    const r: any = { label }
    for (const k of keys) {
      const v = block.series?.[k]?.[i]?.value
      r[k] = isNum(v) ? (opts.scale ? v / opts.scale : v) : null
    }
    return r
  })
}

// Figures taken as delivered by the provider; everything else is calculated by the app.
const REPORTED = new Set(['revenue', 'ebitda', 'net_income', 'eps', 'total_debt', 'cfo', 'capex', 'dividends_paid',
  'buybacks', 'share_issuance', 'net_interest_income'])

export function latest(a: A, key: string) {
  return a.metrics.latest?.[key] || { value: null, status: 'missing' }
}

/** A labelled latest-value cell with provenance popover. */
export function MetricValue({ a, k, unit }: { a: A; k: string; unit?: string }) {
  const d = a.metrics.definitions?.[k] || {}
  const m = latest(a, k)
  const cur = a.quote?.currency || 'INR'
  return (
    <span className="inline-flex items-center gap-1">
      {m.value == null ? <StatusText status={m.status} reason={m.reason} /> : <span className="num">{byUnit(m.value, unit || d.unit, cur)}</span>}
      <Provenance period={m.period} method={d.formula} quality={m.value == null ? m.status : REPORTED.has(k) ? 'reported' : 'calculated'}
        source={a.source_label} retrieved={a.freshness?.retrieved_at} reason={m.reason} />
    </span>
  )
}

export function KV({ label, children, hint }: { label: ReactNode; children: ReactNode; hint?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-line/70 py-2 last:border-0">
      <span className="text-[13px] text-ink-2">{label}{hint && <span className="block text-xs text-muted">{hint}</span>}</span>
      <span className="text-right text-[13px] font-medium text-ink">{children}</span>
    </div>
  )
}

export function FinancialNotice({ a }: { a: A }) {
  if (!a.metrics.is_financial) return null
  return (
    <div role="note" className="rounded-lg border border-line bg-accent-soft px-3 py-2 text-[13px] text-accent-ink">
      This is a bank or financial company. Industrial ratios (debt-to-equity, EV/EBITDA, free cash flow, interest coverage) are
      <b> not meaningful</b> for lenders and are hidden. Asset quality (GNPA/NNPA) and capital adequacy (CAR) are not in the
      free data source: enter them, or read them from the annual report, on the Management &amp; shareholding tab.
    </div>
  )
}

export function moneyCur(a: A, v: unknown) {
  return money(v, a.quote?.currency || 'INR')
}
