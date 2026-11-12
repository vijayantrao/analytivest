import { useQuery } from '@tanstack/react-query'
import { AlertOctagon, AlertTriangle, CircleCheck, Clock, Database, Info, RefreshCw } from 'lucide-react'
import type { ReactNode } from 'react'
import { api, ApiError } from '../lib/api'
import { ago, dateTime } from '../lib/format'

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(' ')
}

export function Card({ title, subtitle, actions, children, className, id }: {
  title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; id?: string
}) {
  return (
    <section id={id} className={cx('print-break rounded-xl border border-line bg-surface p-4 sm:p-5', className)}
      style={{ boxShadow: 'var(--shadow)' }}>
      {(title || actions) && (
        <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            {title && <h2 className="text-[15px] font-semibold leading-tight text-ink">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-[13px] text-muted">{subtitle}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  )
}

type Tone = 'neutral' | 'pos' | 'neg' | 'warn' | 'accent'
const toneCls: Record<Tone, string> = {
  neutral: 'bg-surface-2 text-ink-2 border-line',
  pos: 'bg-pos-soft text-pos border-transparent',
  neg: 'bg-neg-soft text-neg border-transparent',
  warn: 'bg-warn-soft text-warn border-transparent',
  accent: 'bg-accent-soft text-accent-ink border-transparent',
}

export function Badge({ tone = 'neutral', icon, children, title }: { tone?: Tone; icon?: ReactNode; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={cx('inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium', toneCls[tone])}>
      {icon}
      {children}
    </span>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx('skeleton', className)} aria-hidden="true" />
}

export function PageSkeleton() {
  return (
    <div className="space-y-4" aria-busy="true" aria-label="Loading">
      <Skeleton className="h-16 w-full" />
      <div className="grid gap-4 md:grid-cols-3">
        <Skeleton className="h-40" />
        <Skeleton className="h-40" />
        <Skeleton className="h-40" />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Skeleton className="h-72" />
        <Skeleton className="h-72" />
      </div>
    </div>
  )
}

export function ErrorState({ error, onRetry, title }: { error: unknown; onRetry?: () => void; title?: string }) {
  const e = error as ApiError
  const notFound = e?.status === 404
  return (
    <div role="alert" className="rounded-xl border border-line bg-surface p-6 text-center">
      <AlertTriangle className="mx-auto mb-2 text-warn" size={28} aria-hidden />
      <h2 className="text-base font-semibold">{title || (notFound ? 'Not found' : 'Something went wrong')}</h2>
      <p className="mx-auto mt-1 max-w-xl text-sm text-ink-2">{e?.message || String(error)}</p>
      {e?.code === 'provider_unavailable' && (
        <p className="mx-auto mt-1 max-w-xl text-xs text-muted">
          The free data provider may be rate-limiting requests or temporarily down. Cached data is used when available.
        </p>
      )}
      {onRetry && !notFound && (
        <button onClick={onRetry} className="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90">
          <RefreshCw size={14} aria-hidden /> Retry
        </button>
      )}
    </div>
  )
}

export function EmptyState({ title, children, icon }: { title: string; children?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-line-strong p-6 text-center">
      <div className="mx-auto mb-2 flex justify-center text-muted">{icon || <Database size={22} aria-hidden />}</div>
      <p className="text-sm font-medium text-ink">{title}</p>
      {children && <div className="mx-auto mt-1 max-w-lg text-[13px] text-muted">{children}</div>}
    </div>
  )
}

/** Hover/focus popover. Keyboard reachable: the trigger is a button. */
export function Tip({ content, children, label = 'More information', wide }: { content: ReactNode; children?: ReactNode; label?: string; wide?: boolean }) {
  return (
    <span className="group relative inline-flex align-middle">
      <button type="button" aria-label={label}
        className="inline-flex items-center text-muted hover:text-accent focus-visible:text-accent">
        {children || <Info size={13} aria-hidden />}
      </button>
      <span role="tooltip"
        className={cx('pointer-events-none absolute bottom-full left-1/2 z-40 mb-2 hidden max-w-[80vw] -translate-x-1/2 rounded-lg border border-line bg-surface p-3 text-left text-xs font-normal normal-case leading-relaxed tracking-normal text-ink-2 shadow-lg group-focus-within:block group-hover:block',
          wide ? 'w-80' : 'w-64')}>
        {content}
      </span>
    </span>
  )
}

export function useGlossary() {
  return useQuery({ queryKey: ['glossary'], queryFn: api.glossary, staleTime: Infinity })
}

/** A jargon term with an inline definition. */
export function Term({ k, children }: { k: string; children: ReactNode }) {
  const { data } = useGlossary()
  const g = data?.terms?.[k]
  if (!g) return <>{children}</>
  return (
    <span className="inline-flex items-center gap-1">
      {children}
      <Tip label={`What is ${g.term}?`} content={
        <span>
          <strong className="block text-ink">{g.term}</strong>
          {g.short}
          {g.formula && <code className="mt-1 block rounded bg-surface-2 px-1.5 py-1 text-[11px] text-ink">{g.formula}</code>}
          {g.long && <span className="mt-1 block text-muted">{g.long}</span>}
        </span>} />
    </span>
  )
}

/** Source/period/method popover for a metric. */
export function Provenance({ source, period, method, quality, retrieved, reason }: {
  source?: string; period?: string; method?: string; quality?: string; retrieved?: number; reason?: string | null
}) {
  return (
    <Tip label="Data source and method" content={
      <span className="block space-y-1">
        {period && <span className="block"><b className="text-ink">Period:</b> {period}</span>}
        {method && <span className="block"><b className="text-ink">Method:</b> {method}</span>}
        {quality && <span className="block"><b className="text-ink">Type:</b> {quality.replace('_', ' ')}</span>}
        {source && <span className="block"><b className="text-ink">Source:</b> {source}</span>}
        {retrieved && <span className="block"><b className="text-ink">Retrieved:</b> {dateTime(retrieved)}</span>}
        {reason && <span className="block text-warn">{reason}</span>}
      </span>} />
  )
}

export function MetricTile({ label, value, sub, tip, term, tone }: {
  label: string; value: ReactNode; sub?: ReactNode; tip?: ReactNode; term?: string; tone?: 'pos' | 'neg' | 'warn'
}) {
  return (
    <div className="rounded-lg border border-line bg-surface p-3">
      <div className="flex items-center gap-1 text-xs text-muted">
        {term ? <Term k={term}>{label}</Term> : label}
        {tip}
      </div>
      <div className={cx('num mt-1 text-lg font-semibold', tone === 'pos' && 'text-pos', tone === 'neg' && 'text-neg', tone === 'warn' && 'text-warn')}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-muted">{sub}</div>}
    </div>
  )
}

export function FreshnessBadge({ freshness, what = 'Data' }: { freshness?: any; what?: string }) {
  if (!freshness) return null
  const stale = freshness.stale
  const from = freshness.served_from
  return (
    <Badge tone={stale ? 'warn' : 'neutral'} icon={stale ? <AlertTriangle size={12} aria-hidden /> : <Clock size={12} aria-hidden />}
      title={`${what} retrieved ${dateTime(freshness.retrieved_at)}${freshness.error ? ` · provider error: ${freshness.error}` : ''}`}>
      {stale ? 'STALE · ' : ''}{what} {ago(freshness.retrieved_at)}{from === 'stale-cache' ? ' (provider unavailable)' : ''}
    </Badge>
  )
}

export function SampleBanner() {
  return (
    <div role="note" className="flex items-start gap-2 rounded-lg border border-warn/40 bg-warn-soft px-3 py-2 text-[13px] text-warn">
      <AlertTriangle size={16} className="mt-0.5 shrink-0" aria-hidden />
      <span><b>SAMPLE DATA.</b> This is a fictional company with synthetic numbers, shown to demonstrate the app. It is not a real security.</span>
    </div>
  )
}

const sevMeta = {
  high: { icon: AlertOctagon, label: 'High', color: 'var(--status-critical)' },
  medium: { icon: AlertTriangle, label: 'Medium', color: 'var(--status-serious)' },
  low: { icon: Info, label: 'Low', color: 'var(--muted)' },
} as const

export function Severity({ level }: { level: 'high' | 'medium' | 'low' }) {
  const m = sevMeta[level] || sevMeta.low
  const Icon = m.icon
  return (
    <span className="inline-flex items-center gap-1 text-xs font-semibold text-ink">
      <Icon size={14} style={{ color: m.color }} aria-hidden />
      {m.label}
    </span>
  )
}

export function GoodIcon() {
  return <CircleCheck size={14} style={{ color: 'var(--status-good)' }} aria-hidden />
}

/** 0–100 meter. `invert` for risk (higher = worse). */
export function ScoreBar({ score, invert, label }: { score: number | null | undefined; invert?: boolean; label: string }) {
  const s = typeof score === 'number' ? Math.max(0, Math.min(100, score)) : null
  const good = s == null ? null : invert ? 100 - s : s
  const color = good == null ? 'var(--border-strong)' : good >= 60 ? 'var(--status-good)' : good >= 40 ? 'var(--status-warning)' : 'var(--status-critical)'
  return (
    <div role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={s ?? undefined}
      className="h-2 w-full overflow-hidden rounded-full bg-surface-2">
      {s != null && <div className="h-full rounded-full" style={{ width: `${Math.max(s, 2)}%`, background: color }} />}
    </div>
  )
}

export function Segmented<T extends string>({ options, value, onChange, label, disabled }: {
  options: { value: T; label: string }[]; value: T; onChange: (v: T) => void; label: string; disabled?: (v: T) => boolean
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-lg border border-line bg-surface-2 p-0.5">
      {options.map((o) => {
        const dis = disabled?.(o.value)
        return (
          <button key={o.value} role="radio" aria-checked={value === o.value} disabled={dis}
            onClick={() => onChange(o.value)}
            className={cx('rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
              value === o.value ? 'bg-surface text-ink shadow-sm' : 'text-muted hover:text-ink',
              dis && 'cursor-not-allowed opacity-40 hover:text-muted')}>
            {o.label}
          </button>
        )
      })}
    </div>
  )
}

export function Disclaimer({ text }: { text?: string }) {
  return (
    <p className="text-xs leading-relaxed text-muted">
      {text || 'Research and decision support only. Not investment advice, not a recommendation to buy or sell, and no guarantee of future returns. Quotes are delayed. Verify all figures against company filings.'}
    </p>
  )
}

export function StatusText({ status, reason }: { status?: string; reason?: string | null }) {
  if (status === 'not_meaningful') return <span className="text-muted" title={reason || ''}>n/m</span>
  return <span className="text-muted" title={reason || 'not available'}>—</span>
}
