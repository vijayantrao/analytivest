import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bell, BellRing, CheckCheck, Loader2, RefreshCw } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card, EmptyState, ErrorState, Severity, Skeleton, cx } from '../components/ui'
import { api } from '../lib/api'
import { ago, dateTime } from '../lib/format'

export function useJob(id: string | null) {
  return useQuery({
    queryKey: ['job', id], queryFn: () => api.job(id!), enabled: !!id,
    refetchInterval: (q) => (q.state.data && ['done', 'error', 'cancelled'].includes(q.state.data.status) ? false : 1500),
  })
}

export function JobProgress({ job }: { job: any }) {
  if (!job) return null
  const running = ['queued', 'running'].includes(job.status)
  const pctDone = job.total ? Math.round((job.progress / job.total) * 100) : 0
  return (
    <div className="rounded-lg border border-line bg-surface-2 p-3 text-[13px]" role="status">
      <div className="flex items-center justify-between gap-2">
        <span className="inline-flex items-center gap-1.5">{running && <Loader2 size={14} className="animate-spin" aria-hidden />}
          <b className="capitalize">{job.status}</b> · {job.message}</span>
        {job.total > 0 && <span className="num text-xs text-muted">{job.progress}/{job.total}</span>}
      </div>
      {running && job.total > 0 && <div className="mt-2 h-1.5 rounded-full bg-surface"><div className="h-1.5 rounded-full bg-accent" style={{ width: `${pctDone}%` }} /></div>}
    </div>
  )
}

/** Header bell: unread count, polled every minute; desktop notification when new alerts arrive. */
export function AlertBell() {
  const q = useQuery({ queryKey: ['alerts-count'], queryFn: api.alertsCount, refetchInterval: 60_000 })
  const n = q.data?.unread ?? 0
  const prev = useRef<number | null>(null)
  useEffect(() => {
    if (prev.current != null && n > prev.current && 'Notification' in window && Notification.permission === 'granted') {
      try { new Notification('Analytivest', { body: `${n - prev.current} new alert(s). Open Analytivest to review.`, icon: '/favicon.svg' }) } catch { /* unsupported */ }
    }
    prev.current = n
  }, [n])
  return (
    <Link to="/alerts" className="relative rounded-lg p-2 text-muted hover:bg-surface-2 hover:text-ink" aria-label={`Alerts: ${n} unread`}>
      {n > 0 ? <BellRing size={18} aria-hidden /> : <Bell size={18} aria-hidden />}
      {n > 0 && <span className="absolute -right-0.5 -top-0.5 min-w-4 rounded-full bg-neg px-1 text-center text-[10px] font-semibold leading-4 text-white">{n > 99 ? '99+' : n}</span>}
    </Link>
  )
}

