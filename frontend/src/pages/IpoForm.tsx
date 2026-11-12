import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CircleCheck, FileSearch, Info, Plus, Trash2 } from 'lucide-react'
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { Badge, Card, PageSkeleton, Tip } from '../components/ui'
import { api } from '../lib/api'

const FIN_FIELDS = [
  ['revenue_cr', 'Revenue'], ['ebitda_cr', 'EBITDA'], ['pat_cr', 'PAT'], ['net_worth_cr', 'Net worth'],
  ['borrowings_cr', 'Borrowings'], ['cfo_cr', 'CFO'], ['capex_cr', 'Capex'],
] as const

const empty = {
  company_name: '', industry: '', sector: '', exchange: 'NSE, BSE', status: 'upcoming', business_summary: '',
  price_band_low: '', price_band_high: '', lot_size: '', face_value: '', fresh_issue_cr: '', ofs_cr: '',
  pre_issue_shares_cr: '', post_issue_shares_cr: '', promoter_pre_pct: '', promoter_post_pct: '',
  open_date: '', close_date: '', listing_date: '', cash_cr: '', top_customer_concentration_pct: '',
  contingent_liabilities_cr: '', litigation_notes: '', risk_text: '', peers_text: '', source_note: '',
  sub_qib: '', sub_nii: '', sub_retail: '', sub_total: '', sub_asof: '', gmp_value: '', gmp_asof: '',
  financials: [{ fy: 'FY2024' }, { fy: 'FY2025' }, { fy: 'FY2026' }] as any[],
  use_of_proceeds: [] as any[], manual_peers: [] as any[],
}

const n = (v: any) => (v === '' || v == null ? undefined : Number(v))

/** Evidence from an RHP upload: page, snippet and confidence for each extracted field. */
const EvCtx = createContext<Record<string, any> | null>(null)

function EvChip({ k }: { k: string }) {
  const ev = useContext(EvCtx)
  if (!ev) return null
  const e = ev[k]
  if (!e) return <span className="ml-1 rounded bg-warn-soft px-1 py-px text-[10px] font-medium text-warn">not found: enter it</span>
  const Icon = e.confidence === 'high' ? CircleCheck : e.confidence === 'low' ? AlertTriangle : Info
  const color = e.confidence === 'high' ? 'var(--status-good)' : e.confidence === 'low' ? 'var(--status-serious)' : 'var(--muted)'
  return (
    <Tip wide label={`Source for this field: page ${e.page ?? 'n/a'}`} content={
      <span className="block space-y-1">
        <span className="block"><b className="text-ink">Page {e.page ?? '–'}</b> · {e.confidence} confidence</span>
        {e.snippet && <span className="block rounded bg-surface-2 px-1.5 py-1 italic">“{e.snippet}”</span>}
        {e.note && <span className="block text-muted">{e.note}</span>}
      </span>}>
      <span className="ml-1 inline-flex items-center gap-0.5 rounded bg-surface-2 px-1 py-px text-[10px] font-medium text-ink-2">
        <Icon size={10} style={{ color }} aria-hidden /> p.{e.page ?? '–'}
      </span>
    </Tip>
  )
}

function Field({ label, children, hint, wide, ev }: { label: string; children: ReactNode; hint?: string; wide?: boolean; ev?: string }) {
  return (
    <label className={wide ? 'col-span-2 block text-xs sm:col-span-4' : 'block text-xs'}>
      <span className="text-ink-2">{label}{ev && <EvChip k={ev} />}</span>
      <div className="mt-1">{children}</div>
      {hint && <span className="mt-0.5 block text-[11px] text-muted">{hint}</span>}
    </label>
  )
}
const inputCls = 'w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-sm outline-none focus:border-accent'

