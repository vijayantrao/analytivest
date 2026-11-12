"""Tests for: Screener.in import, annual-report facts, portfolio import, alerts, quarterly check, bank data,
and the screener scan job. All offline (fictional sample companies, synthetic files)."""
import copy
import io
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from tests.conftest import AUTH

from app import alerts, db, screener
from app.engine.quarterly import quarterly_check
from app.ingest.annual_report import parse_annual_report
from app.ingest.screener_import import merge_import, parse_screener_export
from app.main import app
from app.portfolio import parse_holdings, resolve_symbol

YEARS = list(range(2017, 2027))  # FY2017..FY2026


def screener_workbook(name="Demo Steady Consumer Ltd", missing_cashflow=False) -> bytes:
    """Synthetic file in the layout of Screener.in's 'Data Sheet' (values in ₹ crore)."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data Sheet"
    dates = [datetime(y, 3, 31) for y in YEARS]
    sales = [2400 * 1.1 ** k for k in range(10)]
    rows = [["COMPANY NAME", name], ["LATEST VERSION", 1], [], ["META"], ["Number of shares", 500000000],
            ["Face Value", 1], ["Current Price", 820], ["Market Capitalization", 41000], [],
            ["PROFIT & LOSS"], ["Report Date", *dates], ["Sales", *sales],
            ["Raw Material Cost", *[s * 0.55 for s in sales]], ["Change in Inventory", *[10] * 10],
            ["Power and Fuel", *[s * 0.02 for s in sales]], ["Other Mfr. Exp", *[s * 0.03 for s in sales]],
            ["Employee Cost", *[s * 0.08 for s in sales]], ["Selling and admin", *[s * 0.06 for s in sales]],
            ["Other Expenses", *[s * 0.04 for s in sales]], ["Other Income", *[30] * 10],
            ["Depreciation", *[s * 0.025 for s in sales]], ["Interest", *[12] * 10],
            ["Profit before tax", *[s * 0.19 for s in sales]], ["Tax", *[s * 0.048 for s in sales]],
            ["Net profit", *[s * 0.142 for s in sales]], ["Dividend Amount", *[s * 0.07 for s in sales]], [],
            ["Quarters"], ["Report Date", datetime(2025, 6, 30), datetime(2025, 9, 30), datetime(2025, 12, 31),
                           datetime(2026, 3, 31), datetime(2026, 6, 30)],
            ["Sales", 1500, 1600, 1700, 2000, 1700], ["Expenses", 1200, 1270, 1350, 1580, 1360],
            ["Other Income", 8, 8, 8, 8, 8], ["Depreciation", 40, 41, 42, 44, 45], ["Interest", 3, 3, 3, 3, 3],
            ["Profit before tax", 265, 294, 313, 381, 300], ["Tax", 66, 73, 78, 95, 75],
            ["Net profit", 199, 221, 235, 286, 225], ["Operating Profit", 300, 330, 350, 420, 340], [],
            ["BALANCE SHEET"], ["Report Date", *dates], ["Equity Share Capital", *[50] * 10],
            ["Reserves", *[1500 + 300 * k for k in range(10)]], ["Borrowings", *[150] * 10],
            ["Other Liabilities", *[700 + 50 * k for k in range(10)]],
            ["Total", *[2400 + 350 * k for k in range(10)]], ["Net Block", *[900 + 80 * k for k in range(10)]],
            ["Capital Work in Progress", *[50] * 10], ["Investments", *[200] * 10],
            ["Other Assets", *[1250 + 270 * k for k in range(10)]], ["Total", *[2400 + 350 * k for k in range(10)]],
            ["Receivables", *[s * 0.08 for s in sales]], ["Inventory", *[s * 0.12 for s in sales]],
            ["Cash & Bank", *[300 + 40 * k for k in range(10)]], ["No. of Equity Shares", *[500000000] * 10],
            ["New Bonus Shares", *[None] * 10], ["Face value", *[1] * 10], []]
    if not missing_cashflow:
        rows += [["CASH FLOW:"], ["Report Date", *dates],
                 ["Cash from Operating Activity", *[s * 0.15 for s in sales]],
                 ["Cash from Investing Activity", *[-s * 0.05 for s in sales]],
                 ["Cash from Financing Activity", *[-s * 0.08 for s in sales]], ["Net Cash Flow", *[5] * 10], []]
    rows += [["PRICE:", *[300 + 50 * k for k in range(10)]], [], ["DERIVED:"],
             ["Adjusted Equity Shares in Cr", *[50] * 10]]
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture(scope="module")
def client():
    with TestClient(app, headers=AUTH) as c:
        yield c


# ---------------- Screener.in import ----------------
def test_screener_export_parsed_to_canonical_rupees():
    r = parse_screener_export(screener_workbook())
    assert r["years"] == 10 and r["range"] == "FY2017 → FY2026" and len(r["quarterly"]) == 5
    fy26 = r["annual"][-1]["fields"]
    sales = 2400 * 1.1 ** 9
    assert fy26["revenue"] == pytest.approx(sales * 1e7)
    expenses = sales * (0.55 + 0.02 + 0.03 + 0.08 + 0.06 + 0.04) - 10  # change in inventory reduces expenses
    assert fy26["ebitda"] == pytest.approx((sales - expenses) * 1e7)
    assert fy26["equity"] == pytest.approx((50 + 1500 + 2700) * 1e7)
    assert fy26["eps_diluted"] == pytest.approx(sales * 0.142 / 50)  # ₹ crore profit / crore shares
    assert fy26["cfo"] == pytest.approx(sales * 0.15 * 1e7)
    assert r["quarterly"][-1]["fields"]["ebitda"] == pytest.approx(340e7)


def test_screener_import_rejects_wrong_file():
    from app.ingest.screener_import import ImportError_
    with pytest.raises(ImportError_):
        parse_screener_export(b"not an excel file")


def test_merge_prefers_import_and_fills_gaps_from_provider():
    imp = parse_screener_export(screener_workbook())
    bundle = {"annual": [{"period_end": "2026-03-31", "label": "FY2026",
                          "fields": {"revenue": 1.0, "capex": 99.0, "net_income_continuing": 5.0}},
                         {"period_end": "2027-03-31", "label": "FY2027", "fields": {"revenue": 2.0}}],
              "quarterly": []}
    out = merge_import(bundle, {"payload": imp, "imported_at": 0})
    fy26 = next(p for p in out["annual"] if p["label"] == "FY2026")
    assert fy26["fields"]["revenue"] != 1.0 and fy26["fields"]["capex"] == 99.0  # import wins; capex filled
    assert "net_income_continuing" not in fy26["fields"]  # not mixed across sources
    assert out["annual"][-1]["label"] == "FY2027" and len(out["annual"]) == 11
    assert out["imported"]["years"] == 10


def test_import_endpoint_extends_history(client):
    r = client.post("/api/company/DEMO-STEADY/import",
                    files={"file": ("Demo.xlsx", screener_workbook(), "application/vnd.ms-excel")})
    assert r.status_code == 200, r.text
    a = client.get("/api/company/DEMO-STEADY/analysis").json()
    assert a["metrics"]["years_available"] == 10 and a["imported"]["range"] == "FY2017 → FY2026"
    assert a["metrics"]["growth"]["revenue_cagr_5y"]["value"] == pytest.approx(10.0, abs=0.1)
    bad = client.post("/api/company/DEMO-STEADY/import",
                      files={"file": ("x.xlsx", screener_workbook(name="Some Other Company Ltd"), "application/octet-stream")})
    assert bad.status_code == 422 and "not" in bad.json()["detail"]
    client.delete("/api/company/DEMO-STEADY/import")
    assert client.get("/api/company/DEMO-STEADY/analysis").json()["metrics"]["years_available"] == 6


# ---------------- Annual report ----------------
AR_PAGES = [
    "ACME BANK LIMITED\nANNUAL REPORT 2025-26\nfor the financial year ended March 31, 2026",
    "INDEPENDENT AUDITOR'S REPORT\nOpinion\nBasis for Qualified Opinion\nWe draw attention to Note 42 regarding "
    "recoverability of loans to a related entity of Rs. 120 crore.\nEmphasis of Matter\nWe draw attention to Note 51.",
    "SHAREHOLDING PATTERN AS ON MARCH 31, 2026\nCategory  No. of shares  % holding\n"
    "Promoter and Promoter Group  45,10,00,000  56.32\nPublic  35,00,00,000  43.68\n"
    "None of the shares held by the promoters are pledged.",
    "Contingent liabilities not provided for: claims against the bank not acknowledged as debts amount to "
    "Rs. 1,234.50 crore.\nKey ratios: Gross NPA 2.85% of gross advances; Net NPA 0.95%; Capital adequacy ratio "
    "16.40%; Provision coverage ratio 72.5%.",
]


def test_annual_report_facts_with_evidence():
    r = parse_annual_report(AR_PAGES)
    f, ev = r["facts"], r["evidence"]
    assert f["as_of"] == "FY2026" and f["auditor_qualification"] is True and ev["auditor_qualification"]["page"] == 2
    assert "emphasis_of_matter" in ev
    assert f["promoter_holding_pct"] == pytest.approx(56.32) and f["promoter_pledge_pct"] == 0.0
    assert f["contingent_liabilities_cr"] == pytest.approx(1234.5)
    assert (f["gnpa_pct"], f["nnpa_pct"], f["car_pct"], f["pcr_pct"]) == (2.85, 0.95, 16.4, 72.5)


def test_clean_audit_opinion_detected():
    r = parse_annual_report(["INDEPENDENT AUDITOR'S REPORT\nOpinion\nIn our opinion and to the best of our information "
                             "and according to the explanations given to us, the financial statements give a true and "
                             "fair view in conformity with the accounting principles."])
    assert r["facts"]["auditor_qualification"] is False


# ---------------- Bank data entry ----------------
def test_bank_figures_feed_asset_quality_and_flags(client):
    base = client.get("/api/company/DEMO-BANK/analysis").json()
    assert base["scores"]["categories"]["asset_quality"]["score"] is None
    client.put("/api/company/DEMO-BANK/notes", json={"gnpa_pct": 6.2, "nnpa_pct": 3.4, "car_pct": 11.9, "pcr_pct": 52,
                                                    "bank_as_of": "Q2 FY27"})
    a = client.get("/api/company/DEMO-BANK/analysis").json()
    aq = a["scores"]["categories"]["asset_quality"]
    assert aq["score"] is not None and aq["score"] < 30
    assert {"high_gnpa", "high_nnpa", "low_car", "low_pcr"} <= {f["id"] for f in a["flags"]}
    client.put("/api/company/DEMO-BANK/notes", json={})


# ---------------- Quarterly check ----------------
def _q(end, **f):
    return {"period_end": end, "label": f"Q {end}", "fields": f}


def test_quarterly_like_for_like():
    b = {"quarterly": [_q("2025-06-30", revenue=100.0, net_income=10.0, operating_income=15.0),
                       _q("2026-03-31", revenue=120.0, net_income=12.0, operating_income=18.0),
                       _q("2026-06-30", revenue=90.0, net_income=6.0, operating_income=9.0)]}
    q = quarterly_check(b, is_financial=False)
    assert q["year_ago"] == "Q 2025-06-30" and q["prev"] == "Q 2026-03-31"
    rev = next(r for r in q["rows"] if r["key"] == "revenue")
    assert rev["yoy_pct"] == pytest.approx(-10.0) and rev["qoq_pct"] == pytest.approx(-25.0)
    assert q["verdict"] == "Weak quarter"
    titles = {s["title"] for s in q["signals"]}
    assert "Net profit fell year on year" in titles and "Operating margin compressed" in titles


def test_quarterly_without_year_ago_is_honest():
    q = quarterly_check({"quarterly": [_q("2026-03-31", revenue=1.0), _q("2026-06-30", revenue=2.0)]}, False)
    assert q["verdict"] == "Not enough history" and q["note"]


# ---------------- Portfolio ----------------
ZERODHA = b"Instrument,Qty.,Avg. cost,LTP,Cur. val,P&L,Net chg.,Day chg.\nTCS,10,3200.5,2460,24600,-7405,-23.1,-0.2\n" \
          b"HDFCBANK,25,1500,712,17800,-19700,-52.5,-2.3\nIDEA-BE,0,8,9,0,0,0,0\nTotal,,,,42400,,,\n"


def test_zerodha_csv_and_symbol_resolution():
    p = parse_holdings(ZERODHA, "holdings.csv")
    assert [(i["raw"], i["quantity"], i["avg_cost"]) for i in p["items"]] == [("TCS", 10, 3200.5), ("HDFCBANK", 25, 1500)]
    assert p["skipped"] and "zero quantity" in p["skipped"][0]
    assert resolve_symbol(p["items"][0], lambda q: {}) == ("TCS.NS", None)


def test_groww_xlsx_by_name():
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in (["Holdings statement"], [], ["Stock Name", "ISIN", "Quantity", "Average buy price", "Buy value"],
              ["Demo Steady Consumer", "INE000X01010", 4, 700, 2800]):
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    p = parse_holdings(buf.getvalue(), "groww.xlsx")
    item = p["items"][0]
    assert item["name"] == "Demo Steady Consumer" and item["quantity"] == 4 and item["avg_cost"] == 700
    fake = lambda q: {"results": [{"market": "IN", "primary_symbol": "DEMOSTEADY.NS", "name": "Demo Steady Consumer Ltd"}]}  # noqa: E731
    assert resolve_symbol(item, fake)[0] == "DEMOSTEADY.NS"


def test_portfolio_endpoints(client):
    csv = b"Symbol,Quantity,Average Price\nDEMO-STEADY,12,700\nDEMO-LEVER,40,250\n"
    r = client.post("/api/portfolio/import", files={"file": ("p.csv", csv, "text/csv")}).json()
    # plain tickers become NSE symbols; DEMO-* are sample symbols, so they are resolved as given
    assert [x["symbol"] for x in r["added"]] == ["DEMO-STEADY", "DEMO-LEVER"]
    client.delete("/api/portfolio")
    assert client.post("/api/portfolio", json={"symbol": "DEMO-STEADY", "quantity": 5, "avg_cost": 700}).status_code == 200
    assert client.get("/api/portfolio").json()["holdings"][0]["quantity"] == 5
    row = client.get("/api/company/DEMO-STEADY/summary").json()
    assert row["business_quality"] is not None and row["sector"]
    client.delete("/api/portfolio")


# ---------------- Alerts ----------------
def test_alert_diff_rules():
    prev = {"name": "X", "flag_ids": {"a": {"title": "Old", "severity": "low"}}, "decision_label": "Strong fundamentals",
            "business_quality": 80, "financial_risk": 10, "valuation_label": "Within estimated fair-value range",
            "price": 100.0, "fv_low": 90.0, "quarter": "Q Mar-2026"}
    cur = copy.deepcopy(prev)
    cur.update(flag_ids={"b": {"title": "New flag", "severity": "high"}}, decision_label="Mixed financial picture",
               business_quality=65, price=85.0, valuation_label="Potentially undervalued", quarter="Q Jun-2026",
               quarter_verdict="Weak quarter")
    kinds = {a["kind"] for a in alerts.diff(prev, cur)}
    assert {"new_flag", "flag_resolved", "decision_change", "score_move", "valuation_change", "price_move",
            "below_fair_range", "new_results"} <= kinds
    assert alerts.diff(prev, copy.deepcopy(prev)) == []


def test_alert_check_records_baseline_then_detects_change(client, monkeypatch):
    db.watchlist_add("DEMO-LEVER", "Demo")
    assert alerts.check_symbol("DEMO-LEVER") == []  # first run = baseline
    snap = db.snapshot_last("DEMO-LEVER")["summary"]
    snap["decision_label"] = "Strong fundamentals"  # pretend it used to look different
    db.snapshot_put("DEMO-LEVER", snap)
    new = alerts.check_symbol("DEMO-LEVER")
    assert any(a["kind"] == "decision_change" for a in new)
    body = client.get("/api/alerts").json()
    assert body["unread"] >= 1 and "DEMO-LEVER" in body["tracked"]
    client.post("/api/alerts/read", json={})
    assert client.get("/api/alerts/count").json()["unread"] == 0
    db.watchlist_remove("DEMO-LEVER")


# ---------------- Screener scan ----------------
def test_scan_job_stores_summaries(monkeypatch):
    monkeypatch.setattr(screener, "universe", lambda size: [{"symbol": s, "name": s} for s in
                                                            ("DEMO-STEADY", "DEMO-LEVER", "DEMO-BANK")][:size])
    screener.run_scan("scan-test", 3, include_peers=False)
    job = db.job_get("scan-test")
    assert job["status"] == "done" and "3 companies" in job["message"]
    rows = {r["symbol"]: r["summary"] for r in db.scan_list()}
    assert rows["DEMO-LEVER"]["financial_risk_label"] == "High" and rows["DEMO-STEADY"]["fair_value"]
