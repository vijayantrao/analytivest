// Number formatting. Indian rupee values use crore / lakh-crore; other currencies use K/M/B.

const CR = 1e7
const isNum = (x: unknown): x is number => typeof x === 'number' && Number.isFinite(x)

export const DASH = '—'

const inGroup = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 })
const inGroup0 = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 })

export function money(v: unknown, currency = 'INR', opts: { compact?: boolean } = {}): string {
  if (!isNum(v)) return DASH
  const sign = v < 0 ? '−' : ''
  const a = Math.abs(v)
  if (currency === 'INR') {
    if (opts.compact === false) return `${sign}₹${inGroup.format(a)}`
    if (a >= 1e5 * CR) return `${sign}₹${(a / (1e5 * CR)).toFixed(2)} L Cr`
    if (a >= CR) return `${sign}₹${inGroup0.format(a / CR)} Cr`
    if (a >= 1e5) return `${sign}₹${(a / 1e5).toFixed(2)} L`
    return `${sign}₹${inGroup.format(a)}`
  }
  const sym = currency === 'USD' ? '$' : `${currency} `
  if (a >= 1e12) return `${sign}${sym}${(a / 1e12).toFixed(2)}T`
  if (a >= 1e9) return `${sign}${sym}${(a / 1e9).toFixed(2)}B`
  if (a >= 1e6) return `${sign}${sym}${(a / 1e6).toFixed(1)}M`
  return `${sign}${sym}${a.toLocaleString('en-US', { maximumFractionDigits: 2 })}`
}

/** Value in crore (for chart axes on INR statements). */
export function toCr(v: unknown): number | null {
  return isNum(v) ? v / CR : null
}

export function price(v: unknown, currency = 'INR'): string {
  if (!isNum(v)) return DASH
  const sym = currency === 'INR' ? '₹' : currency === 'USD' ? '$' : ''
  return `${v < 0 ? '−' : ''}${sym}${Math.abs(v).toLocaleString(currency === 'INR' ? 'en-IN' : 'en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

export function pct(v: unknown, d = 1, signed = false): string {
  if (!isNum(v)) return DASH
  const s = v.toFixed(d)
  return `${signed && v > 0 ? '+' : ''}${s.replace('-', '−')}%`
}

export function ratio(v: unknown, d = 2): string {
  if (!isNum(v)) return DASH
  return `${v.toFixed(d).replace('-', '−')}×`
}

export function num(v: unknown, d = 1): string {
  if (!isNum(v)) return DASH
  return v.toLocaleString('en-IN', { maximumFractionDigits: d, minimumFractionDigits: 0 })
}

/** Format a metric by its unit as defined by the backend's METRIC_DEFS. */
export function byUnit(v: unknown, unit: string | undefined, currency = 'INR'): string {
  switch (unit) {
    case 'pct':
    case '%':
      return pct(v)
    case 'x':
    case '×':
      return ratio(v)
    case 'currency':
      return money(v, currency)
    case 'per_share':
      return price(v, currency)
    case 'days':
      return isNum(v) ? `${v.toFixed(0)} days` : DASH
    case 'pp':
      return isNum(v) ? `${v > 0 ? '+' : ''}${v.toFixed(1)} pp` : DASH
    case 'share':
      return isNum(v) ? `${Math.round(v * 100)}%` : DASH
    case 'pctile':
      return isNum(v) ? `${v.toFixed(0)}th pct.` : DASH
    case 'years':
      return isNum(v) ? `${v.toFixed(0)}` : DASH
    default:
      return num(v, 2)
  }
}

export function ago(epochSeconds: unknown): string {
  if (!isNum(epochSeconds)) return 'unknown'
  const s = Date.now() / 1000 - epochSeconds
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.round(s / 60)} min ago`
  if (s < 86400) return `${Math.round(s / 3600)} h ago`
  return `${Math.round(s / 86400)} d ago`
}

export function dateTime(v: unknown): string {
  if (v == null) return DASH
  const d = typeof v === 'number' ? new Date(v * 1000) : new Date(String(v))
  if (Number.isNaN(d.getTime())) return String(v)
  return d.toLocaleString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export function shortDate(v: unknown): string {
  if (v == null) return DASH
  const d = new Date(String(v))
  if (Number.isNaN(d.getTime())) return String(v)
  return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
}

export { isNum }
