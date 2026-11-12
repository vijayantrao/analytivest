import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, Download, FolderDown, Lock, RotateCcw, Upload } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Card, ErrorState, Skeleton, cx } from '../components/ui'
import { api, type BackupSettings } from '../lib/api'
import { ago, dateTime } from '../lib/format'

const TABLE_LABELS: Record<string, string> = {
  holdings: 'Portfolio holdings', watchlist: 'Watchlist', company_notes: 'Company notes', imports: '10-year imports',
  saved_analysis: 'Saved snapshots', ipo: 'IPOs', alerts: 'Alerts', snapshots: 'Alert baselines', settings: 'Settings',
}

function size(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

type RestoreTarget = { kind: 'upload'; file: File } | { kind: 'saved'; name: string; location: 'local' | 'gdrive' }

function Check({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return (
    <li className="flex items-start gap-2 py-1.5 text-[13px]">
      {ok ? <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-pos" aria-label="OK" />
        : <AlertTriangle size={16} className="mt-0.5 shrink-0 text-warn" aria-label="Warning" />}
      <span>{children}</span>
    </li>
  )
}

export default function Settings() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['backup-status'], queryFn: api.backupStatus })
  const [cfg, setCfg] = useState<BackupSettings | null>(null)
  const [restored, setRestored] = useState<any>(null)
  const [pw, setPw] = useState({ password: '', confirm: '', changing: false })
  const [askPw, setAskPw] = useState<{ target: RestoreTarget; message: string; password: string } | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  useEffect(() => { if (q.data && !cfg) setCfg(q.data.settings) }, [q.data, cfg])

  const refresh = () => qc.invalidateQueries({ queryKey: ['backup-status'] })
  const download = useMutation({ mutationFn: api.backupDownload })
  const [encForm, setEncForm] = useState<{ password: string; confirm: string } | null>(null)
  const encDl = useMutation({ mutationFn: (password?: string) => api.backupDownloadEncrypted(password), onSuccess: () => setEncForm(null) })
  const run = useMutation({ mutationFn: api.backupRun, onSuccess: refresh })
  const save = useMutation({
    mutationFn: () => api.backupSettings({ ...cfg!, password: cfg!.encrypt && pw.password ? pw.password : undefined }),
    onSuccess: (s) => { setCfg(s); setPw({ password: '', confirm: '', changing: false }); refresh() },
  })
  const purge = useMutation({ mutationFn: api.backupPurgePlainCloud, onSuccess: refresh })
  // One restore path for uploaded files and saved backups; an encrypted backup asks for its password and retries.
  const restore = useMutation({
    mutationFn: ({ target, password }: { target: RestoreTarget; password?: string }) =>
      target.kind === 'upload' ? api.backupRestore(target.file, password) : api.backupRestoreFile(target.name, target.location, password),
    onSuccess: (r) => { setAskPw(null); setRestored(r); qc.invalidateQueries() },
    onError: (e: any, v) => {
      if (e.code === 'password_required' || e.code === 'wrong_password') setAskPw({ target: v.target, message: e.message, password: '' })
    },
  })

  if (q.isLoading) return <Skeleton className="h-60" />
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />
  const d = q.data
  const sec = d.security
  const confirmRestore = (what: string) =>
    window.confirm(`Replace your current portfolio, watchlist, notes, IPOs, imports and alerts with ${what}?\n\nA safety backup of the current data is saved first, so this can be undone.`)
  const onPick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    e.target.value = ''
    if (f && confirmRestore(`the backup "${f.name}"`)) restore.mutate({ target: { kind: 'upload', file: f } })
  }
  const restoreErr = restore.error && !askPw ? (restore.error as Error) : null
  const enc = d.encryption
  const needNewPw = !!cfg?.encrypt && (!enc.has_password || pw.changing)
  const pwProblem = !needNewPw ? null
    : pw.password.length < enc.min_password ? `Use at least ${enc.min_password} characters.`
      : pw.password !== pw.confirm ? 'The two passwords do not match.' : null
  const saveSettings = () => { if (!pwProblem) save.mutate() }
  const encFormProblem = !encForm ? null
    : encForm.password.length < enc.min_password ? `Use at least ${enc.min_password} characters.`
      : encForm.password !== encForm.confirm ? 'The two passwords do not match.' : null
  const btn = 'inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-2 text-sm hover:bg-surface-2 disabled:opacity-50'

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Data &amp; security</h1>
        <p className="max-w-2xl text-[13px] text-ink-2">Where your data lives, how it is protected, and backups of everything you have entered or imported. Market data is not backed up because it downloads again automatically.</p>
      </div>

      {restored && (
        <div role="status" className="rounded-lg border border-line bg-pos-soft p-3 text-[13px]">
          <b>Restored</b> the backup from {restored.created_at ? dateTime(restored.created_at) : 'the file'}:{' '}
          {Object.entries(restored.restored).filter(([t]) => t !== 'settings').map(([t, n]) => `${n} ${TABLE_LABELS[t]?.toLowerCase() || t}`).join(', ')}.
          {' '}Your previous data was saved as <code>{restored.safety_backup}</code>, so you can undo this from the list below.
        </div>
      )}
      {restoreErr && <p role="alert" className="text-sm text-neg">Restore failed: {restoreErr.message}</p>}
      {askPw && (
        <form role="dialog" aria-label="Backup password" className="space-y-2 rounded-lg border border-line bg-warn-soft p-3 text-[13px]"
          onSubmit={(e) => { e.preventDefault(); restore.mutate({ target: askPw.target, password: askPw.password }) }}>
          <p className="flex items-center gap-1.5"><Lock size={14} aria-hidden /> {askPw.message}</p>
          <div className="flex flex-wrap gap-2">
            <input type="password" autoFocus autoComplete="current-password" value={askPw.password} aria-label="Backup password"
              onChange={(e) => setAskPw({ ...askPw, password: e.target.value })}
              className="w-64 rounded-lg border border-line bg-surface px-2 py-1.5 text-sm" />
            <button type="submit" disabled={!askPw.password || restore.isPending} className="rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white disabled:opacity-60">{restore.isPending ? 'Decrypting…' : 'Restore'}</button>
            <button type="button" onClick={() => setAskPw(null)} className="rounded-lg border border-line px-3 py-1.5 text-xs">Cancel</button>
          </div>
        </form>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Security" subtitle="Checked each time the app starts">
          <ul>
            <Check ok={sec.local_only}>{sec.local_only ? <>Only this computer can connect (the server listens on <code>{sec.bind_host}</code>).</> : <>The server listens on <code>{sec.bind_host}</code>, so other devices on your network can reach it.</>}</Check>
            <Check ok={sec.cross_site_blocked && sec.session_token}>Other websites open in your browser cannot read or change your data: the app checks the host name and origin of every request and requires a secret key that changes each time it starts.</Check>
            <Check ok>Uploads are limited to {sec.upload_limit_mb} MB, and Excel, Word and ZIP files are checked for "zip bombs" before they are unpacked.</Check>
            <Check ok={!d.data.in_synced_folder}>{d.data.in_synced_folder ? 'Your database is inside a synced folder (OneDrive, Dropbox…). Syncing a live database uploads it and can corrupt it.' : 'Your database is stored on this computer only, outside OneDrive and other synced folders.'}</Check>
            {d.data.legacy_copy_present && <Check ok={false}>An old copy of the database is still in the project folder (<code>backend\data</code>). Delete it once you have checked your data here.</Check>}
          </ul>
        </Card>

        <Card title="Your data">
          <p className="break-all text-[13px]"><span className="text-ink-2">Database:</span> <code>{d.data.db_path}</code> ({size(d.data.size)}, including cached market data)</p>
          <ul className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-[13px] sm:grid-cols-3">
            {Object.entries(d.counts as Record<string, number>).filter(([t]) => t !== 'settings').map(([t, n]) => (
              <li key={t} className="flex justify-between gap-2"><span className="text-ink-2">{TABLE_LABELS[t] || t}</span><span className="num">{n}</span></li>
            ))}
          </ul>
        </Card>
      </div>

      <Card title="Backups" subtitle="Everything you entered or imported, in one file">
        <div className="flex flex-wrap gap-2">
          <button onClick={() => (enc.has_password ? encDl.mutate(undefined) : setEncForm({ password: '', confirm: '' }))} disabled={encDl.isPending}
            className={cx(btn, 'bg-accent text-white border-accent hover:bg-accent')}><Lock size={15} aria-hidden /> {encDl.isPending ? 'Encrypting…' : 'Download encrypted backup'}</button>
          <button onClick={() => run.mutate()} disabled={run.isPending} className={btn}><FolderDown size={15} aria-hidden /> {d.settings.cloud === 'gdrive' ? 'Back up now (computer + Google Drive)' : 'Back up now'}</button>
          <button onClick={() => fileRef.current?.click()} disabled={restore.isPending} className={btn}><Upload size={15} aria-hidden /> Restore from a file…</button>
          <button onClick={() => download.mutate()} disabled={download.isPending} className={btn} title="Readable JSON: keep it on this computer, don't upload it"><Download size={15} aria-hidden /> Download unencrypted</button>
          <input ref={fileRef} type="file" accept=".json,application/json" className="hidden" onChange={onPick} aria-label="Backup file to restore" />
        </div>
        {encForm && (
          <form className="mt-3 space-y-2 rounded-lg border border-line p-3 text-[13px]" aria-label="Encryption password"
            onSubmit={(e) => { e.preventDefault(); if (!encFormProblem) encDl.mutate(encForm.password) }}>
            <p>Choose a password for this file. You'll need it to restore the backup.</p>
            <div className="flex flex-wrap items-end gap-3">
              <label className="block text-xs"><span className="text-ink-2">Password</span>
                <input type="password" autoFocus autoComplete="new-password" value={encForm.password} onChange={(e) => setEncForm({ ...encForm, password: e.target.value })}
                  className="mt-1 block w-56 rounded-lg border border-line bg-surface px-2 py-1.5 text-sm" /></label>
              <label className="block text-xs"><span className="text-ink-2">Repeat password</span>
                <input type="password" autoComplete="new-password" value={encForm.confirm} onChange={(e) => setEncForm({ ...encForm, confirm: e.target.value })}
                  className="mt-1 block w-56 rounded-lg border border-line bg-surface px-2 py-1.5 text-sm" /></label>
              <button type="submit" disabled={!!encFormProblem || encDl.isPending} className="rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white disabled:opacity-60">Download</button>
              <button type="button" onClick={() => setEncForm(null)} className="rounded-lg border border-line px-3 py-1.5 text-xs">Cancel</button>
            </div>
            {encFormProblem && (encForm.password || encForm.confirm) && <p className="text-xs text-warn">{encFormProblem}</p>}
            <p className="text-xs text-muted">Write the password down somewhere safe. Without it the file cannot be opened. Nobody, including Analytivest, can recover it.</p>
          </form>
        )}
        {encDl.isSuccess && (
          <p className="mt-2 text-xs text-pos">Encrypted backup downloaded{enc.has_password ? ' (with your saved password)' : ''}. To keep a copy online, open{' '}
            <a className="text-accent underline" href="https://drive.google.com/drive/my-drive" target="_blank" rel="noopener noreferrer">Google Drive</a>{' '}
            and drag the file from your Downloads folder into it. Restore it later with <b>Restore from a file</b>.</p>
        )}
        {encDl.isError && <p role="alert" className="mt-2 text-sm text-neg">{(encDl.error as Error).message}</p>}
        {download.isError && <p role="alert" className="mt-2 text-sm text-neg">{(download.error as Error).message}</p>}
        {run.isError && <p role="alert" className="mt-2 text-sm text-neg">{(run.error as Error).message}</p>}
        {run.isSuccess && (
          <p className="mt-2 text-xs">
            <span className="text-pos">Saved {run.data.name} on this computer.</span>
            {run.data.cloud && (run.data.cloud.ok
              ? <span className="text-pos"> Copied to Google Drive.</span>
              : <span className="text-warn"> Google Drive copy failed: {run.data.cloud.message}</span>)}
          </p>
        )}

        {cfg && (
          <div className="mt-4 space-y-3 border-t border-line pt-4 text-[13px]">
            <fieldset>
              <legend className="mb-1.5 text-xs text-ink-2">Where backups go</legend>
              <div className="grid gap-2 md:grid-cols-2">
                {([
                  ['none', 'Keep local only', `Backups stay on this computer (${cfg.folder || d.folder_default}). Nothing leaves your PC.`],
                  ['gdrive', 'This computer + Google Drive', 'Each backup is also copied to your Google Drive, so it survives a disk failure or a lost laptop.'],
                ] as const).map(([v, label, desc]) => (
                  <label key={v} className={cx('flex cursor-pointer gap-2 rounded-lg border p-3', cfg.cloud === v ? 'border-accent bg-accent-soft/40' : 'border-line')}>
                    <input type="radio" name="cloud" value={v} checked={cfg.cloud === v} onChange={() => setCfg({ ...cfg, cloud: v, ...(v === 'gdrive' && d.settings.cloud !== 'gdrive' ? { encrypt: enc.available } : {}) })} className="mt-0.5" />
                    <span><b className="font-medium">{label}</b><span className="block text-xs text-ink-2">{desc}</span></span>
                  </label>
                ))}
              </div>
            </fieldset>

            {cfg.cloud === 'gdrive' && (d.gdrive.detected && !cfg.gdrive_path ? (
              <p className="rounded-lg bg-pos-soft px-3 py-2 text-xs">Found Google Drive at <code>{d.gdrive.detected}</code>. Backups will be copied to <code>{d.gdrive.detected}\Analytivest Backups</code>, and Google Drive for desktop uploads them.</p>
            ) : (
              <div className="space-y-2 rounded-lg bg-warn-soft px-3 py-2 text-xs">
                {!d.gdrive.detected && (
                  <>
                    <p><b>Google Drive for desktop isn't set up on this computer.</b> Analytivest never asks for your Google password: it saves backups into the folder Google's own app syncs.</p>
                    <ol className="list-decimal space-y-0.5 pl-5">
                      <li>Install <a className="text-accent underline" href="https://www.google.com/drive/download/" target="_blank" rel="noopener noreferrer">Google Drive for desktop</a> (free).</li>
                      <li>Sign in with your Google account when it opens.</li>
                      <li>Come back here, choose <b>This computer + Google Drive</b> and press <b>Save settings</b>. The "My Drive" folder (usually <code>G:\My Drive</code>) is found automatically.</li>
                    </ol>
                  </>
                )}
                <label className="block"><span className="text-ink-2">"My Drive" folder (only if it isn't found automatically)</span>
                  <input value={cfg.gdrive_path} onChange={(e) => setCfg({ ...cfg, gdrive_path: e.target.value })} placeholder="G:\My Drive"
                    className="mt-1 block w-full max-w-md rounded-lg border border-line bg-surface px-2 py-1.5 text-sm" /></label>
              </div>
            ))}

            {cfg.cloud === 'gdrive' && (
              <div className="space-y-2 rounded-lg border border-line p-3">
                <label className="flex items-start gap-2">
                  <input type="checkbox" checked={cfg.encrypt} disabled={!enc.available} className="mt-0.5"
                    onChange={(e) => setCfg({ ...cfg, encrypt: e.target.checked })} />
                  <span><b className="font-medium"><Lock size={13} className="mr-1 inline" aria-hidden />Encrypt Google Drive copies with a password</b> (recommended)
                    <span className="block text-xs text-ink-2">AES-256 encryption before anything leaves this computer: Google, or anyone who gets into your Google account, sees only scrambled data. Copies on this computer stay unencrypted so you can always restore here.</span></span>
                </label>
                {cfg.encrypt && !needNewPw && (
                  <p className="pl-6 text-xs text-ink-2">Password saved on this computer, protected by your Windows account.{' '}
                    <button type="button" onClick={() => setPw({ ...pw, changing: true })} className="text-accent underline">Change password</button></p>
                )}
                {needNewPw && (
                  <div className="space-y-2 pl-6">
                    <div className="flex flex-wrap gap-3">
                      <label className="block text-xs"><span className="text-ink-2">{enc.has_password ? 'New password' : 'Password'}</span>
                        <input type="password" autoComplete="new-password" value={pw.password} onChange={(e) => setPw({ ...pw, password: e.target.value })}
                          className="mt-1 block w-56 rounded-lg border border-line bg-surface px-2 py-1.5 text-sm" /></label>
                      <label className="block text-xs"><span className="text-ink-2">Repeat password</span>
                        <input type="password" autoComplete="new-password" value={pw.confirm} onChange={(e) => setPw({ ...pw, confirm: e.target.value })}
                          className="mt-1 block w-56 rounded-lg border border-line bg-surface px-2 py-1.5 text-sm" /></label>
                    </div>
                    {pwProblem && (pw.password || pw.confirm) && <p className="text-xs text-warn">{pwProblem}</p>}
                    <p className="rounded bg-warn-soft px-2 py-1.5 text-xs"><b>Write this password down and keep it somewhere safe, not in Google Drive.</b> Without it the Google Drive copies cannot be opened. Nobody, including Analytivest, can recover it.{enc.has_password ? ' Older copies keep their old password.' : ''}</p>
                  </div>
                )}
                {!enc.available && <p className="pl-6 text-xs text-muted">Needs Windows, which keeps the saved password safe.</p>}
                {d.settings.encrypt && d.gdrive.plain_copies > 0 && (
                  <p className="pl-6 text-xs">{d.gdrive.plain_copies} older unencrypted cop{d.gdrive.plain_copies === 1 ? 'y is' : 'ies are'} still in Google Drive.{' '}
                    <button type="button" disabled={purge.isPending} className="text-accent underline"
                      onClick={() => window.confirm('Delete the unencrypted Analytivest backups from Google Drive? Encrypted copies and the copies on this computer are kept.') && purge.mutate()}>Delete them</button>
                    {' '}(they move to Google Drive's trash; empty it to remove them completely).</p>
                )}
              </div>
            )}

            <div className="flex flex-wrap items-end gap-4">
              <label className="flex items-center gap-2 pb-2"><input type="checkbox" checked={cfg.auto} onChange={(e) => setCfg({ ...cfg, auto: e.target.checked })} /> Weekly automatic backup</label>
              <label className="block text-xs"><span className="text-ink-2">Keep last</span>
                <input type="number" min={1} max={52} value={cfg.keep} onChange={(e) => setCfg({ ...cfg, keep: Number(e.target.value) })}
                  className="mt-1 block w-20 rounded-lg border border-line bg-surface px-2 py-1.5 text-sm" /></label>
              <button onClick={saveSettings} disabled={save.isPending || !!pwProblem} className="mb-0.5 rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white disabled:opacity-60">Save settings</button>
            </div>
            <details className="text-xs">
              <summary className="cursor-pointer text-ink-2">Advanced: local backup folder</summary>
              <input value={cfg.folder} onChange={(e) => setCfg({ ...cfg, folder: e.target.value })} placeholder={d.folder_default}
                aria-label="Local backup folder" className="mt-1 block w-full max-w-xl rounded-lg border border-line bg-surface px-2 py-1.5 text-sm" />
            </details>
          </div>
        )}
        {save.isError && <p role="alert" className="mt-2 text-sm text-neg">{(save.error as Error).message}</p>}
        {save.isSuccess && <p className="mt-2 text-xs text-pos">Settings saved</p>}
        <p className="mt-2 text-xs text-muted">
          Last automatic backup: {d.last_auto ? `${dateTime(d.last_auto)} (${ago(d.last_auto)})` : 'none yet'}
          {d.next_auto ? ` · next due ${dateTime(d.next_auto)}` : ''}. Automatic backups run while the app is open.
          {d.settings.cloud === 'gdrive' && d.gdrive.last && (d.gdrive.last.ok
            ? ` Last Google Drive copy: ${dateTime(d.gdrive.last.at)}.`
            : ` Last Google Drive copy FAILED (${dateTime(d.gdrive.last.at)}): ${d.gdrive.last.message}`)}
        </p>
        {d.settings.cloud === 'gdrive' && !d.settings.encrypt && <p className="mt-1 text-xs text-warn">Google Drive copies are not encrypted: they contain your portfolio and notes as plain JSON, readable by anyone with access to your Google account.</p>}

        <h3 className="mt-4 text-sm font-medium">Saved backups</h3>
        {d.files.length === 0 ? <p className="mt-1 text-sm text-muted">No backups saved yet.</p> : (
          <div className="mt-1 overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead><tr className="border-b border-line text-left text-xs text-muted"><th className="py-1.5 font-normal">Saved</th><th className="font-normal">Where</th><th className="font-normal">Type</th><th className="text-right font-normal">Size</th><th /></tr></thead>
              <tbody>
                {d.files.map((f: any) => (
                  <tr key={`${f.location}/${f.name}`} className="border-b border-line/60">
                    <td className="py-1.5" title={f.name}>{dateTime(f.modified)}</td>
                    <td className="text-ink-2">{f.location === 'gdrive' ? 'Google Drive' : 'This computer'}{f.encrypted && <span className="ml-1.5 inline-flex items-center gap-0.5 text-xs text-pos"><Lock size={11} aria-hidden /> encrypted</span>}</td>
                    <td className="text-ink-2">{f.kind === 'before-restore' ? 'Safety copy (before a restore)' : f.kind === 'manual' ? 'Manual' : 'Automatic'}</td>
                    <td className="num text-right">{size(f.size)}</td>
                    <td className="text-right">
                      <button onClick={() => confirmRestore(`the backup from ${dateTime(f.modified)}`) && restore.mutate({ target: { kind: 'saved', name: f.name, location: f.location } })}
                        disabled={restore.isPending} className="inline-flex items-center gap-1 text-xs text-accent disabled:opacity-50"><RotateCcw size={12} aria-hidden /> Restore</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}
