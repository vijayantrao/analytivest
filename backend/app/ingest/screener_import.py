"""Import a company's history from the Excel file Screener.in lets registered users export
("Export to Excel" on a company page). Its "Data Sheet" holds ~10 years of annual P&L, balance sheet
and cash flow plus ~10 quarters, in ₹ crore.

The parser works from row labels (not fixed cell positions), so small layout changes don't break it.
Values are converted to absolute rupees, the app's internal unit. The user downloads the file under
their own Screener account; nothing is scraped.
"""
from __future__ import annotations

import io
import re
from datetime import date, datetime
from typing import Any, Optional

from .extract import check_archive

CR = 1e7
SECTIONS = {"profit & loss": "pl", "quarters": "q", "balance sheet": "bs", "cash flow": "cf", "price": "price",
            "derived": "derived"}


class ImportError_(Exception):
    pass


def _label(v: Any) -> str:
    return re.sub(r"[\s:]+$", "", str(v or "").strip()).lower()


def _num(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def _date(v: Any) -> Optional[str]:
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, str):
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%b-%y", "%b %Y", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(v.strip(), fmt).date().isoformat()
            except ValueError:
                pass
    return None


def _read_sheet(data: bytes) -> list[list[Any]]:
    import openpyxl
    try:
        check_archive(data)
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as e:
        raise ImportError_(f"Not a readable Excel file: {e}") from e
    sheet = next((ws for ws in wb.worksheets if ws.title.strip().lower() == "data sheet"), None)
    if sheet is None:
        for ws in wb.worksheets:
            rows = list(ws.iter_rows(values_only=True))
            if any(_label(r[0] if r else "") == "profit & loss" for r in rows):
                return [list(r) for r in rows]
        raise ImportError_("No 'Data Sheet' found. Use the Excel file from Screener.in's 'Export to Excel' button.")
    return [list(r) for r in sheet.iter_rows(values_only=True)]


def _sections(rows: list[list[Any]]) -> dict[str, dict[str, Any]]:
    """{section: {"dates": [...], "rows": {label: [values aligned to dates]}}}."""
    out: dict[str, dict[str, Any]] = {}
    current = None
    for r in rows:
        if not r:
            continue
        lab = _label(r[0])
        if lab in SECTIONS:
            current = SECTIONS[lab]
            out[current] = {"dates": [], "rows": {}, "single": None}
            # PRICE row carries values on the section line itself
            vals = [_num(v) for v in r[1:]]
            if any(v is not None for v in vals):
                out[current]["single"] = vals
            continue
        if current is None:
            continue
        if lab == "report date":
            out[current]["dates"] = [_date(v) for v in r[1:]]
            continue
        if lab:
            key = lab
            if key in out[current]["rows"]:  # e.g. balance sheet has two "Total" rows
                key = key + "#2"
            out[current]["rows"][key] = [_num(v) for v in r[1:]]
    return out


def _meta(rows: list[list[Any]]) -> dict[str, Any]:
    meta = {}
    for r in rows[:20]:
        if r and r[0] and len(r) > 1:
            meta[_label(r[0])] = r[1]
    return meta


def _get(sec: dict[str, Any], label: str, i: int) -> Optional[float]:
    vals = sec["rows"].get(label)
    return vals[i] if vals and i < len(vals) else None


