// Thin typed client for the FastAPI backend. Analysis payloads are large and evolve with the
// engine, so they are typed loosely (`any`) at the boundary and read defensively in components.

export class ApiError extends Error {
  status: number
  code: string
  retryable: boolean
  constructor(status: number, code: string, message: string, retryable = true) {
    super(message)
    this.status = status
    this.code = code
    this.retryable = retryable
  }
}

// Every API call carries a random per-start session token that only this app's own pages can read
// (it blocks other websites from using the local server). A restarted server issues a new token,
// so a 401 refreshes it once and retries.
let tokenPromise: Promise<string> | null = null
function sessionToken(refresh = false): Promise<string> {
  if (!tokenPromise || refresh) {
    tokenPromise = fetch('/api/session', { cache: 'no-store' })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(r.statusText))))
      .then((b) => b.token as string)
    tokenPromise.catch(() => { tokenPromise = null })
  }
  return tokenPromise
}

const NETWORK_ERROR = 'Cannot reach the Analytivest server. Is the backend running?'

async function send(path: string, init?: RequestInit, retry = true): Promise<Response> {
  let res: Response
  try {
    const token = await sessionToken()
    res = await fetch(path, { ...init, headers: { ...(init?.headers || {}), 'X-Analytivest-Token': token } })
  } catch {
    throw new ApiError(0, 'network', NETWORK_ERROR)
  }
  if (res.status === 401 && retry) {
    try { await sessionToken(true) } catch { throw new ApiError(0, 'network', NETWORK_ERROR) }
    return send(path, init, false)
  }
  return res
}

async function sendForm(path: string, file: File | Blob, filename: string, fields: Record<string, string> = {}) {
  const fd = new FormData()
  fd.append('file', file, filename)
  for (const [k, v] of Object.entries(fields)) fd.append(k, v)
  const res = await send(path, { method: 'POST', body: fd })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new ApiError(res.status, body.error || 'error', body.detail || body.message || res.statusText, false)
  return body as any
}

/** GET a file from the API (with the session token) as a Blob. */
async function blob(path: string): Promise<Blob> {
  const res = await send(path)
  if (!res.ok) throw new ApiError(res.status, 'error', res.statusText, false)
  return res.blob()
}

/** Fetch a file from the API (GET, or the given request) and hand it to the browser as a download. */
async function download(path: string, fallbackName: string, init?: RequestInit): Promise<void> {
  const res = await send(path, init)
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new ApiError(res.status, body.error || 'error', body.detail || body.message || res.statusText, false)
  }
  const name = /filename="([^"]+)"/.exec(res.headers.get('Content-Disposition') || '')?.[1] || fallbackName
  const url = URL.createObjectURL(await res.blob())
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await send(path, { ...init, headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) } })
  if (!res.ok) {
    let body: any = {}
    try {
      body = await res.json()
    } catch {
      /* non-JSON error */
    }
    const detail = Array.isArray(body.detail)
      ? body.detail.map((d: any) => `${(d.loc || []).slice(1).join('.')}: ${d.msg}`).join('; ')
      : body.detail
    throw new ApiError(res.status, body.error || 'error', body.message || detail || res.statusText,
      body.retryable ?? res.status >= 500)
  }
  return res.json() as Promise<T>
}

export type Analysis = any
export type IpoAnalysis = any

export interface SearchGroup {
  name: string
  sector?: string
  industry?: string
  market?: string
  is_sample?: boolean
  primary_symbol: string
  duplicate_listings: boolean
  listings: { symbol: string; exchange?: string }[]
}

export type Market = 'IN' | 'US'

export interface BackupSettings {
  auto: boolean
  folder: string
  keep: number
  cloud: 'none' | 'gdrive'
  gdrive_path: string
  encrypt: boolean
  password?: string // only sent when setting or changing it
}

