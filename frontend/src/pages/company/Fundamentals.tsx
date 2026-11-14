import { useState } from 'react'
import { Link } from 'react-router-dom'
import { SeriesChart } from '../../components/charts'
import { Card, EmptyState, Segmented, Term, Tip } from '../../components/ui'
import { byUnit, isNum, pct } from '../../lib/format'
import { ImportPanel, QuarterlyCard } from './Extras'
import { type A, FinancialNotice, KV, MetricValue, pctFmt, rowsFrom, scaleFor, xFmt } from './shared'

const STMT_TITLES: Record<string, string> = { income: 'Profit & loss', balance: 'Balance sheet', cashflow: 'Cash flow' }

export function Financials({ a }: { a: A }) {
  const [freq, setFreq] = useState<'annual' | 'quarterly'>('annual')
  const cur = a.quote.currency
  const sc = scaleFor(cur)
  const st = a.statements[freq]
  const fmtCell = (v: number | null, kind: string) => {
    if (!isNum(v)) return '—'
    if (kind === 'per_share') return v.toFixed(2)
    if (kind === 'shares') return `${(v / 1e7).toLocaleString('en-IN', { maximumFractionDigits: 1 })} Cr`
    return Math.round(v / sc.div).toLocaleString(cur === 'INR' ? 'en-IN' : 'en-US')
  }
  const notes = (st.notes || []).map((n: string[], i: number) => (n.length ? `${st.labels[i]}: ${n.join(' ')}` : null)).filter(Boolean)
  return (
    <div className="space-y-4">
      {a.market?.code !== 'US' && <ImportPanel a={a} />}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[13px] text-ink-2">Figures as reported by the provider, in <b>{sc.unit}</b> (per-share values in {cur}; share counts in crore). Consolidated where the provider reports it.</p>
        <Segmented label="Frequency" value={freq} onChange={setFreq} options={[{ value: 'annual', label: 'Annual' }, { value: 'quarterly', label: 'Quarterly' }]} />
      </div>
      {st.labels.length === 0 ? <EmptyState title={`No ${freq} statements available from the provider`} /> :
        (['income', 'balance', 'cashflow'] as const).map((k) => (
          <Card key={k} title={STMT_TITLES[k]}>
            {st.rows[k].length === 0 ? <p className="text-sm text-muted">Not reported for {freq} periods.</p> : (
              <div className="scroll-x">
                <table className="w-full min-w-[560px] text-[13px]">
                  <thead>
                    <tr className="border-b border-line text-muted">
                      <th className="sticky left-0 bg-surface py-2 pr-4 text-left font-medium">Line item</th>
                      {st.labels.map((l: string, i: number) => <th key={i} className="py-2 pl-3 text-right font-medium" title={st.period_ends[i]}>{l}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {st.rows[k].map((r: any) => (
                      <tr key={r.key} className="border-b border-line/60 hover:bg-surface-2/60">
                        <td className="sticky left-0 bg-surface py-1.5 pr-4 text-ink-2">{r.label}</td>
                        {r.values.map((v: number | null, i: number) => <td key={i} className="num py-1.5 pl-3 text-right">{fmtCell(v, r.kind)}</td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        ))}
      {notes.length > 0 && (
        <Card title="Adjustment notes">
          <ul className="list-disc space-y-1 pl-5 text-xs text-ink-2">{notes.map((n: any, i: number) => <li key={i}>{n}</li>)}</ul>
        </Card>
      )}
      <p className="text-xs text-muted">Free data typically covers about 4–5 fiscal years and 4–5 quarters. Missing cells mean the provider did not report the line; they are never filled with estimates.</p>
    </div>
  )
}

function CagrTable({ a }: { a: A }) {
  const g = a.metrics.growth
  const fin = a.metrics.is_financial
  const rows = (fin
    ? [['nii_cagr', 'Net interest income'], ['loans_cagr', 'Loan book'], ['net_income_cagr', 'Net profit'], ['eps_cagr', 'EPS (diluted)']]
    : [['revenue_cagr', 'Revenue'], ['net_income_cagr', 'Net profit'], ['eps_cagr', 'EPS (diluted)']]) as [string, string][]
  const cell = (m: any) => {
    if (!m) return <span className="text-muted">—</span>
    if (!isNum(m.value)) return <span className="text-muted" title={m.reason}>— <Tip content={m.reason} /></span>
    return (
      <span className="inline-flex items-center gap-1">
        <span className="num">{pct(m.value)}</span>
        <Tip content={<span>{m.period}{m.base_effect && <span className="mt-1 block text-warn">{m.reason}</span>}</span>} />
        {m.base_effect && <span className="text-[11px] text-warn">base effect</span>}
      </span>
    )
  }
  return (
    <Card title={<Term k="cagr">Compound annual growth</Term>} subtitle="Period shown on hover. 3/5/10-year CAGRs need 4/6/11 fiscal years of data; the longest available span is shown separately.">
      <div className="scroll-x">
        <table className="w-full text-[13px]">
          <thead><tr className="border-b border-line text-left text-muted">
            <th className="py-2 font-medium">Metric</th><th className="py-2 text-right font-medium">3 yr</th><th className="py-2 text-right font-medium">5 yr</th>
            <th className="py-2 text-right font-medium">10 yr</th><th className="py-2 text-right font-medium">Longest available</th></tr></thead>
          <tbody>
            {rows.map(([k, l]) => (
              <tr key={k} className="border-b border-line/60">
                <td className="py-2 text-ink-2">{l}</td>
                <td className="py-2 text-right">{cell(g[`${k}_3y`])}</td>
                <td className="py-2 text-right">{cell(g[`${k}_5y`])}</td>
                <td className="py-2 text-right">{cell(g[`${k}_10y`])}</td>
                <td className="py-2 text-right">{cell(g[`${k}_max`])}{g[`${k}_max`]?.period && <span className="block text-[11px] text-muted">{g[`${k}_max`].period}</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

export function Growth({ a }: { a: A }) {
  const cur = a.quote.currency
  const sc = scaleFor(cur)
  const fin = a.metrics.is_financial
  const rc = a.metrics.revenue_consistency
  const hasQ = (a.metrics.quarterly.labels || []).length > 0
  return (
    <div className="space-y-4">
      <FinancialNotice a={a} />
      <CagrTable a={a} />
      <QuarterlyCard a={a} />
      <div className="grid gap-4 lg:grid-cols-2">
        {fin ? (
          <SeriesChart title="Net interest income & net profit" subtitle={sc.unit} rows={rowsFrom(a, ['net_interest_income', 'net_income'], { scale: sc.div })}
            series={[{ key: 'net_interest_income', name: 'Net interest income', type: 'bar', color: 's1' }, { key: 'net_income', name: 'Net profit', type: 'bar', color: 's2' }]}
            fmt={sc.fmt} axisFmt={sc.axis} />
        ) : (
          <SeriesChart title="Revenue & net profit" subtitle={sc.unit} rows={rowsFrom(a, ['revenue', 'net_income'], { scale: sc.div })}
            series={[{ key: 'revenue', name: 'Revenue', type: 'bar', color: 's1' }, { key: 'net_income', name: 'Net profit', type: 'bar', color: 's2' }]}
            fmt={sc.fmt} axisFmt={sc.axis} />
        )}
        <SeriesChart title="Year-on-year growth" subtitle="%; blank where the prior year was a loss or not comparable"
          rows={rowsFrom(a, fin ? ['nii_growth', 'net_income_growth', 'loan_growth'] : ['revenue_growth', 'net_income_growth', 'eps_growth'])}
          series={fin
            ? [{ key: 'nii_growth', name: 'NII growth', type: 'line', color: 's1' }, { key: 'net_income_growth', name: 'Profit growth', type: 'line', color: 's2' }, { key: 'loan_growth', name: 'Loan growth', type: 'line', color: 's3' }]
            : [{ key: 'revenue_growth', name: 'Revenue growth', type: 'line', color: 's1' }, { key: 'net_income_growth', name: 'Profit growth', type: 'line', color: 's2' }, { key: 'eps_growth', name: 'EPS growth', type: 'line', color: 's3' }]}
          fmt={pctFmt} />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        {!fin && (
          <SeriesChart title="Profit margins" subtitle="% of revenue" rows={rowsFrom(a, ['gross_margin', 'operating_margin', 'net_margin'])}
            series={[{ key: 'gross_margin', name: 'Gross margin', type: 'line', color: 's1' }, { key: 'operating_margin', name: 'Operating margin', type: 'line', color: 's2' }, { key: 'net_margin', name: 'Net margin', type: 'line', color: 's3' }]}
            fmt={pctFmt} />
        )}
        <SeriesChart title={<Term k="eps">EPS (diluted)</Term>} subtitle={`${cur} per share, adjusted for later splits/bonus issues`}
          rows={rowsFrom(a, ['eps'])} series={[{ key: 'eps', name: 'EPS', type: 'bar', color: 's1' }]}
          fmt={(v) => (isNum(v) ? v.toFixed(2) : '—')} />
        <SeriesChart title={fin ? 'Return ratios' : <span>Return on equity & capital</span>} subtitle="%; ROE on average equity"
          rows={rowsFrom(a, fin ? ['roe', 'roa'] : ['roe', 'roce', 'roic'])}
          series={fin
            ? [{ key: 'roe', name: 'ROE', type: 'line', color: 's1' }, { key: 'roa', name: 'ROA', type: 'line', color: 's2' }]
            : [{ key: 'roe', name: 'ROE', type: 'line', color: 's1' }, { key: 'roce', name: 'ROCE', type: 'line', color: 's2' }, { key: 'roic', name: 'ROIC', type: 'line', color: 's3' }]}
          fmt={pctFmt} />
        {fin && (
          <SeriesChart title={<Term k="nim">NII / average assets</Term>} subtitle="NIM proxy, %" rows={rowsFrom(a, ['nim_proxy'])}
            series={[{ key: 'nim_proxy', name: 'NIM proxy', type: 'line', color: 's1' }]} fmt={pctFmt} />
        )}
      </div>
      {hasQ && (
        <SeriesChart title="Quarterly revenue & net profit" subtitle={`${sc.unit}; gaps mean the provider skipped that quarter`}
          rows={rowsFrom(a, ['revenue', 'net_income'], { quarterly: true, scale: sc.div })}
          series={[{ key: 'revenue', name: 'Revenue', type: 'bar', color: 's1' }, { key: 'net_income', name: 'Net profit', type: 'bar', color: 's2' }]}
          fmt={sc.fmt} axisFmt={sc.axis} />
      )}
      <Card title="Consistency & earnings quality">
        <KV label="Volatility of yearly revenue growth" hint="Standard deviation of YoY growth rates">{isNum(rc.stdev) ? `±${rc.stdev.toFixed(1)} pp` : '—'}</KV>
        <KV label="Years with falling revenue">{rc.declines ?? '—'}{rc.n ? ` of ${rc.n}` : ''}</KV>
        <KV label="Exceptional items as % of PBT (latest)"><MetricValue a={a} k="unusual_share_of_pbt" /></KV>
        <KV label="Effective tax rate (latest)"><MetricValue a={a} k="effective_tax_rate" /></KV>
        <p className="mt-2 text-xs text-muted">Segment, geographic and organic-vs-acquisition growth are not provided by the free data source; check the annual report’s segment note.</p>
      </Card>
    </div>
  )
}

export function Debt({ a }: { a: A }) {
  const cur = a.quote.currency
  const sc = scaleFor(cur)
  const fin = a.metrics.is_financial
  if (fin) {
    return (
      <div className="space-y-4">
        <FinancialNotice a={a} />
        <div className="grid gap-4 lg:grid-cols-2">
          <SeriesChart title="Equity cushion" subtitle="Equity / total assets, % (crude proxy; not regulatory CAR)" rows={rowsFrom(a, ['equity_to_assets', 'loans_to_assets'])}
            series={[{ key: 'equity_to_assets', name: 'Equity / assets', type: 'line', color: 's1' }, { key: 'loans_to_assets', name: 'Loans / assets', type: 'line', color: 's2' }]} fmt={pctFmt} />
          <Card title="Latest balance-sheet indicators">
            <KV label="Equity / total assets"><MetricValue a={a} k="equity_to_assets" /></KV>
            <KV label="Loans / total assets"><MetricValue a={a} k="loans_to_assets" /></KV>
            <KV label="Loan growth (YoY)"><MetricValue a={a} k="loan_growth" /></KV>
            <KV label="Book value per share"><MetricValue a={a} k="book_value_per_share" /></KV>
            {a.market?.code === 'US' && <KV label="Asset quality and capital">
              <span className="text-xs text-muted">Not assessed for US banks (NPA and RBI capital measures are Indian disclosures)</span></KV>}
            {a.market?.code !== 'US' && ([['gnpa_pct', 'gnpa', 'Gross NPA'], ['nnpa_pct', 'gnpa', 'Net NPA'], ['car_pct', 'car', 'Capital adequacy'],
              ['pcr_pct', null, 'Provision coverage']] as const).map(([k, term, label]) => (
              <KV key={k} label={term ? <Term k={term}>{label}</Term> : label} hint={a.notes?.[k] != null ? `user-entered${a.notes?.bank_as_of ? `, ${a.notes.bank_as_of}` : ''}` : undefined}>
                {a.notes?.[k] != null ? <span className="num">{Number(a.notes[k]).toFixed(2)}%</span>
                  : <Link to={`/c/${a.symbol}/shareholding`} className="text-xs text-accent underline">Enter it</Link>}
              </KV>
            ))}
          </Card>
        </div>
      </div>
    )
  }
  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-2">
        <SeriesChart title="Gross debt vs cash" subtitle={`${sc.unit}. Net debt = debt − cash; negative means net cash.`}
          rows={rowsFrom(a, ['total_debt', 'cash_and_sti', 'net_debt'], { scale: sc.div })}
          series={[{ key: 'total_debt', name: 'Total debt', type: 'bar', color: 's2' }, { key: 'cash_and_sti', name: 'Cash & ST inv.', type: 'bar', color: 's1' }, { key: 'net_debt', name: 'Net debt', type: 'line', color: 's3' }]}
          fmt={sc.fmt} axisFmt={sc.axis} />
        <SeriesChart title="Leverage" subtitle="× (times)" rows={rowsFrom(a, ['debt_to_equity', 'net_debt_to_ebitda'])}
          series={[{ key: 'debt_to_equity', name: 'Debt / equity', type: 'line', color: 's1' }, { key: 'net_debt_to_ebitda', name: 'Net debt / EBITDA', type: 'line', color: 's2' }]} fmt={xFmt} />
        <SeriesChart title={<Term k="interest_coverage">Interest coverage</Term>} subtitle="EBIT / interest, ×; blank where interest is immaterial" rows={rowsFrom(a, ['interest_coverage'])}
          series={[{ key: 'interest_coverage', name: 'Interest coverage', type: 'bar', color: 's1' }]} fmt={(v) => (isNum(v) ? `${v.toFixed(1)}×` : '—')} />
        <SeriesChart title="Liquidity" subtitle="×" rows={rowsFrom(a, ['current_ratio', 'quick_ratio'])}
          series={[{ key: 'current_ratio', name: 'Current ratio', type: 'line', color: 's1' }, { key: 'quick_ratio', name: 'Quick ratio', type: 'line', color: 's2' }]} fmt={xFmt} />
        <SeriesChart title="Working-capital days" subtitle="Receivables vs revenue; inventory vs cost of revenue" rows={rowsFrom(a, ['receivable_days', 'inventory_days'])}
          series={[{ key: 'receivable_days', name: 'Receivable days', type: 'line', color: 's1' }, { key: 'inventory_days', name: 'Inventory days', type: 'line', color: 's2' }]}
          fmt={(v) => (isNum(v) ? `${v.toFixed(0)} d` : '—')} />
        <Card title="Latest balance sheet">
          <KV label="Total borrowings (gross)"><MetricValue a={a} k="total_debt" /></KV>
          <KV label="Cash & short-term investments"><MetricValue a={a} k="cash_and_sti" /></KV>
          <KV label={<Term k="net_debt">Net debt</Term>}><MetricValue a={a} k="net_debt" /></KV>
          <KV label="Working capital"><MetricValue a={a} k="working_capital" /></KV>
          <KV label="Lease liabilities (in debt)">{byUnit(a.statements.annual.rows.balance.find((r: any) => r.key === 'lease_liabilities')?.values.slice(-1)[0], 'currency', cur)}</KV>
          <KV label="Book value per share"><MetricValue a={a} k="book_value_per_share" /></KV>
          <p className="mt-2 text-xs text-muted">Debt maturity, refinancing schedule and contingent liabilities are not available from the free source. See the notes to accounts in the annual report.</p>
        </Card>
      </div>
    </div>
  )
}

export function CashFlow({ a }: { a: A }) {
  const cur = a.quote.currency
  const sc = scaleFor(cur)
  const fin = a.metrics.is_financial
  return (
    <div className="space-y-4">
      <FinancialNotice a={a} />
      <div className="grid gap-4 lg:grid-cols-2">
        <SeriesChart title="Operating cash flow vs net profit" subtitle={sc.unit} rows={rowsFrom(a, ['cfo', 'net_income'], { scale: sc.div })}
          series={[{ key: 'cfo', name: 'Cash from operations', type: 'bar', color: 's1' }, { key: 'net_income', name: 'Net profit', type: 'bar', color: 's2' }]}
          fmt={sc.fmt} axisFmt={sc.axis} />
        {!fin && (
          <SeriesChart title={<Term k="fcf">Free cash flow</Term>} subtitle={`FCF = CFO − capex, ${sc.unit}`} rows={rowsFrom(a, ['fcf', 'capex'], { scale: sc.div })}
            series={[{ key: 'fcf', name: 'Free cash flow', type: 'bar', color: 's1' }, { key: 'capex', name: 'Capex', type: 'bar', color: 's2' }]}
            fmt={sc.fmt} axisFmt={sc.axis} />
        )}
        {!fin && (
          <SeriesChart title="Cash conversion" subtitle="CFO / net profit (×). Persistently below ~0.8 is a warning sign." rows={rowsFrom(a, ['cash_conversion'])}
            series={[{ key: 'cash_conversion', name: 'CFO / PAT', type: 'line', color: 's1' }]} fmt={xFmt} />
        )}
        <SeriesChart title="Shareholder payouts & equity raised" subtitle={sc.unit} rows={rowsFrom(a, ['dividends_paid', 'buybacks', 'share_issuance'], { scale: sc.div })}
          series={[{ key: 'dividends_paid', name: 'Dividends paid', type: 'bar', color: 's1' }, { key: 'buybacks', name: 'Buybacks', type: 'bar', color: 's2' }, { key: 'share_issuance', name: 'Equity raised', type: 'bar', color: 's3' }]}
          fmt={sc.fmt} axisFmt={sc.axis} emptyText="No dividends, buybacks or equity issuance reported." />
      </div>
      <Card title="Definitions used">
        <ul className="list-disc space-y-1 pl-5 text-[13px] text-ink-2">
          <li><b>Free cash flow</b> = cash flow from operations − purchase of fixed assets (capex). Indian companies usually report interest paid under financing, so this approximates free cash flow to the firm.</li>
          <li><b>Cash conversion</b> = CFO ÷ net profit. The red-flag engine looks at the 3-year cumulative ratio to smooth working-capital timing.</li>
          <li>External funding dependence shows up as equity raised plus rising debt (Debt & balance tab) while FCF is negative.</li>
          {fin && <li>For lenders, CFO mainly reflects changes in the loan book and deposits, so FCF-based analysis is not applied.</li>}
        </ul>
      </Card>
    </div>
  )
}