def parse_screener_export(data: bytes) -> dict[str, Any]:
    rows = _read_sheet(data)
    meta = _meta(rows)
    secs = _sections(rows)
    if "pl" not in secs or not any(secs["pl"]["dates"]):
        raise ImportError_("Could not find the PROFIT & LOSS section with report dates.")
    warnings: list[str] = []

    # Split-adjusted share counts (crore) aligned to the P&L dates, when Screener provides them
    adj_shares = secs.get("derived", {}).get("rows", {}).get("adjusted equity shares in cr")

    pl = secs["pl"]
    annual: dict[str, dict[str, Any]] = {}
    for i, d in enumerate(pl["dates"]):
        if not d:
            continue
        sales = _get(pl, "sales", i)
        if sales is None:
            continue
        cost_lines = ["raw material cost", "power and fuel", "other mfr. exp", "employee cost", "selling and admin",
                      "other expenses"]
        expenses = sum((_get(pl, k, i) or 0.0) for k in cost_lines) - (_get(pl, "change in inventory", i) or 0.0)
        dep, intr = _get(pl, "depreciation", i), _get(pl, "interest", i)
        pbt, tax, ni = _get(pl, "profit before tax", i), _get(pl, "tax", i), _get(pl, "net profit", i)
        f: dict[str, float] = {"revenue": sales * CR}
        if any(_get(pl, k, i) is not None for k in cost_lines):
            f["ebitda"] = (sales - expenses) * CR
            rm = _get(pl, "raw material cost", i)
            if rm is not None:
                f["cost_of_revenue"] = (rm - (_get(pl, "change in inventory", i) or 0.0)) * CR
            if dep is not None:
                f["operating_income"] = (sales - expenses - dep) * CR
        for key, v in (("depreciation", dep), ("interest_expense", intr), ("pbt", pbt), ("tax", tax),
                       ("net_income", ni), ("dividends_paid", _get(pl, "dividend amount", i))):
            if v is not None:
                f[key] = abs(v) * CR if key in ("interest_expense", "dividends_paid") else v * CR
        if pbt is not None and intr is not None:
            f["ebit"] = (pbt + intr) * CR
        if adj_shares and i < len(adj_shares) and adj_shares[i]:
            sh = adj_shares[i] * CR
            f["shares_basic_avg"] = f["shares_diluted_avg"] = sh
            if ni is not None:
                f["eps_basic"] = f["eps_diluted"] = ni * CR / sh
        annual[d] = f

    bs = secs.get("bs")
    if bs:
        for i, d in enumerate(bs["dates"]):
            if not d:
                continue
            f = annual.setdefault(d, {})
            cap, res = _get(bs, "equity share capital", i), _get(bs, "reserves", i)
            total = _get(bs, "total", i)
            if cap is not None and res is not None:
                f["equity"] = (cap + res) * CR
            for key, lab in (("total_debt", "borrowings"), ("net_ppe", "net block"), ("receivables", "receivables"),
                             ("inventory", "inventory"), ("cash", "cash & bank")):
                v = _get(bs, lab, i)
                if v is not None:
                    f[key] = v * CR
            if total is not None:
                f["total_assets"] = total * CR
                if "equity" in f:
                    f["total_liabilities"] = f["total_assets"] - f["equity"]
            if "shares_basic_avg" not in f:
                n_sh = _get(bs, "no. of equity shares", i)
                if n_sh:
                    f["shares_outstanding"] = n_sh
            else:
                f["shares_outstanding"] = f["shares_basic_avg"]

    cf = secs.get("cf")
    if cf:
        for i, d in enumerate(cf["dates"]):
            if not d:
                continue
            f = annual.setdefault(d, {})
            for key, lab in (("cfo", "cash from operating activity"), ("cfi", "cash from investing activity"),
                             ("cff", "cash from financing activity")):
                v = _get(cf, lab, i)
                if v is not None:
                    f[key] = v * CR

    quarterly = []
    q = secs.get("q")
    if q:
        latest_sh = None
        if adj_shares:
            latest_sh = next((s for s in reversed(adj_shares) if s), None)
        for i, d in enumerate(q["dates"]):
            if not d or _get(q, "sales", i) is None:
                continue
            f = {"revenue": _get(q, "sales", i) * CR}
            op = _get(q, "operating profit", i)
            if op is None and _get(q, "expenses", i) is not None:
                op = _get(q, "sales", i) - _get(q, "expenses", i)
            if op is not None:
                f["ebitda"] = op * CR
                dep = _get(q, "depreciation", i)
                if dep is not None:
                    f["operating_income"] = (op - dep) * CR
            for key, lab in (("pbt", "profit before tax"), ("tax", "tax"), ("net_income", "net profit"),
                             ("depreciation", "depreciation"), ("interest_expense", "interest")):
                v = _get(q, lab, i)
                if v is not None:
                    f[key] = v * CR
            if latest_sh and "net_income" in f:
                f["eps_diluted"] = f["eps_basic"] = f["net_income"] / (latest_sh * CR)
            quarterly.append({"period_end": d, "label": f"Q {datetime.fromisoformat(d).strftime('%b-%Y')}", "fields": f})

    periods = [{"period_end": d, "label": f"FY{d[:4]}", "fields": f,
                "notes": ["Source: Screener.in export (user-imported); values in the export were in ₹ crore."]}
               for d, f in sorted(annual.items()) if f.get("revenue") is not None]
    if len(periods) < 2:
        raise ImportError_("Fewer than two years of data were found in the export.")
    if not adj_shares:
        warnings.append("No 'Adjusted Equity Shares' row was found, so EPS for imported years is not computed.")
    if not any("cfo" in p["fields"] for p in periods):
        warnings.append("No cash-flow section was found.")
    warnings.append("Capital expenditure and current assets/liabilities are not in the export; they come from the "
                    "live data provider for the recent years it covers, so free cash flow and liquidity ratios "
                    "for older years remain unavailable.")
    name = meta.get("company name")
    return {"company_name": str(name).strip() if name else None, "annual": periods, "quarterly": quarterly,
            "years": len(periods), "range": f"{periods[0]['label']} → {periods[-1]['label']}",
            "source": "Screener.in export (user-imported)", "warnings": warnings}


# Fields the live provider may still supply for an imported year (things the export lacks)
FILL_FROM_PROVIDER = {"capex", "current_assets", "current_liabilities", "short_term_investments", "lease_liabilities",
                      "minority_interest", "payables", "goodwill_intangibles", "change_receivables", "buybacks",
                      "share_issuance", "acquisitions", "unusual_items", "net_interest_income", "interest_income",
                      "net_loans"}


def _same_period(a: str, b: str) -> bool:
    return abs((date.fromisoformat(a) - date.fromisoformat(b)).days) <= 10


def merge_import(bundle: dict[str, Any], imported: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Imported periods replace the provider's for the same dates (one consistent source per year);
    the provider fills only the fields the export doesn't have, and adds any newer periods."""
    if not imported:
        return bundle
    imp = imported["payload"]
    for key in ("annual", "quarterly"):
        prov = bundle.get(key) or []
        merged = []
        used = set()
        for ip in imp.get(key, []):
            p = {"period_end": ip["period_end"], "label": ip["label"], "fields": dict(ip["fields"]),
                 "notes": list(ip.get("notes", [])), "source": "import"}
            for k, pp in enumerate(prov):
                if _same_period(pp["period_end"], ip["period_end"]):
                    used.add(k)
                    for f, v in pp["fields"].items():
                        if f in FILL_FROM_PROVIDER and f not in p["fields"]:
                            p["fields"][f] = v
            merged.append(p)
        merged += [pp for k, pp in enumerate(prov) if k not in used]
        bundle[key] = sorted(merged, key=lambda p: p["period_end"])
    bundle["imported"] = {"source": imp.get("source"), "imported_at": imported.get("imported_at"),
                          "range": imp.get("range"), "years": imp.get("years"), "company_name": imp.get("company_name")}
    return bundle
