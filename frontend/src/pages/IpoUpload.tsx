import { useMutation } from '@tanstack/react-query'
import { FileText, FileUp, FlaskConical, Loader2, ShieldCheck } from 'lucide-react'
import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, cx } from '../components/ui'
import { api } from '../lib/api'

function size(n: number) {
  return n > 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`
}

export default function IpoUpload() {
  const nav = useNavigate()
  const input = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [drag, setDrag] = useState(false)
  const upload = useMutation({
    mutationFn: ({ blob, name }: { blob: Blob; name: string }) => api.ipoUpload(blob, name),
    onSuccess: (data) => nav('/ipo/new', { state: { upload: data } }),
  })
  const trySample = async () => {
    const blob = await api.sampleRhp()
    upload.mutate({ blob, name: 'SAMPLE-RHP-fictional-Demo-Precision.pdf' })
  }
  const busy = upload.isPending

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Upload an RHP or DRHP</h1>
        <p className="text-[13px] text-ink-2">
          Analytivest reads the offer document, pulls out the price band, issue structure, restated financials, objects of the issue, peer
          multiples and risk factors, and shows each figure with the page it came from so you can check it. It then gives an
          Apply / Borderline / Skip suggestion with its reasons.
        </p>
      </div>

      <Card>
        <div
          onDragOver={(e) => { e.preventDefault(); setDrag(true) }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files?.[0]; if (f) setFile(f) }}
          className={cx('flex flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors',
            drag ? 'border-accent bg-accent-soft' : 'border-line-strong')}>
          <FileUp size={32} className="text-accent" aria-hidden />
          <p className="mt-2 text-sm font-medium text-ink">Drop the document here, or</p>
          <button type="button" onClick={() => input.current?.click()} disabled={busy}
            className="mt-2 rounded-lg border border-line bg-surface px-3 py-1.5 text-sm font-medium hover:border-accent hover:text-accent">
            Choose a file
          </button>
          {/* No `accept` filter: any format is accepted and identified from its content. */}
          <input ref={input} type="file" className="sr-only" aria-label="Offer document file"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) setFile(f); e.target.value = '' }} />
          <p className="mt-3 max-w-md text-xs text-muted">
            Any format: PDF (text or scanned), Word (DOCX), HTML, TXT, RTF, Excel, EPUB/XPS, images (PNG/JPG/TIFF), ZIP archives, even
            legacy .doc. Best results come from the original PDF published on the SEBI, NSE or BSE website.
          </p>
        </div>

        {file && (
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-lg bg-surface-2 px-3 py-2">
            <span className="inline-flex min-w-0 items-center gap-2 text-sm">
              <FileText size={16} className="shrink-0 text-muted" aria-hidden />
              <span className="truncate font-medium">{file.name}</span>
              <span className="shrink-0 text-xs text-muted">{size(file.size)}</span>
            </span>
            <button onClick={() => upload.mutate({ blob: file, name: file.name })} disabled={busy}
              className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-white disabled:opacity-60">
              {busy ? <Loader2 size={15} className="animate-spin" aria-hidden /> : <FileUp size={15} aria-hidden />}
              {busy ? 'Reading document…' : 'Read & analyse'}
            </button>
          </div>
        )}

        {busy && (
          <p role="status" className="mt-3 text-xs text-muted">
            Extracting text and tables. A 400–600 page RHP usually takes 5–30 seconds; scanned pages need OCR and take longer.
          </p>
        )}
        {upload.isError && (
          <p role="alert" className="mt-3 rounded-lg bg-neg-soft px-3 py-2 text-sm text-neg">{(upload.error as Error).message}</p>
        )}

        <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3">
          <span className="inline-flex items-center gap-1.5 text-xs text-muted"><ShieldCheck size={14} aria-hidden /> Processed on this computer; the file is not sent anywhere else and is not stored.</span>
          <button onClick={trySample} disabled={busy} className="inline-flex items-center gap-1.5 text-xs font-medium text-accent disabled:opacity-50">
            <FlaskConical size={14} aria-hidden /> No RHP handy? Try a fictional sample
          </button>
        </div>
      </Card>

      <Card title="How the suggestion is made">
        <ul className="list-disc space-y-1 pl-5 text-[13px] text-ink-2">
          <li>Five separate assessments: business quality, financial strength, valuation against listed peers, governance & disclosure risk, and IPO-specific risk.</li>
          <li><b>Skip</b> if any deal-breaker applies (loss-making, negative operating cash flow in 2 of 3 years, P/E more than 60% above peers, the base-case value 15%+ below the issue price, high governance risk, or contingent liabilities above half of net worth).</li>
          <li><b>Apply</b> only when the overall score is good, valuation is reasonable, the base case gives at least a 10% margin of safety, peers are available, and there is at most one serious structural concern.</li>
          <li>Everything else is <b>Borderline</b>. Subscription numbers and grey-market premium are ignored on purpose: they measure hype, not value.</li>
        </ul>
      </Card>
    </div>
  )
}
