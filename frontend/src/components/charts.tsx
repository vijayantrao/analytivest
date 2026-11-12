import { useQuery } from '@tanstack/react-query'
import { Table2 } from 'lucide-react'
import { useMemo, useState, type ReactNode } from 'react'
import {
  Area, Bar, CartesianGrid, Cell, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { api } from '../lib/api'
import { DASH, isNum, pct, price as fmtPrice, shortDate } from '../lib/format'
import { useChartColors } from '../lib/theme'
import { Card, EmptyState, Segmented, Skeleton, cx } from './ui'

export interface SeriesDef {
  key: string
  name: string
  type: 'bar' | 'line'
  color?: 's1' | 's2' | 's3'
}

type Fmt = (v: number | null | undefined) => string

function TooltipBox({ active, payload, label, fmt, series }: any) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-lg">
      <div className="mb-1 font-semibold text-ink">{label}</div>
      {series.map((s: SeriesDef) => {
        const p = payload.find((x: any) => x.dataKey === s.key)
        const v = p?.payload?.[s.key]
        return (
          <div key={s.key} className="flex items-center justify-between gap-4">
            <span className="inline-flex items-center gap-1.5 text-ink-2">
              <span className="inline-block h-2 w-2 rounded-full" style={{ background: p?.color || p?.fill }} />
              {s.name}
            </span>
            <span className="num font-medium text-ink">{isNum(v) ? fmt(v) : DASH}</span>
          </div>
        )
      })}
    </div>
  )
}

function Legend({ series, colors }: { series: SeriesDef[]; colors: Record<string, string> }) {
  if (series.length < 2) return null
  return (
    <ul className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-2" aria-label="Legend">
      {series.map((s) => (
        <li key={s.key} className="inline-flex items-center gap-1.5">
          {s.type === 'line'
            ? <span className="inline-block h-0.5 w-4 rounded" style={{ background: colors[s.color || 's1'] }} />
            : <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: colors[s.color || 's1'] }} />}
          {s.name}
        </li>
      ))}
    </ul>
  )
}

