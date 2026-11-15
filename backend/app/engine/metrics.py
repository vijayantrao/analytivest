"""Metric computation over canonical statements.

Produces aligned annual/quarterly series and a "latest" snapshot. Every value carries
status/reason so missing or meaningless figures are never shown (or scored) as zero.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from . import formulas as F
from .formulas import Calc, is_num

# Ratios that mislead for lenders (debt and interest are their raw material, CFO tracks loan growth).
INDUSTRIAL_ONLY = ("gross_margin", "ebitda_margin", "operating_margin", "roce", "roic", "debt_to_equity",
                   "net_debt", "net_debt_to_ebitda", "interest_coverage", "current_ratio", "quick_ratio",
                   "working_capital", "receivable_days", "inventory_days", "receivables_growth", "fcf",
                   "fcf_margin", "cash_conversion", "ebitda")

# Which financial companies get the balance-sheet ("financial") model. Only lenders and insurers do: their
# operating cash flow and debt ratios describe the loan book or the insurance float, not the business. Fee
# businesses (fund managers, exchanges, ratings and data firms, insurance brokers, payment networks) are scored on
# the standard model like any other company.
LENDER_INDUSTRY_KEYWORDS = ("bank", "mortgage", "financial conglomerates", "capital markets")
INSURER_EXCLUDE = ("insurance brokers",)
# Industries that mix lenders and fee businesses: decided from the balance sheet.
MIXED_INDUSTRY_KEYWORDS = ("credit services", "asset management")
LENDER_MIN_LOAN_SHARE = 20.0  # net loans as % of total assets
LENDER_MIN_NII_SHARE = 20.0  # net interest income as % of revenue
LENDER_MIN_DEBT_SHARE = 50.0  # borrowings as % of total assets (credit services only)

# key -> label, unit, formula, category, higher_is_better (None = context-dependent)
METRIC_DEFS: dict[str, dict[str, Any]] = {
    "revenue": dict(label="Revenue", unit="currency", formula="Reported total revenue", cat="growth", hib=True),
    "revenue_growth": dict(label="Revenue growth (YoY)", unit="pct",
                           formula="(Revenue_t / Revenue_t−1 − 1) × 100", cat="growth", hib=True),
    "gross_margin": dict(label="Gross margin", unit="pct", formula="Gross profit / Revenue × 100", cat="profitability", hib=True),
    "ebitda": dict(label="EBITDA", unit="currency", formula="Reported EBITDA (provider definition)", cat="profitability", hib=True),
    "ebitda_margin": dict(label="EBITDA margin", unit="pct", formula="EBITDA / Revenue × 100", cat="profitability", hib=True),
    "operating_margin": dict(label="Operating (EBIT) margin", unit="pct",
                             formula="Operating income / Revenue × 100 (EBIT used if operating income missing)",
                             cat="profitability", hib=True),
    "net_income": dict(label="Net profit (PAT)", unit="currency", formula="Profit attributable to shareholders", cat="profitability", hib=True),
    "net_income_growth": dict(label="Net profit growth (YoY)", unit="pct", formula="(PAT_t / PAT_t−1 − 1) × 100", cat="growth", hib=True),
    "net_margin": dict(label="Net profit margin", unit="pct", formula="Net profit / Revenue × 100", cat="profitability", hib=True),
    "eps": dict(label="EPS (diluted)", unit="per_share", formula="Diluted EPS, adjusted for later splits/bonus issues", cat="profitability", hib=True),
    "eps_growth": dict(label="EPS growth (YoY)", unit="pct", formula="(EPS_t / EPS_t−1 − 1) × 100", cat="growth", hib=True),
    "roe": dict(label="Return on equity (ROE)", unit="pct", formula="Net profit / Average shareholders' equity × 100", cat="profitability", hib=True),
    "roce": dict(label="Return on capital employed (ROCE)", unit="pct",
                 formula="EBIT / Average capital employed × 100; capital employed = Total assets − Current liabilities",
                 cat="profitability", hib=True),
    "roic": dict(label="Return on invested capital (ROIC)", unit="pct",
                 formula="EBIT × (1 − tax rate) / Average (Equity + Total debt − Cash) × 100", cat="profitability", hib=True),
    "roa": dict(label="Return on assets (ROA)", unit="pct", formula="Net profit / Average total assets × 100", cat="profitability", hib=True),
    "effective_tax_rate": dict(label="Effective tax rate", unit="pct", formula="Tax expense / Profit before tax × 100", cat="profitability", hib=None),
    "total_debt": dict(label="Total borrowings (gross debt)", unit="currency", formula="Short + long-term borrowings incl. lease liabilities", cat="balance", hib=False),
    "cash_and_sti": dict(label="Cash & short-term investments", unit="currency", formula="Cash & equivalents + short-term investments", cat="balance", hib=True),
    "net_debt": dict(label="Net debt (negative = net cash)", unit="currency", formula="Total debt − Cash & short-term investments", cat="balance", hib=False),
    "debt_to_equity": dict(label="Debt-to-equity", unit="x", formula="Total debt / Shareholders' equity", cat="balance", hib=False),
    "net_debt_to_ebitda": dict(label="Net debt / EBITDA", unit="x", formula="Net debt / EBITDA", cat="balance", hib=False),
    "interest_coverage": dict(label="Interest coverage", unit="x", formula="EBIT / Interest expense", cat="balance", hib=True),
    "current_ratio": dict(label="Current ratio", unit="x", formula="Current assets / Current liabilities", cat="balance", hib=True),
    "quick_ratio": dict(label="Quick ratio", unit="x", formula="(Current assets − Inventory) / Current liabilities", cat="balance", hib=True),
    "working_capital": dict(label="Working capital", unit="currency", formula="Current assets − Current liabilities", cat="balance", hib=None),
    "receivable_days": dict(label="Receivable days", unit="days", formula="Trade receivables / Revenue × 365", cat="quality", hib=False),
    "inventory_days": dict(label="Inventory days", unit="days", formula="Inventory / Cost of revenue × 365", cat="quality", hib=False),
    "receivables_growth": dict(label="Receivables growth (YoY)", unit="pct", formula="(Receivables_t / Receivables_t−1 − 1) × 100", cat="quality", hib=None),
    "cfo": dict(label="Cash flow from operations", unit="currency", formula="Reported operating cash flow", cat="cashflow", hib=True),
    "capex": dict(label="Capital expenditure", unit="currency", formula="Purchase of property, plant & equipment (outflow)", cat="cashflow", hib=None),
    "fcf": dict(label="Free cash flow", unit="currency", formula="Cash flow from operations − Capital expenditure", cat="cashflow", hib=True),
    "fcf_margin": dict(label="FCF margin", unit="pct", formula="Free cash flow / Revenue × 100", cat="cashflow", hib=True),
    "cash_conversion": dict(label="Cash conversion (CFO / PAT)", unit="x", formula="Cash flow from operations / Net profit", cat="cashflow", hib=True),
    "dividends_paid": dict(label="Dividends paid", unit="currency", formula="Cash dividends paid", cat="returns", hib=None),
    "payout_ratio": dict(label="Dividend payout ratio", unit="pct", formula="Dividends paid / Net profit × 100", cat="returns", hib=None),
    "buybacks": dict(label="Share buybacks", unit="currency", formula="Cash spent repurchasing shares", cat="returns", hib=None),
    "share_issuance": dict(label="Equity raised", unit="currency", formula="Cash from issuing shares", cat="returns", hib=None),
    "share_count_change": dict(label="Change in share count", unit="pct",
                               formula="(Shares_t / Shares_t−1 − 1) × 100, split-adjusted", cat="returns", hib=False),
    "unusual_share_of_pbt": dict(label="Exceptional items as % of PBT", unit="pct",
                                 formula="Exceptional / unusual items / Profit before tax × 100", cat="quality", hib=False),
    "book_value_per_share": dict(label="Book value per share", unit="per_share", formula="Shareholders' equity / Shares outstanding", cat="balance", hib=True),
    # Financial-sector metrics
    "net_interest_income": dict(label="Net interest income (NII)", unit="currency", formula="Interest earned − Interest expended", cat="growth", hib=True),
    "nii_growth": dict(label="NII growth (YoY)", unit="pct", formula="(NII_t / NII_t−1 − 1) × 100", cat="growth", hib=True),
    "nim_proxy": dict(label="NII / average assets (NIM proxy)", unit="pct",
                      formula="Net interest income / Average total assets × 100 (true NIM uses average interest-earning assets, not available)",
                      cat="profitability", hib=True),
    "loan_growth": dict(label="Loan book growth (YoY)", unit="pct", formula="(Net loans_t / Net loans_t−1 − 1) × 100", cat="growth", hib=True),
    "equity_to_assets": dict(label="Equity / total assets", unit="pct",
                             formula="Shareholders' equity / Total assets × 100 (a crude leverage proxy; not regulatory CAR)",
                             cat="balance", hib=True),
    "loans_to_assets": dict(label="Loans / total assets", unit="pct", formula="Net loans / Total assets × 100", cat="balance", hib=None),
}


def _share(part: Any, whole: Any) -> Optional[float]:
    return part / whole * 100 if is_num(part) and is_num(whole) and whole > 0 else None


def financial_kind(profile: dict[str, Any], latest_fields: Optional[dict[str, Any]] = None) -> Optional[str]:
    """'lender', 'insurer' or None (standard model). For credit services and asset management the industry name is
    not enough (Visa and Mastercard are "credit services"; an NBFC can be filed under asset management), so the
    balance sheet decides: a lender has loans of at least 20% of assets or net interest income of at least 20% of
    revenue. A credit-services company that borrows at least half its assets is also a lender: Yahoo often reports no
    loan book and a meaningless interest split for Indian NBFCs, but their borrowing gives them away (Tata Capital
    78%, IRFC 84%, against 20-40% for Visa and Mastercard). With no balance-sheet data, credit services default to
    lender and asset management to standard."""
    ind = (profile.get("industry") or "").lower()
    if "insurance" in ind:
        return None if any(k in ind for k in INSURER_EXCLUDE) else "insurer"
    if any(k in ind for k in LENDER_INDUSTRY_KEYWORDS):
        return "lender"
    if any(k in ind for k in MIXED_INDUSTRY_KEYWORDS):
        f = latest_fields or {}
        loans = _share(f.get("net_loans"), f.get("total_assets"))
        nii = _share(f.get("net_interest_income"), f.get("revenue"))
        debt = _share(f.get("total_debt"), f.get("total_assets")) if "credit" in ind else None
        if loans is None and nii is None and debt is None:
            return "lender" if "credit" in ind else None
        if ((loans or 0) >= LENDER_MIN_LOAN_SHARE or (nii or 0) >= LENDER_MIN_NII_SHARE
                or (debt or 0) >= LENDER_MIN_DEBT_SHARE):
            return "lender"
        return None
    return None


def is_financial(profile: dict[str, Any], latest_fields: Optional[dict[str, Any]] = None) -> bool:
    return financial_kind(profile, latest_fields) is not None


def _c(calc: Calc) -> dict[str, Any]:
    return {"value": calc.value, "status": calc.status if calc.value is None else "ok", "reason": calc.reason}


def _raw(v: Any) -> dict[str, Any]:
    if is_num(v):
        return {"value": float(v), "status": "ok", "reason": None}
    return {"value": None, "status": "missing", "reason": "not reported by the data provider"}


def _years_between(a: str, b: str) -> float:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days / 365.25


def compute_series(periods: list[dict[str, Any]], *, statutory_tax: float, quarterly: bool = False) -> dict[str, Any]:
    """Aligned per-period metric series. For quarterly, growth compares with the same quarter a year earlier."""
    n = len(periods)
    S: dict[str, list[dict[str, Any]]] = {}

    def put(key: str, i: int, cell: dict[str, Any]) -> None:
        S.setdefault(key, [None] * n)[i] = cell  # type: ignore[list-item]

    def f(i: int, k: str) -> Optional[float]:
        if i < 0 or i >= n:
            return None
        v = periods[i]["fields"].get(k)
        return float(v) if is_num(v) else None

    def comparable_index(i: int) -> Optional[int]:
        """Index of the comparable prior period, or None."""
        if not quarterly:
            if i == 0:
                return None
            # A short (or long) fiscal year is not comparable with a normal one in either direction: growth from a
            # 9-month year to a 12-month year at the same monthly sales would show +33%.
            if periods[i].get("non_standard_length_days") or periods[i - 1].get("non_standard_length_days"):
                return None
            return i - 1
        target = date.fromisoformat(periods[i]["period_end"])
        for j in range(i - 1, -1, -1):
            d = date.fromisoformat(periods[j]["period_end"])
            if 350 <= (target - d).days <= 380:
                return j
        return None

    def g(i: int, k: str) -> Calc:
        j = comparable_index(i)
        if j is None:
            return F.missing("comparable prior period")
        return F.growth(f(i, k), f(j, k))

    def avg(i: int, k: str) -> Calc:
        j = None if quarterly else (i - 1 if i > 0 else None)
        return F.average(f(i, k), f(j, k) if j is not None else None)

    for i, p in enumerate(periods):
        rev = f(i, "revenue")
        put("revenue", i, _raw(rev))
        put("revenue_growth", i, _c(g(i, "revenue")))
        put("gross_margin", i, _c(F.pct(f(i, "gross_profit"), rev, name="gross margin")))
        ebitda = f(i, "ebitda")
        put("ebitda", i, _raw(ebitda))
        put("ebitda_margin", i, _c(F.pct(ebitda, rev, name="EBITDA margin")))
        op = f(i, "operating_income")
        put("operating_margin", i, _c(F.pct(op if op is not None else f(i, "ebit"), rev, name="operating margin")))
        ni = f(i, "net_income")
        put("net_income", i, _raw(ni))
        put("net_income_growth", i, _c(g(i, "net_income")))
        put("net_margin", i, _c(F.pct(ni, rev, name="net margin")))
        eps = f(i, "eps_diluted") if f(i, "eps_diluted") is not None else f(i, "eps_basic")
        put("eps", i, _raw(eps))
        j = comparable_index(i)
        prev_eps = None
        if j is not None:
            prev_eps = f(j, "eps_diluted") if f(j, "eps_diluted") is not None else f(j, "eps_basic")
        put("eps_growth", i, _c(F.growth(eps, prev_eps) if j is not None else F.missing("comparable prior period")))
        pbt, tax = f(i, "pbt"), f(i, "tax")
        etr = F.pct(tax, pbt, name="effective tax rate")
        put("effective_tax_rate", i, _c(etr))

        put("net_interest_income", i, _raw(f(i, "net_interest_income")))
        put("nii_growth", i, _c(g(i, "net_interest_income")))
        put("loan_growth", i, _c(g(i, "net_loans")))

        if quarterly:
            continue  # balance-sheet/cash-flow ratios on quarters are sparse on free data

        eq_avg = avg(i, "equity")
        roe = F.pct(ni, eq_avg.value, name="ROE")
        put("roe", i, {**_c(roe), "reason": roe.reason or eq_avg.reason})
        ta_avg = avg(i, "total_assets")
        put("roa", i, _c(F.pct(ni, ta_avg.value, name="ROA")))

        ebit = f(i, "ebit")
        ta, cl = f(i, "total_assets"), f(i, "current_liabilities")
        ce = (ta - cl) if (ta is not None and cl is not None) else None
        ce_prev = None
        if i > 0:
            ta0, cl0 = f(i - 1, "total_assets"), f(i - 1, "current_liabilities")
            ce_prev = (ta0 - cl0) if (ta0 is not None and cl0 is not None) else None
        ce_avg = F.average(ce, ce_prev)
        if ce_avg.value is None:
            put("roce", i, {"value": None, "status": "missing",
                            "reason": "capital employed not available (total assets or current liabilities missing)"})
        else:
            rc = F.pct(ebit, ce_avg.value, name="ROCE")
            put("roce", i, {**_c(rc), "reason": rc.reason or ce_avg.reason})

        debt, cash = f(i, "total_debt"), f(i, "cash")
        sti = f(i, "short_term_investments") or 0.0
        cash_sti = (cash + sti) if cash is not None else None
        eq = f(i, "equity")
        # Effective tax: use reported rate if within a sane band, else statutory.
        t = etr.value if (etr.value is not None and 5 <= etr.value <= 45) else statutory_tax
        nopat = ebit * (1 - t / 100) if ebit is not None else None
        # Invested capital = equity + debt − cash. Missing debt or cash makes it missing, never zero: a company
        # whose debt simply was not reported would otherwise look far more capital-efficient than it is.
        ic = (eq + debt - cash_sti) if None not in (eq, debt, cash_sti) else None
        ic_prev = None
        if i > 0:
            e0, d0, c0 = f(i - 1, "equity"), f(i - 1, "total_debt"), f(i - 1, "cash")
            if None not in (e0, d0, c0):
                ic_prev = e0 + d0 - (c0 + (f(i - 1, "short_term_investments") or 0.0))
        if ic is None:
            missing_parts = [n for n, v in (("equity", eq), ("total debt", debt), ("cash", cash_sti)) if v is None]
            put("roic", i, {"value": None, "status": "missing",
                            "reason": f"invested capital needs {', '.join(missing_parts)}, which the provider did not report"})
        else:
            ic_avg = F.average(ic, ic_prev)
            put("roic", i, _c(F.pct(nopat, ic_avg.value, name="ROIC")))

        put("total_debt", i, _raw(debt))
        put("cash_and_sti", i, _raw(cash_sti))
        nd = F.net_debt(debt, cash_sti)
        put("net_debt", i, _c(nd))
        put("debt_to_equity", i, _c(F.ratio(debt, eq, name="debt-to-equity")))
        nde = F.ratio(nd.value, ebitda, name="net debt/EBITDA")
        if nd.value is not None and nd.value <= 0 and ebitda and ebitda > 0:
            nde = Calc(nd.value / ebitda, "net cash position")
        put("net_debt_to_ebitda", i, _c(nde))
        put("interest_coverage", i, _c(F.interest_coverage(ebit, f(i, "interest_expense"))))
        ca, inv = f(i, "current_assets"), f(i, "inventory")
        put("current_ratio", i, _c(F.ratio(ca, cl, name="current ratio")))
        put("quick_ratio", i, _c(F.ratio((ca - (inv or 0)) if ca is not None else None, cl, name="quick ratio")))
        put("working_capital", i, _c(Calc(ca - cl) if (ca is not None and cl is not None) else F.missing("current assets/liabilities")))
        rec = f(i, "receivables")
        put("receivable_days", i, _c(F.ratio(rec, rev, name="receivable days", scale=365)))
        put("inventory_days", i, _c(F.ratio(inv, f(i, "cost_of_revenue"), name="inventory days", scale=365)))
        put("receivables_growth", i, _c(g(i, "receivables")))

        cfo, capex = f(i, "cfo"), f(i, "capex")
        put("cfo", i, _raw(cfo))
        put("capex", i, _raw(capex))
        fcf = Calc(cfo - capex) if (cfo is not None and capex is not None) else F.missing("CFO or capex")
        put("fcf", i, _c(fcf))
        put("fcf_margin", i, _c(F.pct(fcf.value, rev, name="FCF margin")))
        put("cash_conversion", i, _c(F.ratio(cfo, ni, name="cash conversion")))
        put("dividends_paid", i, _raw(f(i, "dividends_paid")))
        put("payout_ratio", i, _c(F.pct(f(i, "dividends_paid"), ni, name="payout ratio")))
        put("buybacks", i, _raw(f(i, "buybacks")))
        put("share_issuance", i, _raw(f(i, "share_issuance")))
        put("share_count_change", i, _c(g(i, "shares_outstanding")))
        un = f(i, "unusual_items")
        put("unusual_share_of_pbt", i, _c(F.pct(un, pbt, name="exceptional share of PBT") if un is not None
                                           else F.missing("exceptional items")))
        sh = f(i, "shares_outstanding")
        put("book_value_per_share", i, _c(F.ratio(eq, sh, name="book value per share", den_must_be_positive=True)))
        put("nim_proxy", i, _c(F.pct(f(i, "net_interest_income"), ta_avg.value, name="NIM proxy")))
        put("equity_to_assets", i, _c(F.pct(eq, ta, name="equity/assets")))
        put("loans_to_assets", i, _c(F.pct(f(i, "net_loans"), ta, name="loans/assets")))

    # Fill any never-set slots with "missing"
    for k, arr in S.items():
        S[k] = [c if c is not None else {"value": None, "status": "missing", "reason": "not computed"} for c in arr]
    return {
        "labels": [p["label"] for p in periods],
        "period_ends": [p["period_end"] for p in periods],
        "notes": [p.get("notes", []) for p in periods],
        "series": S,
    }


def cagr_metric(periods: list[dict[str, Any]], field: str, years: int, *, eps: bool = False) -> dict[str, Any]:
    """CAGR over exactly ``years`` fiscal years ending at the latest period, if data allows."""
    if len(periods) < years + 1:
        return {"value": None, "status": "missing",
                "reason": f"needs {years + 1} annual periods; {len(periods)} available from the provider",
                "period": None}
    end_p, start_p = periods[-1], periods[-1 - years]
    odd = [p["label"] for p in (start_p, end_p) if p.get("non_standard_length_days") and not eps]
    if odd:
        return {"value": None, "status": "not_meaningful", "period": None,
                "reason": f"{' and '.join(odd)} is not a 12-month fiscal year, so a growth rate from it would be distorted"}
    get = (lambda p: p["fields"].get("eps_diluted", p["fields"].get("eps_basic"))) if eps else (lambda p: p["fields"].get(field))
    actual_years = _years_between(start_p["period_end"], end_p["period_end"])
    calc = F.cagr(get(start_p), get(end_p), round(actual_years, 2))
    out = {**_c(calc), "period": f"{start_p['label']} → {end_p['label']} ({actual_years:.1f} yrs)",
           "start": get(start_p), "end": get(end_p), "base_effect": False}
    # Base effect: a depressed starting year makes the CAGR look spectacular.
    window = [get(p) for p in periods[-1 - years:]]
    pos = [x for x in window if is_num(x) and x > 0]
    if calc.value is not None and len(pos) >= 3:
        med = F.median(pos)
        if med and get(start_p) < 0.5 * med:
            out["base_effect"] = True
            out["reason"] = (f"start year ({start_p['label']}) is unusually low, less than half the period median, "
                             "so this CAGR overstates the underlying growth")
    return out


def ttm_from_quarters(quarters: list[dict[str, Any]], field: str) -> dict[str, Any]:
    """Sum of the latest four quarters, only if they are consecutive (~3 months apart)."""
    if len(quarters) < 4:
        return {"value": None, "status": "missing", "reason": "fewer than 4 quarters available"}
    last4 = quarters[-4:]
    ends = [date.fromisoformat(q["period_end"]) for q in last4]
    for a, b in zip(ends, ends[1:]):
        if not 80 <= (b - a).days <= 100:
            return {"value": None, "status": "missing",
                    "reason": "the provider's latest four quarters are not consecutive (a quarter is missing)"}
    vals = [q["fields"].get(field) for q in last4]
    if not all(is_num(v) for v in vals):
        return {"value": None, "status": "missing", "reason": f"{field} missing in one of the last four quarters"}
    return {"value": float(sum(vals)), "status": "ok", "reason": None,
            "period": f"TTM to {last4[-1]['label']}"}


def consistency(values: list[Optional[float]]) -> dict[str, Any]:
    v = [x for x in values if is_num(x)]
    if len(v) < 3:
        return {"stdev": None, "declines": None, "n": len(v)}
    return {"stdev": F.stdev(v), "declines": sum(1 for x in v if x < 0), "n": len(v),
            "mean": sum(v) / len(v)}


def compute_metrics(bundle: dict[str, Any], statutory_tax: float) -> dict[str, Any]:
    annual = bundle.get("annual") or []
    quarterly = bundle.get("quarterly") or []
    kind = financial_kind(bundle.get("profile") or {}, annual[-1]["fields"] if annual else None)
    fin = kind is not None
    A = compute_series(annual, statutory_tax=statutory_tax)
    Q = compute_series(quarterly, statutory_tax=statutory_tax, quarterly=True)
    if fin:
        for S in (A["series"], Q["series"]):
            for k in INDUSTRIAL_ONLY:
                if k in S:
                    S[k] = [{"value": None, "status": "not_meaningful",
                             "reason": "not meaningful for lenders and insurers"} for _ in S[k]]

    latest: dict[str, Any] = {}
    if annual:
        for k, arr in A["series"].items():
            cell = dict(arr[-1])
            cell["period"] = A["labels"][-1]
            latest[k] = cell

    growth = {}
    for yrs in (3, 5, 10):
        growth[f"revenue_cagr_{yrs}y"] = cagr_metric(annual, "revenue", yrs)
        growth[f"net_income_cagr_{yrs}y"] = cagr_metric(annual, "net_income", yrs)
        growth[f"eps_cagr_{yrs}y"] = cagr_metric(annual, "eps", yrs, eps=True)
        if kind == "lender":
            growth[f"nii_cagr_{yrs}y"] = cagr_metric(annual, "net_interest_income", yrs)
            growth[f"loans_cagr_{yrs}y"] = cagr_metric(annual, "net_loans", yrs)
    # Longest available span, so short histories still get a CAGR (clearly labelled with its period)
    if len(annual) >= 3:
        span = len(annual) - 1
        growth["revenue_cagr_max"] = cagr_metric(annual, "revenue", span)
        growth["net_income_cagr_max"] = cagr_metric(annual, "net_income", span)
        growth["eps_cagr_max"] = cagr_metric(annual, "eps", span, eps=True)

    rg = [c["value"] for c in A["series"].get("revenue_growth", [])]
    ttm = {"revenue": ttm_from_quarters(quarterly, "revenue"),
           "net_income": ttm_from_quarters(quarterly, "net_income"),
           "eps": ttm_from_quarters(quarterly, "eps_diluted")}
    return {
        "is_financial": fin,
        "financial_kind": kind,
        "model": "financial" if fin else "standard",
        "annual": A,
        "quarterly": Q,
        "latest": latest,
        "growth": growth,
        "ttm": ttm,
        "revenue_consistency": consistency(rg),
        "years_available": len(annual),
        "definitions": METRIC_DEFS,
    }