export default function Alerts() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['alerts'], queryFn: api.alerts })
  const [jobId, setJobId] = useState<string | null>(null)
  const job = useJob(jobId)
  const [cfg, setCfg] = useState<{ enabled: boolean; time: string } | null>(null)
  const [perm, setPerm] = useState(typeof Notification !== 'undefined' ? Notification.permission : 'unsupported')
  useEffect(() => { if (q.data && !cfg) setCfg(q.data.settings) }, [q.data, cfg])
  useEffect(() => {
    if (job.data?.status === 'done') { qc.invalidateQueries({ queryKey: ['alerts'] }); qc.invalidateQueries({ queryKey: ['alerts-count'] }) }
  }, [job.data?.status, qc])
  const check = useMutation({ mutationFn: api.alertsCheck, onSuccess: (d) => setJobId(d.job_id) })
  const read = useMutation({ mutationFn: (ids?: number[]) => api.alertsRead(ids), onSuccess: () => { qc.invalidateQueries({ queryKey: ['alerts'] }); qc.invalidateQueries({ queryKey: ['alerts-count'] }) } })
  const saveCfg = useMutation({ mutationFn: () => api.alertsSettings(cfg!.enabled, cfg!.time), onSuccess: () => qc.invalidateQueries({ queryKey: ['alerts'] }) })

  if (q.isLoading) return <Skeleton className="h-60" />
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />
  const d = q.data
  const running = job.data && ['queued', 'running'].includes(job.data.status)
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Alerts</h1>
          <p className="max-w-2xl text-[13px] text-ink-2">A daily check of your watchlist and portfolio for new red flags, verdict or valuation changes, score moves of 10+ points, new quarterly results and big price moves. The first check of each company only records a baseline.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button onClick={() => read.mutate(undefined)} disabled={!d.unread} className="inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-2 text-sm disabled:opacity-50"><CheckCheck size={15} aria-hidden /> Mark all read</button>
          <button onClick={() => check.mutate()} disabled={check.isPending || !!running} className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white disabled:opacity-60">
            <RefreshCw size={15} className={cx(running && 'animate-spin')} aria-hidden /> Check now</button>
        </div>
      </div>
      {check.isError && <p role="alert" className="text-sm text-neg">{(check.error as Error).message}</p>}
      <JobProgress job={job.data || (d.job && ['queued', 'running'].includes(d.job.status) ? d.job : null)} />

      <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
        <Card title={`Alerts (${d.unread} unread)`}>
          {d.alerts.length === 0 ? (
            <EmptyState title="No alerts yet">{d.tracked.length ? 'Run a check: the first run records a baseline, later runs report what changed.' : 'Add companies to your watchlist or portfolio first.'}</EmptyState>
          ) : (
            <ul className="divide-y divide-line">
              {d.alerts.map((a: any) => (
                <li key={a.id} className={cx('flex items-start justify-between gap-3 py-2.5', !a.read && 'bg-accent-soft/40 -mx-2 px-2 rounded')}>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2 text-[13px]"><Severity level={a.severity} />
                      <Link to={`/c/${a.symbol}`} className="font-medium hover:text-accent">{a.title}</Link></div>
                    <p className="text-[13px] text-ink-2">{a.message}</p>
                    <p className="text-[11px] text-muted">{dateTime(a.created_at)} · {a.symbol}</p>
                  </div>
                  {!a.read && <button onClick={() => read.mutate([a.id])} className="shrink-0 text-xs text-accent">Mark read</button>}
                </li>
              ))}
            </ul>
          )}
        </Card>
        <div className="space-y-4">
          <Card title="Schedule">
            {cfg && (
              <div className="space-y-3 text-[13px]">
                <label className="flex items-center gap-2"><input type="checkbox" checked={cfg.enabled} onChange={(e) => setCfg({ ...cfg, enabled: e.target.checked })} /> Daily check while the app is running</label>
                <label className="block text-xs"><span className="text-ink-2">Time (after market close)</span>
                  <input type="time" value={cfg.time} onChange={(e) => setCfg({ ...cfg, time: e.target.value })} className="mt-1 block rounded-lg border border-line bg-surface px-2 py-1.5 text-sm" /></label>
                <button onClick={() => saveCfg.mutate()} className="rounded-lg border border-line px-3 py-1.5 text-xs">Save schedule</button>
                {saveCfg.isSuccess && <span className="ml-2 text-xs text-pos">Saved</span>}
                <p className="text-xs text-muted">Last check: {d.last_run ? `${dateTime(d.last_run)} (${ago(d.last_run)})` : 'never'}.</p>
                <div className="border-t border-line pt-3">
                  <p className="mb-1 text-xs text-ink-2">Desktop notifications while Analytivest is open in a browser tab:</p>
                  {perm === 'granted' ? <p className="text-xs text-pos">Enabled</p> : perm === 'unsupported' ? <p className="text-xs text-muted">Not supported by this browser.</p> : (
                    <button onClick={async () => setPerm(await Notification.requestPermission())} className="rounded-lg border border-line px-3 py-1.5 text-xs">Enable notifications</button>)}
                </div>
              </div>
            )}
          </Card>
          <Card title={`Tracked companies (${d.tracked.length})`} subtitle="Your watchlist plus portfolio holdings">
            {d.tracked.length === 0 ? <p className="text-sm text-muted">None yet.</p> : (
              <ul className="flex flex-wrap gap-1.5">{d.tracked.map((s: string) => <li key={s}><Link to={`/c/${s}`} className="rounded-full border border-line px-2 py-0.5 text-xs hover:text-accent">{s}</Link></li>)}</ul>)}
          </Card>
          <Card title="Run checks without opening the app">
            <p className="text-xs text-ink-2">To check even when Analytivest isn't running, add a daily Windows Task Scheduler task that runs this in the <code>stockiq\backend</code> folder:</p>
            <code className="mt-1 block rounded bg-surface-2 px-2 py-1.5 text-xs">.venv\Scripts\python -m app.alerts</code>
            <p className="mt-1 text-xs text-muted">Alerts it finds appear here the next time you open the app.</p>
          </Card>
        </div>
      </div>
    </div>
  )
}