export const api = {
  health: () => request<any>('/api/health'),
  search: (q: string) => request<{ results: SearchGroup[]; errors: string[] }>(`/api/search?q=${encodeURIComponent(q)}`),
  analysis: (symbol: string, refresh = false) =>
    request<Analysis>(`/api/company/${encodeURIComponent(symbol)}/analysis${refresh ? '?refresh=true' : ''}`),
  prices: (symbol: string, range: string) =>
    request<any>(`/api/company/${encodeURIComponent(symbol)}/prices?range=${range}`),
  dcf: (symbol: string, body: Record<string, number>) =>
    request<any>(`/api/company/${encodeURIComponent(symbol)}/dcf`, { method: 'POST', body: JSON.stringify(body) }),
  saveNotes: (symbol: string, body: any) =>
    request<any>(`/api/company/${encodeURIComponent(symbol)}/notes`, { method: 'PUT', body: JSON.stringify(body) }),
  compare: (symbols: string[]) => request<any>(`/api/compare?symbols=${symbols.map(encodeURIComponent).join(',')}`),
  watchlist: (details = false) => request<any>(`/api/watchlist${details ? '?details=true' : ''}`),
  watchAdd: (symbol: string) => request<any>('/api/watchlist', { method: 'POST', body: JSON.stringify({ symbol }) }),
  watchRemove: (symbol: string) => request<any>(`/api/watchlist/${encodeURIComponent(symbol)}`, { method: 'DELETE' }),
  saved: () => request<any>('/api/saved'),
  savedGet: (id: number) => request<any>(`/api/saved/${id}`),
  saveAnalysis: (symbol: string, label?: string) =>
    request<any>('/api/saved', { method: 'POST', body: JSON.stringify({ symbol, label }) }),
  savedDelete: (id: number) => request<any>(`/api/saved/${id}`, { method: 'DELETE' }),
  ipos: () => request<any>('/api/ipos'),
  ipo: (id: string) => request<any>(`/api/ipos/${encodeURIComponent(id)}`),
  ipoAnalysis: (id: string) => request<IpoAnalysis>(`/api/ipos/${encodeURIComponent(id)}/analysis`),
  ipoCreate: (body: any) => request<{ id: string }>('/api/ipos', { method: 'POST', body: JSON.stringify(body) }),
  ipoUpdate: (id: string, body: any) =>
    request<any>(`/api/ipos/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(body) }),
  ipoDelete: (id: string) => request<any>(`/api/ipos/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  ipoUpload: (file: File | Blob, filename: string) => sendForm('/api/ipos/upload', file, filename),
  sampleRhp: () => blob('/api/ipos/sample-rhp'),
  upload: (path: string, file: File | Blob, filename: string) => sendForm(path, file, filename),
  exportCsv: (symbol: string) => download(`/api/company/${encodeURIComponent(symbol)}/export.csv`, `${symbol}.csv`),
  summary: (symbol: string) => request<any>(`/api/company/${encodeURIComponent(symbol)}/summary`),
  importDelete: (symbol: string) => request<any>(`/api/company/${encodeURIComponent(symbol)}/import`, { method: 'DELETE' }),
  portfolio: () => request<any>('/api/portfolio'),
  holdingAdd: (symbol: string, quantity: number, avg_cost?: number) =>
    request<any>('/api/portfolio', { method: 'POST', body: JSON.stringify({ symbol, quantity, avg_cost }) }),
  holdingRemove: (symbol: string) => request<any>(`/api/portfolio/${encodeURIComponent(symbol)}`, { method: 'DELETE' }),
  portfolioClear: () => request<any>('/api/portfolio', { method: 'DELETE' }),
  alerts: () => request<any>('/api/alerts'),
  alertsCount: () => request<{ unread: number }>('/api/alerts/count'),
  alertsRead: (ids?: number[]) => request<any>('/api/alerts/read', { method: 'POST', body: JSON.stringify({ ids }) }),
  alertsCheck: () => request<{ job_id: string }>('/api/alerts/check', { method: 'POST' }),
  alertsSettings: (enabled: boolean, time: string, time_us: string | null) =>
    request<any>('/api/alerts/settings', { method: 'PUT', body: JSON.stringify({ enabled, time, time_us }) }),
  job: (id: string) => request<any>(`/api/jobs/${encodeURIComponent(id)}`),
  screener: (market: Market = 'IN') => request<any>(`/api/screener?market=${market}`),
  scan: (size: number, include_peers: boolean, market: Market = 'IN') =>
    request<{ job_id: string }>('/api/screener/scan', { method: 'POST', body: JSON.stringify({ size, include_peers, market }) }),
  fx: (pair: string) => request<{ pair: string; rate: number; as_of: string; source: string }>(`/api/fx?pair=${pair}`),
  scanCancel: () => request<any>('/api/screener/cancel', { method: 'POST' }),
  backupStatus: () => request<any>('/api/backup/status'),
  backupDownload: () => download('/api/backup', 'analytivest-backup.json'),
  backupDownloadEncrypted: (password?: string) =>
    download('/api/backup/encrypted', 'analytivest-backup.enc.json',
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password }) }),
  backupRun: () => request<any>('/api/backup/run', { method: 'POST' }),
  backupSettings: (body: BackupSettings) =>
    request<any>('/api/backup/settings', { method: 'PUT', body: JSON.stringify(body) }),
  backupRestore: (file: File, password?: string) =>
    sendForm('/api/backup/restore', file, file.name, password ? { password } : {}),
  backupRestoreFile: (name: string, location: 'local' | 'gdrive', password?: string) =>
    request<any>('/api/backup/restore-file', { method: 'POST', body: JSON.stringify({ name, location, password }) }),
  backupPurgePlainCloud: () => request<{ deleted: number }>('/api/backup/purge-plain-cloud', { method: 'POST' }),
  mlAnomalies: (market: Market = 'IN') => request<any>(`/api/ml/anomalies?market=${market}`),
  companyAnomaly: (symbol: string) => request<any>(`/api/company/${encodeURIComponent(symbol)}/anomaly`),
  methodology: () => request<any>('/api/methodology'),
  glossary: () => request<any>('/api/glossary'),
}
