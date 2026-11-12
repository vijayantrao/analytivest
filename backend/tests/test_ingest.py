import copy
import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from tests.conftest import AUTH

from app.engine.ipo import analyse_ipo
from app.engine.ipo_decision import decide
from app.ingest.extract import ExtractionError, extract_text
from app.ingest.rhp import normalise, parse_offer_document
from app.ingest.sample_rhp import build_sample_rhp
from app.main import app
from app.providers.sample import SAMPLE_IPO

COVER = (
    "RED HERRING PROSPECTUS\n\nACME WIDGETS LIMITED\n\n"
    "INITIAL PUBLIC OFFERING ... COMPRISING A FRESH ISSUE OF UP TO 50,00,000 EQUITY SHARES OF FACE VALUE OF Rs. 10 EACH "
    "AGGREGATING UP TO Rs. 120.00 CRORE AND AN OFFER FOR SALE OF UP TO 30,00,000 EQUITY SHARES AGGREGATING UP TO "
    "Rs. 72.00 CRORE.\nPRICE BAND: Rs. 230 TO Rs. 240 PER EQUITY SHARE\n"
    "BIDS CAN BE MADE FOR A MINIMUM OF 62 EQUITY SHARES AND IN MULTIPLES OF 62 EQUITY SHARES THEREAFTER\n"
    "BID/OFFER OPENS ON: TUESDAY, 3RD MARCH, 2026\n"
)


@pytest.fixture(scope="module")
def sample_pdf():
    return build_sample_rhp()


def test_pdf_tables_rebuilt_into_rows(sample_pdf):
    d = extract_text(sample_pdf, "rhp.pdf")
    assert d.kind == "pdf" and len(d.pages) == 10
    fin_page = next(p for p in d.pages if p.startswith("SUMMARY OF RESTATED"))  # not the table of contents
    assert any(ln.startswith("Revenue from operations") and "20,100.00" in ln for ln in fin_page.split("\n"))


def test_sample_rhp_extracts_every_key_field(sample_pdf):
    r = parse_offer_document(extract_text(sample_pdf, "rhp.pdf").pages)
    dr, ev = r["draft"], r["evidence"]
    assert r["doc_type"] == "RHP" and not r["missing_required"]
    assert dr["company_name"] == "Demo Precision Components Limited"
    assert (dr["price_band_low"], dr["price_band_high"], dr["lot_size"], dr["face_value"]) == (415, 436, 34, 2)
    assert dr["fresh_issue_cr"] == pytest.approx(400.0) and dr["ofs_cr"] == pytest.approx(600.0)  # million -> crore
    assert dr["pre_issue_shares"] == 10.5e7 and dr["post_issue_shares"] == 114174312
    assert (dr["promoter_pre_pct"], dr["promoter_post_pct"]) == (88.0, 64.0)
    assert dr["open_date"] == "2026-11-02" and dr["close_date"] == "2026-11-04"
    fin = {f["fy"]: f for f in dr["financials"]}
    assert set(fin) == {"FY2024", "FY2025", "FY2026"}  # part-year column ignored
    assert fin["FY2026"]["revenue_cr"] == pytest.approx(2010.0) and fin["FY2024"]["pat_cr"] == pytest.approx(96.0)
    assert fin["FY2026"]["capex_cr"] == pytest.approx(160.0)  # (1,600.00) million outflow -> positive crore
    purposes = {u["purpose"]: u["amount_cr"] for u in dr["use_of_proceeds"]}
    assert purposes["General corporate purposes"] == pytest.approx(80.0)
    assert [p["pe"] for p in dr["manual_peers"]] == [32.0, 26.0, 41.0]  # company's own row excluded
    assert len(dr["risk_factors"]) == 6 and dr["risk_factors"][0].startswith("Our top five customers")
    assert dr["top_customer_concentration_pct"] == 58.2 and dr["contingent_liabilities_cr"] == pytest.approx(45.0)
    assert ev["price_band_high"]["page"] == 1 and ev["financials"]["page"] == 9  # evidence points at the page


def test_rupee_variants_and_soft_hyphens_are_normalised():
    t = normalise("Rs.415 to ` 436, pre­Offer, ₹ 2 each, [ ● ]")
    assert "₹ 415" in t and "₹ 436" in t and "pre-Offer" in t and "[●]" in t


def test_plain_text_and_ordinal_dates():
    r = parse_offer_document(extract_text(COVER.encode(), "rhp.txt").pages)
    dr = r["draft"]
    assert dr["company_name"] == "Acme Widgets Limited"
    assert (dr["price_band_low"], dr["price_band_high"]) == (230, 240)
    assert dr["fresh_issue_cr"] == 120.0 and dr["ofs_cr"] == 72.0 and dr["lot_size"] == 62
    assert dr["open_date"] == "2026-03-03"