function DataTable({ rows, series, fmt, xLabel = 'Period' }: { rows: any[]; series: SeriesDef[]; fmt: Fmt; xLabel?: string }) {
  return (
    <div className="scroll-x">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-line text-left text-muted">
            <th className="py-1.5 pr-3 font-medium">{xLabel}</th>
            {series.map((s) => <th key={s.key} className="py-1.5 pr-3 text-right font-medium">{s.name}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-line/60">
              <td className="py-1.5 pr-3 text-ink-2">{r.label}</td>
              {series.map((s) => <td key={s.key} className="num py-1.5 pr-3 text-right">{isNum(r[s.key]) ? fmt(r[s.key]) : DASH}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Chart card with a period selector, legend, tooltip and a table view of the underlying values. */
export function SeriesChart({ title, subtitle, rows, series, fmt, axisFmt, height = 240, note, emptyText, extraActions }: {
  title: ReactNode; subtitle?: ReactNode; rows: any[]; series: SeriesDef[]; fmt: Fmt; axisFmt?: Fmt; height?: number
  note?: ReactNode; emptyText?: string; extraActions?: ReactNode
}) {
  const c = useChartColors()
  const colors = { s1: c.s1, s2: c.s2, s3: c.s3 }
  const [table, setTable] = useState(false)
  const [span, setSpan] = useState<'3' | '5' | '10'>('10')
  const hasData = rows.some((r) => series.some((s) => isNum(r[s.key])))
  const n = rows.length
  const shown = rows.slice(-Number(span))
  return (
    <Card title={title} subtitle={subtitle} actions={
      <>
        {extraActions}
        {n > 3 && (
          <Segmented label="Years shown" value={span} onChange={setSpan}
            options={[{ value: '3', label: '3Y' }, { value: '5', label: '5Y' }, { value: '10', label: '10Y' }]}
            disabled={(v) => (v === '5' && n <= 3) || (v === '10' && n <= 5)} />
        )}
        <button onClick={() => setTable((t) => !t)} aria-pressed={table}
          className={cx('inline-flex items-center gap-1 rounded-md border border-line px-2 py-1 text-xs', table ? 'bg-accent-soft text-accent-ink' : 'text-muted hover:text-ink')}>
          <Table2 size={13} aria-hidden /> Table
        </button>
      </>
    }>
      {!hasData ? (
        <EmptyState title="No data available">{emptyText || 'The data provider did not report these values for this company.'}</EmptyState>
      ) : table ? (
        <DataTable rows={shown} series={series} fmt={fmt} />
      ) : (
        <>
          <Legend series={series} colors={colors} />
          <div style={{ height }} role="img" aria-label={`${typeof title === 'string' ? title : 'Chart'}; use the Table button for values`}>
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={shown} margin={{ top: 8, right: 8, bottom: 0, left: 0 }} barGap={2} barCategoryGap="28%">
                <CartesianGrid vertical={false} stroke={c.grid} strokeWidth={1} />
                <XAxis dataKey="label" tickLine={false} axisLine={{ stroke: c.border }} tick={{ fill: c.axis, fontSize: 12 }} />
                <YAxis width={64} tickLine={false} axisLine={false} tick={{ fill: c.axis, fontSize: 12 }}
                  tickFormatter={(v) => (axisFmt || fmt)(v)} />
                <ReferenceLine y={0} stroke={c.border} />
                <Tooltip cursor={{ fill: c.grid, opacity: 0.35 }} content={<TooltipBox fmt={fmt} series={series} />} />
                {series.map((s) => s.type === 'bar' ? (
                  <Bar key={s.key} dataKey={s.key} name={s.name} fill={colors[s.color || 's1']} maxBarSize={24}
                    radius={[4, 4, 0, 0]} isAnimationActive={false} />
                ) : (
                  <Line key={s.key} dataKey={s.key} name={s.name} stroke={colors[s.color || 's1']} strokeWidth={2}
                    dot={{ r: 4, strokeWidth: 2, stroke: c.surface, fill: colors[s.color || 's1'] }}
                    activeDot={{ r: 5, strokeWidth: 2, stroke: c.surface }} connectNulls={false}
                    type="linear" isAnimationActive={false} />
                ))}
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
      {note && <p className="mt-2 text-xs text-muted">{note}</p>}
    </Card>
  )
}

const RANGES = [
  { value: '1m', label: '1M', days: 31 }, { value: '6m', label: '6M', days: 183 }, { value: '1y', label: '1Y', days: 366 },
  { value: '3y', label: '3Y', days: 1098 }, { value: '5y', label: '5Y', days: 1830 }, { value: '10y', label: '10Y', days: 3660 },
  { value: 'max', label: 'Max', days: 0 },
] as const
type RangeV = (typeof RANGES)[number]['value']

export function PriceChart({ symbol, currency, height = 260 }: { symbol: string; currency: string; height?: number }) {
  const [range, setRange] = useState<RangeV>('1y')
  const [table, setTable] = useState(false)
  const c = useChartColors()
  const q = useQuery({ queryKey: ['prices', symbol, range], queryFn: () => api.prices(symbol, range), staleTime: 10 * 60_000 })
  const pts = q.data?.points || []
  const from = q.data?.available_from
  const ret = pts.length > 1 ? (pts[pts.length - 1].close / pts[0].close - 1) * 100 : null
  const tsr = pts.length > 1 && pts[0].adj_close ? (pts[pts.length - 1].adj_close / pts[0].adj_close - 1) * 100 : null
  const disabled = (v: RangeV) => {
    if (!from || v === 'max') return false
    const d = RANGES.find((r) => r.value === v)!.days
    return (Date.now() - new Date(from).getTime()) / 86400000 < d * 0.9
  }
  return (
    <Card title="Share price" subtitle={
      <span>
        {ret != null ? <>Price return <b className="num text-ink">{pct(ret, 1, true)}</b>{tsr != null && <> · with dividends <b className="num text-ink">{pct(tsr, 1, true)}</b></>} over the selected range · </> : null}
        Delayed data; split/bonus-adjusted
      </span>}
      actions={
        <>
          <Segmented label="Price range" value={range} onChange={setRange} options={RANGES.map((r) => ({ value: r.value, label: r.label }))} disabled={disabled} />
          <button onClick={() => setTable((t) => !t)} aria-pressed={table}
            className={cx('inline-flex items-center gap-1 rounded-md border border-line px-2 py-1 text-xs', table ? 'bg-accent-soft text-accent-ink' : 'text-muted hover:text-ink')}>
            <Table2 size={13} aria-hidden /> Table
          </button>
        </>
      }>
      {q.isLoading ? <Skeleton className="h-64 w-full" /> : q.isError ? (
        <EmptyState title="Price history unavailable">{(q.error as Error).message}</EmptyState>
      ) : !pts.length ? <EmptyState title="No price history" /> : table ? (
        <div className="max-h-72 overflow-y-auto">
          <DataTable rows={pts.slice().reverse().map((p: any) => ({ label: p.date, close: p.close, adj: p.adj_close }))}
            series={[{ key: 'close', name: 'Close', type: 'line' }, { key: 'adj', name: 'Adj. close (incl. dividends)', type: 'line' }]}
            fmt={(v) => fmtPrice(v, currency)} xLabel="Date" />
        </div>
      ) : (
        <div style={{ height }} role="img" aria-label="Share price line chart; use the Table button for values">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={pts} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id="pfill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={c.s1} stopOpacity={0.14} />
                  <stop offset="100%" stopColor={c.s1} stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid vertical={false} stroke={c.grid} />
              <XAxis dataKey="date" tickLine={false} axisLine={{ stroke: c.border }} minTickGap={48}
                tick={{ fill: c.axis, fontSize: 12 }}
                tickFormatter={(d) => new Date(d).toLocaleDateString('en-IN', range === '1m' || range === '6m' ? { day: 'numeric', month: 'short' } : { month: 'short', year: '2-digit' })} />
              <YAxis width={64} domain={['auto', 'auto']} tickLine={false} axisLine={false} tick={{ fill: c.axis, fontSize: 12 }}
                tickFormatter={(v) => fmtPrice(v, currency).replace('.00', '')} />
              <Tooltip cursor={{ stroke: c.axis, strokeWidth: 1 }} content={({ active, payload }: any) => active && payload?.length ? (
                <div className="rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-lg">
                  <div className="font-semibold text-ink">{shortDate(payload[0].payload.date)}</div>
                  <div className="num text-ink-2">Close {fmtPrice(payload[0].payload.close, currency)}</div>
                </div>) : null} />
              <Area dataKey="close" stroke={c.s1} strokeWidth={2} fill="url(#pfill)" isAnimationActive={false} dot={false}
                activeDot={{ r: 4, strokeWidth: 2, stroke: c.surface }} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  )
}

export function PeBandChart({ band, stats, currentPe }: { band: any[]; stats: any; currentPe?: number | null }) {
  const c = useChartColors()
  const [table, setTable] = useState(false)
  if (!band?.length || !stats) {
    return (
      <Card title="Historical P/E band">
        <EmptyState title="Not enough history">Needs at least 20 weeks with positive EPS. Loss-making years have no meaningful P/E.</EmptyState>
      </Card>
    )
  }
  return (
    <Card title="Historical P/E band" subtitle={`Weekly P/E on trailing fiscal-year EPS, ${shortDate(stats.from)} – ${shortDate(stats.to)}. Lines: 25th percentile, median, 75th percentile.`}
      actions={<button onClick={() => setTable((t) => !t)} aria-pressed={table}
        className={cx('inline-flex items-center gap-1 rounded-md border border-line px-2 py-1 text-xs', table ? 'bg-accent-soft text-accent-ink' : 'text-muted hover:text-ink')}>
        <Table2 size={13} aria-hidden /> Table</button>}>
      {table ? (
        <div className="max-h-72 overflow-y-auto">
          <DataTable rows={band.slice().reverse().map((b) => ({ label: b.date, pe: b.pe, eps: b.eps_period }))}
            series={[{ key: 'pe', name: 'P/E', type: 'line' }]} fmt={(v) => `${v?.toFixed(1)}×`} xLabel="Week" />
        </div>
      ) : (
        <div style={{ height: 240 }} role="img" aria-label="Historical P/E line chart">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={band} margin={{ top: 8, right: 96, bottom: 0, left: 0 }}>
              <CartesianGrid vertical={false} stroke={c.grid} />
              <XAxis dataKey="date" tickLine={false} axisLine={{ stroke: c.border }} minTickGap={48} tick={{ fill: c.axis, fontSize: 12 }}
                tickFormatter={(d) => new Date(d).toLocaleDateString('en-IN', { month: 'short', year: '2-digit' })} />
              <YAxis width={48} tickLine={false} axisLine={false} tick={{ fill: c.axis, fontSize: 12 }} tickFormatter={(v) => `${v}×`} domain={['auto', 'auto']} />
              <Tooltip cursor={{ stroke: c.axis }} content={({ active, payload }: any) => active && payload?.length ? (
                <div className="rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-lg">
                  <div className="font-semibold text-ink">{shortDate(payload[0].payload.date)}</div>
                  <div className="num text-ink-2">P/E {payload[0].payload.pe.toFixed(1)}× (EPS {payload[0].payload.eps_period})</div>
                </div>) : null} />
              {[['p25', '25th'], ['median', 'Median'], ['p75', '75th']].map(([k, l]) => (
                <ReferenceLine key={k} y={stats[k]} stroke={c.axis} strokeWidth={1}
                  label={{ value: `${l} ${stats[k].toFixed(1)}×`, position: 'right', fill: c.muted, fontSize: 11 }} />
              ))}
              <Line dataKey="pe" stroke={c.s1} strokeWidth={2} dot={false} isAnimationActive={false} activeDot={{ r: 4, stroke: c.surface, strokeWidth: 2 }} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}
      {isNum(currentPe) && <p className="mt-2 text-xs text-muted">Current P/E on latest fiscal-year earnings: <b className="num text-ink">{currentPe.toFixed(1)}×</b>, against a 5-year median of {stats.median.toFixed(1)}×.</p>}
    </Card>
  )
}

/** Horizontal bars with the subject company emphasised and peers in a recessive tone. */
export function PeerBars({ rows, metricLabel, fmt, subject }: { rows: { name: string; value: number | null; isSubject?: boolean }[]; metricLabel: string; fmt: Fmt; subject: string }) {
  const c = useChartColors()
  const data = useMemo(() => rows.filter((r) => isNum(r.value)).sort((a, b) => (b.value as number) - (a.value as number)), [rows])
  if (data.length < 2) return <EmptyState title={`Not enough peer data for ${metricLabel}`} />
  return (
    <div style={{ height: Math.max(160, data.length * 34 + 24) }} role="img" aria-label={`${metricLabel} by company, ${subject} highlighted`}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart layout="vertical" data={data} margin={{ top: 4, right: 56, bottom: 4, left: 8 }}>
          <CartesianGrid horizontal={false} stroke={c.grid} />
          <XAxis type="number" tickLine={false} axisLine={false} tick={{ fill: c.axis, fontSize: 12 }} tickFormatter={(v) => fmt(v)} />
          <YAxis type="category" dataKey="name" width={150} tickLine={false} axisLine={false} tick={{ fill: c.text2, fontSize: 12 }}
            tickFormatter={(n: string) => (n.length > 22 ? n.slice(0, 21) + '…' : n)} />
          <ReferenceLine x={0} stroke={c.border} />
          <Tooltip cursor={{ fill: c.grid, opacity: 0.35 }} content={({ active, payload }: any) => active && payload?.length ? (
            <div className="rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-lg">
              <div className="font-semibold text-ink">{payload[0].payload.name}</div>
              <div className="num text-ink-2">{metricLabel}: {fmt(payload[0].payload.value)}</div>
            </div>) : null} />
          <Bar dataKey="value" maxBarSize={20} radius={[0, 4, 4, 0]} isAnimationActive={false}
            label={{ position: 'right', fill: c.text2, fontSize: 11, formatter: (v: any) => fmt(v) }}>
            {data.map((d, i) => <Cell key={i} fill={d.isSubject ? c.s1 : c.border} />)}
          </Bar>
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}