export default function IpoForm() {
  const { id } = useParams()
  const nav = useNavigate()
  const qc = useQueryClient()
  const existing = useQuery({ queryKey: ['ipo', id], queryFn: () => api.ipo(id!), enabled: !!id })
  const upload = (useLocation().state as any)?.upload
  const [f, setF] = useState<any>(empty)

  const toForm = (p: any) => ({
      ...empty, ...Object.fromEntries(Object.entries(p).map(([k, v]) => [k, v ?? ''])),
      pre_issue_shares_cr: p.pre_issue_shares ? p.pre_issue_shares / 1e7 : '',
      post_issue_shares_cr: p.post_issue_shares ? p.post_issue_shares / 1e7 : '',
      risk_text: (p.risk_factors || []).join('\n'), peers_text: (p.peers || []).join(', '),
      sub_qib: p.subscription?.qib ?? '', sub_nii: p.subscription?.nii ?? '', sub_retail: p.subscription?.retail ?? '',
      sub_total: p.subscription?.total ?? '', sub_asof: p.subscription?.as_of ?? '',
      gmp_value: p.gmp?.value ?? '', gmp_asof: p.gmp?.as_of ?? '',
      financials: p.financials?.length ? p.financials : empty.financials,
      use_of_proceeds: p.use_of_proceeds || [], manual_peers: p.manual_peers || [],
  })

  useEffect(() => {
    const p = existing.data?.payload
    if (p) setF(toForm(p))
  }, [existing.data])

  useEffect(() => {
    if (!upload || id) return
    const form = toForm(upload.draft)
    if (upload.peer_suggestions?.length) form.peers_text = upload.peer_suggestions.map((x: any) => x.symbol).join(', ')
    setF(form)
  }, [upload, id])

  const extraction = upload && !id
    ? { document: upload.document, doc_type: upload.doc_type, evidence: upload.evidence, warnings: upload.warnings, coverage: upload.coverage }
    : existing.data?.payload?.extraction

  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value })
  const save = useMutation({
    mutationFn: () => {
      const sub = { qib: n(f.sub_qib), nii: n(f.sub_nii), retail: n(f.sub_retail), total: n(f.sub_total), as_of: f.sub_asof || undefined }
      const body = {
        company_name: f.company_name, industry: f.industry || undefined, sector: f.sector || undefined, exchange: f.exchange || undefined,
        status: f.status || undefined, business_summary: f.business_summary || undefined,
        price_band_low: n(f.price_band_low), price_band_high: n(f.price_band_high), lot_size: n(f.lot_size), face_value: n(f.face_value),
        fresh_issue_cr: n(f.fresh_issue_cr) ?? 0, ofs_cr: n(f.ofs_cr) ?? 0,
        pre_issue_shares: n(f.pre_issue_shares_cr) != null ? Number(f.pre_issue_shares_cr) * 1e7 : undefined,
        post_issue_shares: n(f.post_issue_shares_cr) != null ? Number(f.post_issue_shares_cr) * 1e7 : undefined,
        promoter_pre_pct: n(f.promoter_pre_pct), promoter_post_pct: n(f.promoter_post_pct),
        open_date: f.open_date || undefined, close_date: f.close_date || undefined, listing_date: f.listing_date || undefined,
        cash_cr: n(f.cash_cr), top_customer_concentration_pct: n(f.top_customer_concentration_pct),
        contingent_liabilities_cr: n(f.contingent_liabilities_cr), litigation_notes: f.litigation_notes || undefined,
        risk_factors: f.risk_text.split('\n').map((s: string) => s.trim()).filter(Boolean),
        peers: f.peers_text.split(/[,\s]+/).map((s: string) => s.trim().toUpperCase()).filter(Boolean),
        financials: f.financials.filter((r: any) => r.fy).map((r: any) => Object.fromEntries(Object.entries(r).map(([k, v]) => [k, k === 'fy' ? v : n(v)]))),
        use_of_proceeds: f.use_of_proceeds.filter((u: any) => u.purpose && u.amount_cr !== '').map((u: any) => ({ purpose: u.purpose, amount_cr: Number(u.amount_cr) })),
        manual_peers: f.manual_peers.filter((m: any) => m.name).map((m: any) => ({ name: m.name, pe: n(m.pe), ev_ebitda: n(m.ev_ebitda), pb: n(m.pb), roe: n(m.roe) })),
        subscription: Object.values(sub).some((v) => v != null) ? sub : undefined,
        gmp: n(f.gmp_value) != null ? { value: n(f.gmp_value), as_of: f.gmp_asof || undefined, source: 'User-entered (unofficial)' } : undefined,
        source_note: f.source_note || undefined,
        extraction: extraction || undefined,
      }
      return id ? api.ipoUpdate(id, body).then(() => ({ id })) : api.ipoCreate(body)
    },
    onSuccess: (d: any) => {
      qc.invalidateQueries({ queryKey: ['ipos'] })
      qc.invalidateQueries({ queryKey: ['ipo-analysis', d.id] })
      nav(`/ipo/${d.id}`)
    },
  })

  if (id && existing.isLoading) return <PageSkeleton />
  const rowSet = (list: string, i: number, k: string) => (e: any) => {
    const arr = [...f[list]]
    arr[i] = { ...arr[i], [k]: e.target.value }
    setF({ ...f, [list]: arr })
  }
  const addRow = (list: string, row: any) => setF({ ...f, [list]: [...f[list], row] })
  const delRow = (list: string, i: number) => setF({ ...f, [list]: f[list].filter((_: any, j: number) => j !== i) })

  return (
    <EvCtx.Provider value={upload && !id ? upload.evidence : null}>
    <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
      <div>
        <h1 className="text-xl font-semibold">{id ? 'Edit IPO' : upload ? 'Review the extracted figures' : 'New IPO from offer document'}</h1>
        {!upload && <p className="text-[13px] text-ink-2">Copy figures from the RHP/DRHP (SEBI → Filings → Public issues, or the exchange IPO pages). Amounts in ₹ crore. Only the price band, pre-issue shares and at least one year of financials are required for valuation.</p>}
        {upload && !id && <UploadSummary u={upload} />}
      </div>
      <Card title="Company & issue">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Field label="Company name *" wide ev="company_name"><input required minLength={2} className={inputCls} value={f.company_name} onChange={set('company_name')} /></Field>
          <Field label="Industry"><input className={inputCls} value={f.industry} onChange={set('industry')} /></Field>
          <Field label="Exchange(s)"><input className={inputCls} value={f.exchange} onChange={set('exchange')} /></Field>
          <Field label="Price band low (₹) *" ev="price_band_low"><input required type="number" step="any" min={0} className={inputCls} value={f.price_band_low} onChange={set('price_band_low')} /></Field>
          <Field label="Price band high (₹) *" ev="price_band_high"><input required type="number" step="any" min={0} className={inputCls} value={f.price_band_high} onChange={set('price_band_high')} /></Field>
          <Field label="Lot size (shares)" ev="lot_size"><input type="number" min={1} className={inputCls} value={f.lot_size} onChange={set('lot_size')} /></Field>
          <Field label="Face value (₹)" ev="face_value"><input type="number" step="any" className={inputCls} value={f.face_value} onChange={set('face_value')} /></Field>
          <Field label="Fresh issue (₹ Cr)" ev="fresh_issue_cr"><input type="number" step="any" min={0} className={inputCls} value={f.fresh_issue_cr} onChange={set('fresh_issue_cr')} /></Field>
          <Field label="Offer for sale (₹ Cr)" ev="ofs_cr"><input type="number" step="any" min={0} className={inputCls} value={f.ofs_cr} onChange={set('ofs_cr')} /></Field>
          <Field label="Pre-issue shares (crore) *" hint="e.g. 10.5 = 10.5 crore shares" ev="pre_issue_shares"><input required type="number" step="any" min={0} className={inputCls} value={f.pre_issue_shares_cr} onChange={set('pre_issue_shares_cr')} /></Field>
          <Field label="Post-issue shares (crore)" hint="Optional; computed if blank" ev="post_issue_shares"><input type="number" step="any" min={0} className={inputCls} value={f.post_issue_shares_cr} onChange={set('post_issue_shares_cr')} /></Field>
          <Field label="Promoter holding pre (%)" ev="promoter_pre_pct"><input type="number" step="any" min={0} max={100} className={inputCls} value={f.promoter_pre_pct} onChange={set('promoter_pre_pct')} /></Field>
          <Field label="Promoter holding post (%)" ev="promoter_post_pct"><input type="number" step="any" min={0} max={100} className={inputCls} value={f.promoter_post_pct} onChange={set('promoter_post_pct')} /></Field>
          <Field label="Opens" ev="open_date"><input type="date" className={inputCls} value={f.open_date} onChange={set('open_date')} /></Field>
          <Field label="Closes" ev="close_date"><input type="date" className={inputCls} value={f.close_date} onChange={set('close_date')} /></Field>
          <Field label="Listing date"><input type="date" className={inputCls} value={f.listing_date} onChange={set('listing_date')} /></Field>
          <Field label="Cash before issue (₹ Cr)" ev="cash_cr"><input type="number" step="any" min={0} className={inputCls} value={f.cash_cr} onChange={set('cash_cr')} /></Field>
        </div>
      </Card>

      <Card title={<span>Restated financials (₹ Cr)<EvChip k="financials" /></span>} actions={<button type="button" onClick={() => addRow('financials', { fy: '' })} className="inline-flex items-center gap-1 text-xs text-accent"><Plus size={13} aria-hidden /> Year</button>}>
        <div className="scroll-x">
          <table className="w-full min-w-[720px] text-xs">
            <thead><tr className="text-left text-muted"><th className="py-1 pr-2 font-medium">FY</th>{FIN_FIELDS.map(([, l]) => <th key={l} className="py-1 pr-2 font-medium">{l}</th>)}<th /></tr></thead>
            <tbody>
              {f.financials.map((r: any, i: number) => (
                <tr key={i}>
                  <td className="py-1 pr-2"><input aria-label="Fiscal year" className={inputCls} value={r.fy ?? ''} onChange={rowSet('financials', i, 'fy')} /></td>
                  {FIN_FIELDS.map(([k, l]) => <td key={k} className="py-1 pr-2"><input aria-label={`${l} ${r.fy}`} type="number" step="any" className={inputCls} value={r[k] ?? ''} onChange={rowSet('financials', i, k)} /></td>)}
                  <td><button type="button" aria-label="Remove year" onClick={() => delRow('financials', i)} className="p-1 text-muted hover:text-neg"><Trash2 size={14} /></button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-1 text-[11px] text-muted">Oldest first. Use full fiscal years; stub periods (e.g. 6 months) distort growth and multiples.</p>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={<span>Use of proceeds (fresh issue)<EvChip k="use_of_proceeds" /></span>} actions={<button type="button" onClick={() => addRow('use_of_proceeds', { purpose: '', amount_cr: '' })} className="inline-flex items-center gap-1 text-xs text-accent"><Plus size={13} aria-hidden /> Item</button>}>
          {f.use_of_proceeds.map((u: any, i: number) => (
            <div key={i} className="mb-2 flex gap-2">
              <input aria-label="Purpose" placeholder="Purpose, e.g. Repayment of borrowings" className={inputCls} value={u.purpose} onChange={rowSet('use_of_proceeds', i, 'purpose')} />
              <input aria-label="Amount ₹ Cr" placeholder="₹ Cr" type="number" step="any" className={`${inputCls} w-28`} value={u.amount_cr} onChange={rowSet('use_of_proceeds', i, 'amount_cr')} />
              <button type="button" aria-label="Remove" onClick={() => delRow('use_of_proceeds', i)} className="p-1 text-muted hover:text-neg"><Trash2 size={14} /></button>
            </div>
          ))}
          {f.use_of_proceeds.length === 0 && <p className="text-xs text-muted">Name general corporate purposes exactly so the 25% check works.</p>}
        </Card>
        <Card title={<span>Peers<EvChip k="manual_peers" /></span>}>
          <Field label="Listed peer symbols (from the RHP's peer table)" hint="Comma-separated, e.g. TCS.NS, INFY.NS. Their multiples are fetched from the provider."><input className={inputCls} value={f.peers_text} onChange={set('peers_text')} /></Field>
          <div className="mt-3 flex items-center justify-between"><span className="text-xs text-ink-2">Or enter peer multiples manually</span>
            <button type="button" onClick={() => addRow('manual_peers', { name: '', pe: '', ev_ebitda: '', pb: '', roe: '' })} className="inline-flex items-center gap-1 text-xs text-accent"><Plus size={13} aria-hidden /> Peer</button></div>
          {f.manual_peers.map((m: any, i: number) => (
            <div key={i} className="mt-2 grid grid-cols-[2fr_1fr_1fr_1fr_1fr_auto] gap-1.5">
              <input aria-label="Peer name" placeholder="Name" className={inputCls} value={m.name} onChange={rowSet('manual_peers', i, 'name')} />
              {(['pe', 'ev_ebitda', 'pb', 'roe'] as const).map((k) => <input key={k} aria-label={k} placeholder={k === 'pe' ? 'P/E' : k === 'pb' ? 'P/B' : k === 'roe' ? 'ROE %' : 'EV/EBITDA'} type="number" step="any" className={inputCls} value={m[k]} onChange={rowSet('manual_peers', i, k)} />)}
              <button type="button" aria-label="Remove peer" onClick={() => delRow('manual_peers', i)} className="p-1 text-muted hover:text-neg"><Trash2 size={14} /></button>
            </div>
          ))}
        </Card>
      </div>

      <Card title="Risks, disclosures & market data">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Field label="Top-customer concentration (%)" ev="top_customer_concentration_pct"><input type="number" step="any" min={0} max={100} className={inputCls} value={f.top_customer_concentration_pct} onChange={set('top_customer_concentration_pct')} /></Field>
          <Field label="Contingent liabilities (₹ Cr)" ev="contingent_liabilities_cr"><input type="number" step="any" min={0} className={inputCls} value={f.contingent_liabilities_cr} onChange={set('contingent_liabilities_cr')} /></Field>
          <Field label="Litigation summary" wide ev="litigation_notes"><textarea rows={2} className={inputCls} value={f.litigation_notes} onChange={set('litigation_notes')} /></Field>
          <Field label="Key risk factors (one per line)" wide ev="risk_factors"><textarea rows={4} className={inputCls} value={f.risk_text} onChange={set('risk_text')} /></Field>
          <Field label="Subscription QIB (×)"><input type="number" step="any" className={inputCls} value={f.sub_qib} onChange={set('sub_qib')} /></Field>
          <Field label="Subscription NII (×)"><input type="number" step="any" className={inputCls} value={f.sub_nii} onChange={set('sub_nii')} /></Field>
          <Field label="Subscription Retail (×)"><input type="number" step="any" className={inputCls} value={f.sub_retail} onChange={set('sub_retail')} /></Field>
          <Field label="Subscription Total (×)"><input type="number" step="any" className={inputCls} value={f.sub_total} onChange={set('sub_total')} /></Field>
          <Field label="Subscription as of"><input className={inputCls} value={f.sub_asof} onChange={set('sub_asof')} /></Field>
          <Field label="GMP ₹ (unofficial, optional)" hint="Speculative; never used as a reason to invest"><input type="number" step="any" className={inputCls} value={f.gmp_value} onChange={set('gmp_value')} /></Field>
          <Field label="GMP as of"><input className={inputCls} value={f.gmp_asof} onChange={set('gmp_asof')} /></Field>
          <Field label="Source note" hint="e.g. RHP dated …, page …"><input className={inputCls} value={f.source_note} onChange={set('source_note')} /></Field>
        </div>
      </Card>

      {save.isError && <p role="alert" className="text-sm text-neg">{(save.error as Error).message}</p>}
      <div className="flex gap-2">
        <button type="submit" disabled={save.isPending} className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50">{save.isPending ? 'Saving…' : upload && !id ? 'Confirm figures & get suggestion' : 'Save & analyse'}</button>
        <button type="button" onClick={() => nav(-1)} className="rounded-lg border border-line px-4 py-2 text-sm">Cancel</button>
      </div>
    </form>
    </EvCtx.Provider>
  )
}

const FIELD_NAMES: Record<string, string> = {
  company_name: 'company name', price_band_low: 'price band (low)', price_band_high: 'price band (high)',
  pre_issue_shares: 'pre-issue shares', financials: 'restated financials', fresh_issue_cr: 'fresh issue size', ofs_cr: 'OFS size',
  lot_size: 'lot size', use_of_proceeds: 'use of proceeds', manual_peers: 'peer multiples', risk_factors: 'risk factors',
  promoter_pre_pct: 'promoter holding (pre)', promoter_post_pct: 'promoter holding (post)',
  top_customer_concentration_pct: 'customer concentration', contingent_liabilities_cr: 'contingent liabilities', open_date: 'issue dates',
}

function UploadSummary({ u }: { u: any }) {
  const d = u.document
  return (
    <div className="mt-3 space-y-2 rounded-xl border border-line bg-surface p-4">
      <div className="flex flex-wrap items-center gap-2 text-[13px]">
        <FileSearch size={16} className="text-accent" aria-hidden />
        <b className="truncate">{d.filename}</b>
        <Badge tone="accent">{u.doc_type}</Badge>
        <Badge>{d.kind.toUpperCase()} · {d.pages} {d.kind === 'pdf' ? 'pages' : 'sections'}</Badge>
        {d.ocr_pages > 0 && <Badge tone="warn">{d.ocr_pages} page(s) via OCR</Badge>}
        <Badge tone={u.coverage >= 0.75 ? 'pos' : u.coverage >= 0.5 ? 'warn' : 'neg'}>{Math.round(u.coverage * 100)}% of key fields found</Badge>
      </div>
      <p className="text-[13px] text-ink-2">
        {u.note} Hover the <span className="rounded bg-surface-2 px-1 text-[11px]">p.N</span> chip beside a field to see the text it was read from.
      </p>
      {u.missing_required?.length > 0 && (
        <p className="text-[13px] font-medium text-warn">Required but not found: {u.missing_required.map((k: string) => FIELD_NAMES[k] || k).join(', ')}. Enter these before saving.</p>
      )}
      {u.missing?.filter((k: string) => !u.missing_required.includes(k)).length > 0 && (
        <p className="text-xs text-muted">Also not found (optional): {u.missing.filter((k: string) => !u.missing_required.includes(k)).map((k: string) => FIELD_NAMES[k] || k).join(', ')}.</p>
      )}
      {u.warnings?.length > 0 && (
        <ul className="space-y-1">
          {u.warnings.map((w: string, i: number) => (
            <li key={i} className="flex items-start gap-1.5 text-xs text-ink-2"><AlertTriangle size={13} className="mt-0.5 shrink-0" style={{ color: 'var(--status-serious)' }} aria-hidden />{w}</li>
          ))}
        </ul>
      )}
      {u.peer_suggestions?.length > 0 && (
        <p className="text-xs text-muted">Peers matched to listed symbols: {u.peer_suggestions.map((x: any) => `${x.name} → ${x.symbol}`).join('; ')}. Their current multiples will be fetched live.</p>
      )}
    </div>
  )
}