def test_drhp_without_price_band_warns_and_cannot_be_decided():
    text = COVER.replace("RED HERRING PROSPECTUS", "DRAFT RED HERRING PROSPECTUS").replace(
        "PRICE BAND: Rs. 230 TO Rs. 240", "PRICE BAND: Rs. [ ● ] TO Rs. [ ● ]")
    r = parse_offer_document(extract_text(text.encode(), "drhp.txt").pages)
    assert r["doc_type"] == "DRHP" and "price_band_high" not in r["draft"]
    assert any("not yet fixed" in w for w in r["warnings"])
    d = decide(analyse_ipo(r["draft"], []), r["draft"])
    assert d["verdict"] == "INSUFFICIENT"


def test_docx_html_rtf_zip_formats(sample_pdf):
    import docx
    doc = docx.Document()
    for line in COVER.split("\n"):
        doc.add_paragraph(line)
    buf = io.BytesIO()
    doc.save(buf)
    assert extract_text(buf.getvalue(), "x.docx").kind == "docx"
    assert parse_offer_document(extract_text(buf.getvalue(), "x.docx").pages)["draft"]["price_band_high"] == 240

    html = "<html><body><p>" + COVER.replace("\n", "</p><p>") + "</p></body></html>"
    h = extract_text(html.encode(), "x.html")
    assert h.kind == "html" and parse_offer_document(h.pages)["draft"]["lot_size"] == 62

    rtf = r"{\rtf1\ansi " + COVER.replace("\n", r"\par ") + "}"
    assert parse_offer_document(extract_text(rtf.encode(), "x.rtf").pages)["draft"]["price_band_low"] == 230

    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w") as z:
        z.writestr("readme.txt", "hello")
        z.writestr("RHP.pdf", sample_pdf)
    zd = extract_text(zbuf.getvalue(), "rhp.zip")
    assert zd.kind == "pdf" and "RHP.pdf" in zd.warnings[0]


def test_unreadable_inputs_raise_clear_errors():
    with pytest.raises(ExtractionError):
        extract_text(b"", "empty.pdf")
    with pytest.raises(ExtractionError):
        extract_text(bytes(range(256)) * 10, "noise.bin")


def test_legacy_binary_text_recovery():
    blob = b"\xd0\xcf\x11\xe0" + b"\x00" * 50 + COVER.encode("utf-16le") * 3 + b"\x00\x01\x02" * 100
    d = extract_text(blob, "old.doc")
    assert d.kind == "binary-recovered" and "PRICE BAND" in "".join(d.pages)


# ---------------- decision ----------------
def test_decision_borderline_for_sample_with_structural_concerns():
    p = SAMPLE_IPO["payload"]
    d = decide(analyse_ipo(p, []), p)
    assert d["verdict"] == "BORDERLINE" and len(d["serious_concerns"]) >= 2
    assert d["reasons_for"] and d["reasons_against"] and "not personalised advice" in d["disclaimer"]


def test_decision_skip_when_overpriced():
    p = copy.deepcopy(SAMPLE_IPO["payload"])
    p.update(price_band_low=600, price_band_high=640)
    d = decide(analyse_ipo(p, []), p)
    assert d["verdict"] == "SKIP" and d["deal_breakers"]


def test_decision_skip_when_loss_making():
    p = copy.deepcopy(SAMPLE_IPO["payload"])
    p["financials"][-1]["pat_cr"] = -20
    d = decide(analyse_ipo(p, []), p)
    assert d["verdict"] == "SKIP" and any("Loss-making" in b for b in d["deal_breakers"])


def test_decision_apply_for_clean_reasonably_priced_issue():
    p = copy.deepcopy(SAMPLE_IPO["payload"])
    p.update(price_band_low=300, price_band_high=315, fresh_issue_cr=700, ofs_cr=150, promoter_pre_pct=80,
             promoter_post_pct=68, top_customer_concentration_pct=30)
    d = decide(analyse_ipo(p, []), p)
    assert d["verdict"] == "APPLY", d


def test_decision_ignores_gmp_and_subscription():
    p = copy.deepcopy(SAMPLE_IPO["payload"])
    base = decide(analyse_ipo(p, []), p)
    p["gmp"] = {"value": 500}
    p["subscription"] = {"total": 400}
    hyped = decide(analyse_ipo(p, []), p)
    assert hyped["verdict"] == base["verdict"]


# ---------------- API ----------------
def test_upload_endpoint_round_trip(sample_pdf):
    with TestClient(app, headers=AUTH) as c:
        r = c.post("/api/ipos/upload", files={"file": ("SAMPLE.pdf", sample_pdf, "application/pdf")})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["doc_type"] == "RHP" and body["draft"]["price_band_high"] == 436 and body["evidence"]
        draft = dict(body["draft"], extraction={"document": body["document"], "evidence": body["evidence"]})
        new_id = c.post("/api/ipos", json=draft).json()["id"]
        a = c.get(f"/api/ipos/{new_id}/analysis").json()
        assert a["analysis"]["decision"]["verdict"] in {"APPLY", "BORDERLINE", "SKIP"}
        assert a["input"]["extraction"]["document"]["pages"] == 10
        c.delete(f"/api/ipos/{new_id}")
        bad = c.post("/api/ipos/upload", files={"file": ("x.bin", bytes(range(256)) * 4, "application/octet-stream")})
        assert bad.status_code == 422 and bad.json()["detail"]
        assert c.get("/api/ipos/sample-rhp").content.startswith(b"%PDF")
