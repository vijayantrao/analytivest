// Types for the API responses, mirroring the Pydantic models in backend/app/schemas.py (also visible at /docs).
// The fields every screen relies on are typed exactly. The analysis payload is large and grows with the engine,
// so each object also allows other keys (`[key: string]: any`): undeclared detail is still readable, but a
// misspelt or retyped core field is a compile error.

type Rest = { [key: string]: any }
type Num = number | null

export type MarketCode = 'IN' | 'US'
export type Severity = 'high' | 'medium' | 'low'
export type ScoreModel = 'standard' | 'financial'

export interface MarketInfo {
  code: MarketCode
  name: string
  currency: string
  display_units: string
  notes: string[]
}

export interface Quote extends Rest {
  price: Num
  previous_close?: Num
  change?: Num
  change_pct?: Num
  currency?: string | null
  shares_outstanding?: Num
}

export interface Profile extends Rest {
  name?: string | null
  symbol?: string | null
  sector?: string | null
  industry?: string | null
}

export interface Verdict extends Rest {
  score: Num
  label: string | null
  question: string
}

export interface Scores extends Rest {
  model: ScoreModel
  verdicts: { business_quality: Verdict; financial_risk: Verdict; valuation: Verdict }
  composite: Rest
  categories: Record<string, Rest>
  data_completeness: Num
  confidence: { score: Num; label: string; reasons: string[] }
  decision_label: string
}

export interface FairValueFamily {
  family: string
  label: string
  value: number
  n_methods: number
}

export interface FairValue extends Rest {
  label: string
  low: Num
  mid: Num
  high: Num
  n_methods: number
  n_families?: number | null
  families?: FairValueFamily[]
}

export interface Estimate extends Rest {
  method: string
  value_per_share: Num
  family?: string | null
  inputs?: string | null
}

export interface Valuation extends Rest {
  price: Num
  fair_value: FairValue
  estimates: Estimate[]
  dcf: Rest
}

export interface Metrics extends Rest {
  is_financial: boolean
  financial_kind: 'lender' | 'insurer' | null
  model: ScoreModel
  annual: Rest
  latest: Rest
  growth: Rest
  years_available: number
}

export interface Flag {
  id: string
  title: string
  severity: Severity
  category: string
  evidence: string
  period: string
  implication: string
  rule: string
}

export interface Analysis extends Rest {
  symbol: string
  is_sample: boolean
  market: MarketInfo
  profile: Profile
  quote: Quote
  metrics: Metrics
  valuation: Valuation
  flags: Flag[]
  scores: Scores
  in_watchlist: boolean
  disclaimer: string
}

export interface DcfResponse extends Rest {
  dcf: Rest
  fair_value: FairValue
  estimates: Estimate[]
  price: Num
}

export interface SummaryRow {
  symbol: string
  name: string | null
  is_sample: boolean
  sector: string | null
  industry: string | null
  price: Num
  change_pct: Num
  currency: string | null
  market_cap: Num
  decision_label: string
  business_quality: Num
  business_quality_label: string | null
  financial_risk: Num
  financial_risk_label: string | null
  valuation_score: Num
  valuation_label: string | null
  composite: Num
  completeness: Num
  confidence: string
  model: ScoreModel
  metrics: Record<
    | 'revenue_cagr_3y' | 'eps_cagr_3y' | 'roe' | 'roce' | 'operating_margin' | 'net_margin' | 'debt_to_equity'
    | 'interest_coverage' | 'cash_conversion' | 'fcf_margin' | 'pe' | 'pb' | 'ev_ebitda' | 'dividend_yield'
    | 'fcf_yield', Num>
  flags_high: number
  flags_total: number
  latest_period: string | null
  retrieved_at: Num
}

export interface CompanySummary extends SummaryRow {
  quarter: { latest: any; verdict: any } | null
  fair_value: { low: Num; mid: Num; high: Num; label: string }
}

export interface CompareRow extends SummaryRow {
  series: { labels: string[]; revenue: Num[]; net_income: Num[]; roe: Num[] }
}

export interface CompareResponse {
  rows: CompareRow[]
  errors: { symbol: string; message: string }[]
}
