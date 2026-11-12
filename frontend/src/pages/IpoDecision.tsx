import { CircleCheck, CircleHelp, CircleMinus, CircleX, ChevronDown, FileSearch, Minus, OctagonAlert, Plus } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ScoreBar, cx } from '../components/ui'
import { isNum, price } from '../lib/format'

const META: Record<string, { icon: any; color: string; ring: string }> = {
  APPLY: { icon: CircleCheck, color: 'var(--status-good)', ring: 'border-[color:var(--status-good)]' },
  BORDERLINE: { icon: CircleMinus, color: 'var(--status-warning)', ring: 'border-[color:var(--status-warning)]' },
  SKIP: { icon: CircleX, color: 'var(--status-critical)', ring: 'border-[color:var(--status-critical)]' },
  INSUFFICIENT: { icon: CircleHelp, color: 'var(--muted)', ring: 'border-line-strong' },
}

/** The Apply / Borderline / Skip suggestion with every reason that produced it. */
export function DecisionCard({ d, upperBand, extraction, editHref }: { d: any; upperBand?: number; extraction?: any; editHref?: string }) {
  const [open, setOpen] = useState(false)
  if (!d) return null
  const m = META[d.verdict] || META.INSUFFICIENT
  const Icon = m.icon
  return (
    <section aria-label="Apply or skip suggestion" className={cx('rounded-xl border-2 bg-surface p-4 sm:p-5', m.ring)}>
      <div className="flex flex-wrap items-start gap-4">
        <div className="flex items-center gap-3">
          <Icon size={40} style={{ color: m.color }} aria-hidden />
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-muted">Analytivest suggestion</p>
            <p className="text-xl font-semibold leading-tight">{d.label}</p>
            <p className="mt-0.5 text-xs text-muted">{d.horizon_note}</p>
          </div>
        </div>
        {isNum(d.score) && (
          <div className="ml-auto w-48">
            <div className="flex items-baseline justify-between text-xs text-muted"><span>Decision score</span><span className="num text-base font-semibold text-ink">{d.score.toFixed(0)}/100</span></div>
            <ScoreBar score={d.score} label="Decision score" />
            {isNum(d.fair_entry_price) && isNum(upperBand) && (
              <p className="mt-1.5 text-xs text-muted">Price with a 10% margin of safety in the base case: <b className="num text-ink">{price(d.fair_entry_price)}</b> (upper band {price(upperBand)})</p>
            )}
          </div>
        )}
      </div>

      {d.deal_breakers?.length > 0 && (
        <div className="mt-4 rounded-lg bg-neg-soft p-3">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-neg">Deal-breakers</p>
          <ul className="space-y-1">
            {d.deal_breakers.map((b: string, i: number) => (
              <li key={i} className="flex gap-2 text-[13px] text-ink"><OctagonAlert size={15} className="mt-0.5 shrink-0" style={{ color: 'var(--status-critical)' }} aria-hidden />{b}</li>
            ))}
          </ul>
        </div>
      )}

      {(d.reasons_for?.length > 0 || d.reasons_against?.length > 0) && (
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <div>
            <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted">In favour</p>
            {d.reasons_for.length === 0 ? <p className="text-[13px] text-muted">Nothing stands out.</p> : (
              <ul className="space-y-1.5">{d.reasons_for.map((r: string, i: number) => (
                <li key={i} className="flex gap-2 text-[13px]"><Plus size={15} className="mt-0.5 shrink-0" style={{ color: 'var(--status-good)' }} aria-label="For" />{r}</li>))}</ul>
            )}
          </div>
          <div>
            <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted">Against</p>
            {d.reasons_against.length === 0 ? <p className="text-[13px] text-muted">No major concerns from the figures.</p> : (
              <ul className="space-y-1.5">{d.reasons_against.map((r: string, i: number) => (
                <li key={i} className="flex gap-2 text-[13px]"><Minus size={15} className="mt-0.5 shrink-0" style={{ color: 'var(--status-critical)' }} aria-label="Against" />{r}</li>))}</ul>
            )}
          </div>
        </div>
      )}

      {d.conditions?.length > 0 && (
        <div className="mt-4">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">{d.verdict === 'INSUFFICIENT' ? 'Needed' : 'What would change the picture'}</p>
          <ul className="list-disc space-y-1 pl-5 text-[13px] text-ink-2">{d.conditions.map((c: string, i: number) => <li key={i}>{c}</li>)}</ul>
        </div>
      )}

      {extraction?.document && (
        <p className="mt-4 flex flex-wrap items-center gap-1.5 text-xs text-muted">
          <FileSearch size={13} aria-hidden /> Figures extracted automatically from <b className="text-ink-2">{extraction.document.filename}</b> ({extraction.doc_type},
          {' '}{extraction.document.pages} pages{extraction.document.ocr_pages ? `, ${extraction.document.ocr_pages} via OCR` : ''}).
          {editHref && <Link to={editHref} className="text-accent underline">Review or correct them</Link>}
        </p>
      )}

      <div className="mt-3 border-t border-line pt-3">
        {d.rules && (
          <button onClick={() => setOpen((o) => !o)} aria-expanded={open} className="inline-flex items-center gap-1 text-xs font-medium text-accent">
            How this is decided <ChevronDown size={13} className={cx('transition-transform', open && 'rotate-180')} aria-hidden />
          </button>
        )}
        {open && d.rules && (
          <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-ink-2">
            <li><b>Apply</b> when: {d.rules.apply}.</li>
            <li><b>Skip</b> when: {d.rules.skip}.</li>
            <li>Otherwise <b>Borderline</b>. Score weights: {d.rules.weights}.</li>
            {d.components && <li>Components: {Object.entries(d.components).map(([k, v]: any) => `${k.replace(/_/g, ' ')} ${isNum(v) ? v.toFixed(0) : 'n/a'}`).join(' · ')} (risk shown as 100 − risk).</li>}
          </ul>
        )}
        <p className="mt-2 text-xs text-muted">{d.disclaimer}</p>
      </div>
    </section>
  )
}
