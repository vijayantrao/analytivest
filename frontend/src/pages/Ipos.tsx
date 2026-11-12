import { useQuery } from '@tanstack/react-query'
import { FileUp, Plus } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Badge, Card, ErrorState, Skeleton } from '../components/ui'
import { api } from '../lib/api'
import { shortDate } from '../lib/format'

export default function Ipos() {
  const q = useQuery({ queryKey: ['ipos'], queryFn: api.ipos })
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">IPO analysis</h1>
          <p className="max-w-2xl text-[13px] text-ink-2">
            Upload an offer document (DRHP/RHP from the SEBI, NSE or BSE website) in any format, or enter its figures by hand. Analytivest then works out the issue structure, implied valuation versus
            listed peers, three valuation scenarios and IPO-specific risks.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link to="/ipo/upload" className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white hover:opacity-90"><FileUp size={16} aria-hidden /> Upload RHP/DRHP</Link>
          <Link to="/ipo/new" className="inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-2 text-sm font-medium text-ink-2 hover:bg-surface-2"><Plus size={16} aria-hidden /> Enter manually</Link>
        </div>
      </div>
      {q.isLoading ? <Skeleton className="h-40" /> : q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : (
        <Card>
          <div className="scroll-x">
            <table className="w-full min-w-[640px] text-[13px]">
              <thead><tr className="border-b border-line text-left text-muted">
                <th className="py-2 font-medium">Company</th><th className="py-2 font-medium">Industry</th><th className="py-2 text-right font-medium">Price band</th>
                <th className="py-2 text-right font-medium">Issue size</th><th className="py-2 pl-4 font-medium">Dates</th><th className="py-2 font-medium">Status</th></tr></thead>
              <tbody>
                {q.data.items.map((i: any) => (
                  <tr key={i.id} className="border-b border-line/60">
                    <td className="py-2"><Link to={`/ipo/${i.id}`} className="font-medium hover:text-accent">{i.name}</Link></td>
                    <td className="py-2 text-ink-2">{i.industry || '—'}</td>
                    <td className="num py-2 text-right">₹{i.price_band[0]}–{i.price_band[1]}</td>
                    <td className="num py-2 text-right">₹{Number(i.issue_size_cr).toLocaleString('en-IN')} Cr</td>
                    <td className="py-2 pl-4 text-xs text-muted">{i.open_date ? `${shortDate(i.open_date)} – ${shortDate(i.close_date)}` : '—'}{i.listing_date && ` · lists ${shortDate(i.listing_date)}`}</td>
                    <td className="py-2">{i.is_sample ? <Badge tone="warn">Sample</Badge> : <Badge>{i.status || 'entered'}</Badge>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-muted">{q.data.note}</p>
        </Card>
      )}
    </div>
  )
}
