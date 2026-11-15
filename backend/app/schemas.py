"""Response models for the main read endpoints.

The fields the frontend relies on (verdicts, fair value, quote, summary rows) are declared and validated, so a change
that breaks them fails a test instead of a screen. The analysis payload is large and grows with the engine, so its
models also allow extra fields: undeclared detail passes through unchanged rather than being stripped.
These models also document the API in /docs (OpenAPI), which the frontend types in src/lib/types.ts mirror.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict


class Open(BaseModel):
    model_config = ConfigDict(extra="allow")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------- analysis ----------------
class MarketInfo(Strict):
    code: Literal["IN", "US"]
    name: str
    currency: str
    display_units: str
    notes: list[str]


class Quote(Open):
    price: Optional[float] = None
    previous_close: Optional[float] = None
    change: Optional[float] = None
    change_pct: Optional[float] = None
    currency: Optional[str] = None
    shares_outstanding: Optional[float] = None


class Profile(Open):
    name: Optional[str] = None
    symbol: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    currency: Optional[str] = None


class Verdict(Open):
    score: Optional[float] = None
    label: Optional[str] = None
    question: str


class Verdicts(Strict):
    business_quality: Verdict
    financial_risk: Verdict
    valuation: Verdict


class Confidence(Strict):
    score: Optional[float] = None
    label: str
    reasons: list[str]


class Scores(Open):
    model: Literal["standard", "financial"]
    verdicts: Verdicts
    composite: dict[str, Any]
    categories: dict[str, dict[str, Any]]
    data_completeness: Optional[float] = None
    confidence: Confidence
    decision_label: str


class FairValueFamily(Strict):
    family: str
    label: str
    value: float
    n_methods: int


class FairValue(Open):
    label: str
    low: Optional[float] = None
    mid: Optional[float] = None
    high: Optional[float] = None
    n_methods: int = 0
    n_families: Optional[int] = None
    families: list[FairValueFamily] = []


class Estimate(Open):
    method: str
    value_per_share: Optional[float] = None
    family: Optional[str] = None
    inputs: Optional[str] = None


class Valuation(Open):
    price: Optional[float] = None
    fair_value: FairValue
    estimates: list[Estimate]
    dcf: dict[str, Any]


class Metrics(Open):
    is_financial: bool
    financial_kind: Optional[Literal["lender", "insurer"]] = None
    model: Literal["standard", "financial"]
    annual: dict[str, Any]
    latest: dict[str, Any]
    growth: dict[str, Any]
    years_available: int


class Flag(Strict):
    id: str
    title: str
    severity: Literal["high", "medium", "low"]
    category: str
    evidence: str
    period: str
    implication: str
    rule: str


class Analysis(Open):
    symbol: str
    is_sample: bool
    market: MarketInfo
    profile: Profile
    quote: Quote
    metrics: Metrics
    valuation: Valuation
    flags: list[Flag]
    scores: Scores
    in_watchlist: bool
    disclaimer: str



class DcfResponse(Open):
    """POST /dcf returns just the valuation pieces that change with the assumptions."""
    dcf: dict[str, Any]
    fair_value: FairValue
    estimates: list[Estimate]
    price: Optional[float] = None


# ---------------- summary rows (watchlist, compare, portfolio, screener) ----------------
class SummaryMetrics(Strict):
    revenue_cagr_3y: Optional[float] = None
    eps_cagr_3y: Optional[float] = None
    roe: Optional[float] = None
    roce: Optional[float] = None
    operating_margin: Optional[float] = None
    net_margin: Optional[float] = None
    debt_to_equity: Optional[float] = None
    interest_coverage: Optional[float] = None
    cash_conversion: Optional[float] = None
    fcf_margin: Optional[float] = None
    pe: Optional[float] = None
    pb: Optional[float] = None
    ev_ebitda: Optional[float] = None
    dividend_yield: Optional[float] = None
    fcf_yield: Optional[float] = None


class SummaryRow(Strict):
    symbol: str
    name: Optional[str] = None
    is_sample: bool
    sector: Optional[str] = None
    industry: Optional[str] = None
    price: Optional[float] = None
    change_pct: Optional[float] = None
    currency: Optional[str] = None
    market_cap: Optional[float] = None
    decision_label: str
    business_quality: Optional[float] = None
    business_quality_label: Optional[str] = None
    financial_risk: Optional[float] = None
    financial_risk_label: Optional[str] = None
    valuation_score: Optional[float] = None
    valuation_label: Optional[str] = None
    composite: Optional[float] = None
    completeness: Optional[float] = None
    confidence: str
    model: Literal["standard", "financial"]
    metrics: SummaryMetrics
    flags_high: int
    flags_total: int
    latest_period: Optional[str] = None
    retrieved_at: Optional[float] = None


class QuarterBrief(Strict):
    latest: Optional[Any] = None
    verdict: Optional[Any] = None


class FairValueBrief(Strict):
    low: Optional[float] = None
    mid: Optional[float] = None
    high: Optional[float] = None
    label: str


class CompanySummary(SummaryRow):
    quarter: Optional[QuarterBrief] = None
    fair_value: FairValueBrief


class CompareSeries(Strict):
    labels: list[str]
    revenue: list[Optional[float]]
    net_income: list[Optional[float]]
    roe: list[Optional[float]]


class CompareRow(SummaryRow):
    series: CompareSeries


class CompareError(Strict):
    symbol: str
    message: str


class CompareResponse(Strict):
    rows: list[CompareRow]
    errors: list[CompareError]


class Health(Strict):
    status: Literal["ok"]
    providers: list[dict[str, Any]]
    offline: bool
    cache: dict[str, Any]
    time: float
