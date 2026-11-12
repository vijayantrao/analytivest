"""Heuristic extraction of IPO facts from an Indian offer document (DRHP / RHP / Prospectus).

No language model is used: SEBI-format offer documents follow standard section names and phrasing
("Price Band", "Fresh Issue of up to … Equity Shares aggregating up to ₹ … million", "Summary of
Restated Financial Information", "Comparison with listed industry peers", ...), so targeted patterns
recover most key figures.

Every value is returned with *evidence* (page number, source snippet, confidence). Extraction is
never treated as final: the UI shows the figures for review before anything is analysed.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

UNIT_TO_CR = {"crore": 1.0, "crores": 1.0, "cr": 1.0, "million": 0.1, "mn": 0.1, "millions": 0.1,
              "lakh": 0.01, "lakhs": 0.01, "lacs": 0.01, "lac": 0.01, "billion": 100.0, "bn": 100.0}

NUM = r"\(?-?\d[\d,]*(?:\.\d+)?\)?"
PLACEHOLDER = r"\[\s*[●•l●•■*]?\s*\]"
RUPEE = "₹"


def normalise(text: str) -> str:
    t = text.replace("₹", RUPEE).replace(" ", " ")
    # Dashes and hyphen look-alikes (PDFs often emit soft hyphens U+00AD for ordinary hyphens)
    t = re.sub("[­‐‑‒–—−]", "-", t)
    t = re.sub(r"\b(?:Rs\.?|INR)\s*(?=\d|\[)", RUPEE + " ", t)
    t = re.sub(r"`\s*(?=\d|\[)", RUPEE + " ", t)  # rupee glyph often extracts as a backtick
    t = re.sub(PLACEHOLDER, "[●]", t)
    return t


def to_num(s: str) -> Optional[float]:
    s = s.strip()
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace(",", "")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def _snippet(text: str, start: int, end: int, pad: int = 90) -> str:
    a, b = max(0, start - pad), min(len(text), end + pad)
    return re.sub(r"\s+", " ", text[a:b]).strip()


class Doc:
    def __init__(self, pages: list[str]):
        self.pages = [normalise(p) for p in pages]          # line structure kept (tables, headings)
        self.flat = [re.sub(r"\s+", " ", p) for p in self.pages]  # for sentence patterns across line wraps
        self.lower = [p.lower() for p in self.flat]

    def find(self, pattern: str, pages: Optional[range] = None, flags=re.I | re.S):
        rng = pages if pages is not None else range(len(self.pages))
        rx = re.compile(pattern, flags)
        for i in rng:
            if 0 <= i < len(self.pages):
                m = rx.search(self.flat[i])
                if m:
                    return m, i
        return None, None

    def pages_with(self, needle: str) -> list[int]:
        n = needle.lower()
        return [i for i, p in enumerate(self.lower) if n in p]

    def heading_page(self, heading: str, min_chars: int = 800) -> Optional[int]:
        """First page where `heading` stands on its own line (skipping the table of contents)."""
        rx = re.compile(r"^\s*(?:section\s+[ivx]+\s*[:\-–]?\s*)?" + heading + r"\s*$", re.I | re.M)
        toc_rx = re.compile(r"\.{4,}\s*\d+|\s\d{1,3}\s*$")
        for i, p in enumerate(self.pages):
            for m in rx.finditer(p):
                line = p[m.start():m.end()]
                if not toc_rx.search(line) and len(p) >= min_chars and "table of contents" not in self.lower[i]:
                    return i
        return None


class Extraction:
    def __init__(self):
        self.draft: dict[str, Any] = {}
        self.evidence: dict[str, dict[str, Any]] = {}
        self.warnings: list[str] = []

    def put(self, field: str, value: Any, page: Optional[int], snippet: str = "", confidence: str = "medium",
            note: str | None = None):
        if value is None or value == "" or value == []:
            return
        self.draft[field] = value
        self.evidence[field] = {"page": None if page is None else page + 1, "snippet": snippet[:300],
                                "confidence": confidence, "note": note}


# ---------------- individual fields ----------------
def _doc_type(d: Doc) -> str:
    head = " ".join(d.lower[:3])
    if "draft red herring prospectus" in head:
        return "DRHP"
    if "red herring prospectus" in head:
        return "RHP"
    if "prospectus" in head:
        return "Prospectus"
    return "Unknown"


def _company_name(d: Doc, x: Extraction):
    skip = ("PRIVATE LIMITED", "BOOK RUNNING", "REGISTRAR", "MANAGER", "SECURITIES", "STOCK EXCHANGE",
            "CAPITAL MARKETS", "INTIME", "KFIN", "BIGSHARE", "SKYLINE")
    rx = re.compile(r"^\s*([A-Z][A-Z0-9&.,'()\- ]{2,80}?\s+(?:LIMITED|LTD\.?))\s*(?:\(.*\))?\s*$", re.M)
    for i in range(min(3, len(d.pages))):
        for m in rx.finditer(d.pages[i]):
            name = re.sub(r"\s+", " ", m.group(1)).strip()
            if not any(s in name for s in skip):
                x.put("company_name", name.title(), i, _snippet(d.pages[i], m.start(), m.end()), "high")
                return


def _amount_cr(num: str, unit: Optional[str]) -> Optional[float]:
    v = to_num(num)
    if v is None:
        return None
    if not unit:
        return None
    return v * UNIT_TO_CR.get(unit.lower().rstrip("."), 1.0)


def _issue(d: Doc, x: Extraction):
    first = range(0, min(40, len(d.pages)))
    # The rupee sign is optional here: OCR often drops it, and "price band" already anchors the context.
    m, i = d.find(r"price band\s*[:\-]?[^.\d\[]{0,100}?" + RUPEE + r"?\s*(" + NUM + r")\s*(?:to|-|and)\s*" + RUPEE + r"?\s*(" + NUM + ")", first)
    if m:
        lo, hi = to_num(m.group(1)), to_num(m.group(2))
        if lo and hi and 0 < lo <= hi < 100000:
            x.put("price_band_low", lo, i, _snippet(d.flat[i], m.start(), m.end()), "high")
            x.put("price_band_high", hi, i, _snippet(d.flat[i], m.start(), m.end()), "high")
    if "price_band_high" not in x.draft:
        m, i = d.find(r"floor price of " + RUPEE + r"\s*(" + NUM + r")[^.]{0,80}?cap price of " + RUPEE + r"\s*(" + NUM + ")", first)
        if m:
            x.put("price_band_low", to_num(m.group(1)), i, _snippet(d.flat[i], m.start(), m.end()), "high")
            x.put("price_band_high", to_num(m.group(2)), i, _snippet(d.flat[i], m.start(), m.end()), "high")
    if "price_band_high" not in x.draft:
        m, i = d.find(r"price band[^.]{0,80}?\[●\]", first)
        if m:
            x.warnings.append("The price band is not yet fixed in this document ([●]), typical of a DRHP. "
                              "Enter it when announced; valuation and the Apply/Skip suggestion need it.")

    m, i = d.find(r"face value of\s*" + RUPEE + r"?\s*(" + NUM + r")\s*each", first)
    if m:
        x.put("face_value", to_num(m.group(1)), i, _snippet(d.flat[i], m.start(), m.end()), "high")

    m, i = d.find(r"(?:bid lot|minimum bid lot)[^\d\[]{0,60}?(\d[\d,]{0,6})\s*equity shares", first)
    if not m:
        m, i = d.find(r"minimum of\s*(\d[\d,]{0,6})\s*equity shares\s*and in multiples of", first)
    if m:
        x.put("lot_size", int(to_num(m.group(1)) or 0) or None, i, _snippet(d.flat[i], m.start(), m.end()), "high")

    fresh_rx = (r"fresh issue of (?:up to )?(" + NUM + r"|\[●\])\s*equity shares[^.]{0,260}?aggregating (?:up to )?"
                + RUPEE + r"?\s*(" + NUM + r"|\[●\])\s*(crores?|million|lakhs?|billion)")
    m, i = d.find(fresh_rx, first)
    if m:
        cr = _amount_cr(m.group(2), m.group(3)) if m.group(2) != "[●]" else None
        if cr is not None:
            x.put("fresh_issue_cr", round(cr, 2), i, _snippet(d.flat[i], m.start(), m.end()), "high",
                  f"Stated as {m.group(2)} {m.group(3)}")
        if m.group(1) != "[●]":
            x.put("fresh_issue_shares", to_num(m.group(1)), i, _snippet(d.flat[i], m.start(), m.end()), "medium")
    elif d.find(r"offer for sale", first)[0] and not d.find(r"fresh issue", first)[0]:
        x.put("fresh_issue_cr", 0.0, None, "No fresh issue mentioned on the cover pages", "medium",
              "Entire offer appears to be an offer for sale")

    ofs_rx = (r"offer for sale of (?:up to )?(" + NUM + r"|\[●\])\s*equity shares[^.]{0,260}?aggregating (?:up to )?"
              + RUPEE + r"?\s*(" + NUM + r"|\[●\])\s*(crores?|million|lakhs?|billion)")
    m, i = d.find(ofs_rx, first)
    if m:
        cr = _amount_cr(m.group(2), m.group(3)) if m.group(2) != "[●]" else None
        if cr is not None:
            x.put("ofs_cr", round(cr, 2), i, _snippet(d.flat[i], m.start(), m.end()), "high", f"Stated as {m.group(2)} {m.group(3)}")
        if m.group(1) != "[●]":
            x.put("ofs_shares", to_num(m.group(1)), i, _snippet(d.flat[i], m.start(), m.end()), "medium")

    date_rx = r"([a-z]+\s+\d{1,2},?\s*\d{4}|\d{1,2}(?:st|nd|rd|th)?\s+[a-z]+,?\s*\d{4})"
    for field, word in (("open_date", "opens"), ("close_date", "closes")):
        m, i = d.find(r"(?:bid\s*/\s*offer|offer|issue|bid)\s+" + word + r"\s+on\s*:?\s*(?:[a-z]+day,?\s*)?" + date_rx, first)
        if m:
            dt = _parse_date(m.group(1))
            if dt:
                x.put(field, dt, i, _snippet(d.flat[i], m.start(), m.end()), "high")


def _parse_date(s: str) -> Optional[str]:
    s = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", s.replace(",", " "), flags=re.I)
    s = re.sub(r"\s+", " ", s).strip()
    for fmt in ("%B %d %Y", "%d %B %Y", "%b %d %Y", "%d %b %Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _shares_and_promoters(d: Doc, x: Extraction):
    pre_rx = [r"(?:pre-?\s?(?:offer|issue)|prior to the (?:offer|issue)|before the (?:offer|issue))[^.]{0,160}?(\d[\d,]{6,})\s*equity shares",
              r"(\d[\d,]{6,})\s*equity shares[^.]{0,160}?(?:pre-?\s?(?:offer|issue)|prior to the (?:offer|issue)|before the (?:offer|issue))"]
    for rx in pre_rx:
        m, i = d.find(rx)
        if m:
            v = to_num(m.group(1))
            if v and v >= 1e6:
                x.put("pre_issue_shares", v, i, _snippet(d.flat[i], m.start(), m.end()), "medium")
                break
    post_rx = [r"(?:post-?\s?(?:offer|issue)|after the (?:offer|issue))[^.]{0,160}?(\d[\d,]{6,})\s*equity shares"]
    for rx in post_rx:
        m, i = d.find(rx)
        if m:
            v = to_num(m.group(1))
            if v and v >= 1e6 and v >= (x.draft.get("pre_issue_shares") or 0):
                x.put("post_issue_shares", v, i, _snippet(d.flat[i], m.start(), m.end()), "medium")
                break
    pat = r"promoters?(?: and (?:the )?(?:members of (?:the )?)?promoter group)?[^%]{0,220}?(\d{1,3}(?:\.\d{1,2})?)\s*%[^%]{0,120}?"
    for field, when in (("promoter_pre_pct", "pre"), ("promoter_post_pct", "post")):
        for rx, conf in ((when + r"-?\s?(?:offer|issue) (?:promoter )?shareholding[^%]{0,140}?(\d{1,3}(?:\.\d{1,2})?)\s*%", "medium"),
                         (pat + when + r"-?\s?(?:offer|issue)", "low")):
            m, i = d.find(rx)
            if m:
                v = to_num(m.group(1))
                if v is not None and 0 < v <= 100 and not (field == "promoter_post_pct" and v == x.draft.get("promoter_pre_pct")):
                    x.put(field, v, i, _snippet(d.flat[i], m.start(), m.end()), conf)
                    break


# ---------------- financial table ----------------
FIN_LABELS = {
    "revenue_cr": r"revenue from operations",
    "ebitda_cr": r"ebitda(?!\s*margin)(?!\s*\(%)",
    "pat_cr": r"(?:restated\s+)?(?:net\s+)?profit\s*/?\s*(?:\(loss\)\s*)?(?:after tax|for the (?:year|period))(?!\s*margin)",
    "net_worth_cr": r"net\s*worth\b",
    "borrowings_cr": r"total borrowings",
    "cfo_cr": r"net cash (?:flows? )?(?:generated from|from|used in|generated from\s*/\s*\(used in\))\s*operating activities",
    "cash_cr": r"cash and cash equivalents",
    "capex_cr": r"purchase of property,?\s*plant and equipment",
}
PERIOD_RX = re.compile(
    r"(?P<stub>(?:three|six|nine|3|6|9)\s*months?(?:\s*period)?\s*ended[^0-9]{0,20}\d{1,2}?,?\s*\d{4})"
    r"|(?:fiscal|financial year|fy)\s*(?:20)?(?P<fy>\d{2})(?:\s*-\s*(?:20)?(?P<fy2>\d{2}))?\b"
    r"|march\s*31,?\s*(?P<m31>\d{4})|31(?:st)?\s*march,?\s*(?P<m31b>\d{4})", re.I)


def _unit_on_page(text: str) -> Optional[str]:
    m = re.search(r"(?:" + RUPEE + r"\s*in\s*|in\s*" + RUPEE + r"\s*|" + RUPEE + r"\s*)(crores?|million|lakhs?|billion)", text, re.I)
    return m.group(1).lower() if m else None


def _periods(header: str) -> list[tuple[str, Optional[int]]]:
    out = []
    for m in PERIOD_RX.finditer(header):
        if m.group("stub"):
            out.append(("stub", None))
        elif m.group("fy"):
            y2 = m.group("fy2")
            yr = int(y2) if y2 else int(m.group("fy"))
            out.append(("fy", 2000 + yr % 100))
        else:
            out.append(("fy", int(m.group("m31") or m.group("m31b"))))
    return out


def _financials(d: Doc, x: Extraction):
    scores = []
    for i, p in enumerate(d.pages):
        s = sum(1 for k in ("revenue_cr", "ebitda_cr", "pat_cr", "net_worth_cr", "borrowings_cr")
                if re.search(r"^\s*" + FIN_LABELS[k], p, re.M | re.I))
        if s >= 3:
            scores.append((s, -i, i))
    if not scores:
        x.warnings.append("Could not locate the restated financial summary table. Enter the financials manually.")
        return
    scores.sort(reverse=True)
    best = scores[0][2]
    text = d.pages[best]
    unit = _unit_on_page(text) or _doc_unit(d)
    factor = UNIT_TO_CR.get(unit or "", None)
    if factor is None:
        x.warnings.append("Could not tell whether the financial table is in ₹ crore, million or lakh; assumed million.")
        factor, unit = 0.1, "million (assumed)"
    lines = text.split("\n")
    # Header: the line with the most period tokens above the first label row
    first_label = next((n for n, ln in enumerate(lines) if re.match(r"^\s*" + FIN_LABELS["revenue_cr"], ln, re.I)), len(lines))
    header, periods = None, []
    for ln in lines[:first_label][::-1][:25]:
        ps = _periods(ln)
        if len(ps) > len(periods):
            header, periods = ln, ps
    confidence = "medium" if periods else "low"
    rows: dict[str, list[float]] = {}
    for key, lab in FIN_LABELS.items():
        for n, ln in enumerate(lines):
            m = re.match(r"^\s*" + lab + r"[^0-9(\-]*?(?:\(\d\)|\*+)?\s*(.*)$", ln, re.I)
            if not m or "%" in ln:
                continue
            nums = [to_num(t) for t in re.findall(NUM, m.group(1))]
            nums = [v for v in nums if v is not None]
            if nums:
                rows[key] = nums
                break
    if not rows:
        return
    ncols = max(len(v) for v in rows.values())
    region = " ".join(lines[max(0, first_label - 4):first_label]).lower()
    if periods and not any(k == "stub" for k, _ in periods) and ncols == len(periods) + 1 and "month" in region:
        # A part-year column whose header wrapped onto another line: it precedes the fiscal years.
        periods = [("stub", None)] + periods
    if periods and ncols != len(periods):
        confidence = "low"
        x.warnings.append(f"The financial table has {ncols} value columns but {len(periods)} period headings were "
                          "recognised; check that each year's figures are in the right column.")
    if not periods:
        # Assume latest-first fiscal years ending in the latest March found in the document
        yrs = [int(y) for y in re.findall(r"march\s*31,?\s*(\d{4})", " ".join(d.lower[:80]))]
        latest = max(yrs) if yrs else None
        periods = [("fy", latest - k if latest else None) for k in range(ncols)]
        x.warnings.append("Column periods were not identified in the financial table; assumed latest year first.")
    fy_cols = [(k, yr) for k, (kind, yr) in enumerate(periods) if kind == "fy"]
    fin: dict[int, dict[str, Any]] = {}
    for key, nums in rows.items():
        if key == "cash_cr":
            continue
        for col, yr in fy_cols:
            if col < len(nums) and yr:
                v = nums[col] * factor
                fin.setdefault(yr, {"fy": f"FY{yr}"})[key] = round(abs(v) if key == "capex_cr" else v, 2)
    if fin:
        years = sorted(fin)[-3:]
        table = [fin[y] for y in years]
        x.put("financials", table, best, header or "", confidence,
              f"Read from the table on page {best + 1}, units: {unit}. Stub (part-year) periods are ignored.")
    if "cash_cr" in rows and fy_cols:
        col = min(fy_cols, key=lambda c: -(c[1] or 0))[0]
        if col < len(rows["cash_cr"]):
            x.put("cash_cr", round(rows["cash_cr"][col] * factor, 2), best, "Cash and cash equivalents (latest fiscal year)", "low")


def _doc_unit(d: Doc) -> Optional[str]:
    counts: dict[str, int] = {}
    for p in d.pages[:150]:
        for m in re.finditer(r"(?:" + RUPEE + r"\s*in\s*|in\s*" + RUPEE + r"\s*)(crores?|million|lakhs?)", p, re.I):
            u = m.group(1).lower()
            counts[u] = counts.get(u, 0) + 1
    return max(counts, key=counts.get) if counts else None


# ---------------- objects, peers, risks, other ----------------
OBJECT_KINDS = [
    (r"repay|prepay", "Repayment/prepayment of borrowings"),
    (r"capital expenditure|capex|purchase of (?:plant|machinery|equipment)|setting up|set up", "Capital expenditure"),
    (r"working capital", "Working capital requirements"),
    (r"general corporate purposes", "General corporate purposes"),
    (r"acquisition|inorganic", "Acquisitions / inorganic growth"),
    (r"investment in (?:our )?(?:wholly[- ]owned )?subsidiar", "Investment in subsidiary"),
]


def _objects(d: Doc, x: Extraction):
    start = d.heading_page(r"objects of the (?:offer|issue)")
    if start is None:
        return
    items: dict[str, float] = {}
    page_used = start
    for i in range(start, min(start + 6, len(d.pages))):
        unit = _unit_on_page(d.pages[i]) or _doc_unit(d)
        f = UNIT_TO_CR.get(unit or "", None)
        if f is None:
            continue
        for ln in d.pages[i].split("\n"):
            low = ln.lower()
            if "%" in ln or "total" in low[:12]:
                continue
            nums = re.findall(NUM, ln)
            if not nums:
                continue
            for rx, label in OBJECT_KINDS:
                if label not in items and re.search(rx, low):
                    v = to_num(nums[-1])
                    if v and v > 0 and not (1990 < v < 2100):
                        items[label] = round(v * f, 2)
                        page_used = i
                    break
    if items:
        x.put("use_of_proceeds", [{"purpose": k, "amount_cr": v} for k, v in items.items()], page_used,
              "Objects of the Offer: utilisation of Net Proceeds", "medium")


def _peers(d: Doc, x: Extraction):
    m, i = d.find(r"comparison (?:of accounting ratios )?with (?:listed )?(?:industry )?peers|listed (?:industry )?peers")
    if m is None:
        return
    peers, names = [], []
    for j in range(i, min(i + 3, len(d.pages))):
        lines = d.pages[j].split("\n")
        hdr_idx = next((n for n, ln in enumerate(lines) if re.search(r"p\s*/\s*e", ln, re.I)), None)
        if hdr_idx is None:
            continue
        hdr = [c.strip().lower() for c in re.split(r"\s{2,}", lines[hdr_idx].strip()) if c.strip()]
        def col(rx):
            return next((k for k, c in enumerate(hdr) if re.search(rx, c)), None)
        c_pe, c_ronw, c_nav, c_price = col(r"p\s*/\s*e"), col(r"ronw|return on net ?worth"), col(r"nav|net asset value"), col(r"closing|market price|cmp")
        for ln in lines[hdr_idx + 1: hdr_idx + 25]:
            cells = [c.strip() for c in re.split(r"\s{2,}", ln.strip()) if c.strip()]
            if len(cells) < 3 or not re.search(r"[A-Za-z]{3}", cells[0]):
                continue
            name = cells[0]
            if re.search(r"\bcompany\b|our company|^peer|^listed|^name|^notes?|^source", name, re.I):
                continue
            if x.draft.get("company_name") and x.draft["company_name"].split()[0].lower() in name.lower():
                continue
            if len(cells) != len(hdr):
                # Header cells sometimes merge or wrap; numeric columns still line up from the right.
                shift = len(cells) - len(hdr)
                if shift <= 0 and len(cells) < 4:
                    continue
                remap = lambda c: None if c is None or c == 0 else c + shift  # noqa: E731
            else:
                remap = lambda c: c  # noqa: E731
            g = lambda c: (lambda k: to_num(cells[k]) if k is not None and 0 < k < len(cells) else None)(remap(c))  # noqa: E731
            pe = g(c_pe)
            if pe is None or pe <= 0:
                continue
            row = {"name": name, "pe": pe, "roe": g(c_ronw)}
            price, nav = g(c_price), g(c_nav)
            if price and nav and nav > 0:
                row["pb"] = round(price / nav, 2)
            peers.append(row)
            names.append(name)
        if peers:
            x.put("manual_peers", peers, j, lines[hdr_idx], "medium",
                  "From the RHP's peer table; multiples are as of the date in the document, not today.")
            x.draft["peer_names"] = names
            return


def _risks(d: Doc, x: Extraction):
    start = d.heading_page(r"risk factors")
    if start is None:
        return
    out, buf, page_used = [], None, start
    for i in range(start, min(start + 45, len(d.pages))):
        for ln in d.pages[i].split("\n"):
            s = ln.strip()
            m = re.match(r"^(\d{1,2})\.\s+(.+)$", s)
            if m and len(m.group(2)) > 30 and m.group(2)[0].isupper():
                if buf:
                    out.append(buf)
                buf = m.group(2)
                page_used = i
            elif buf is not None and s and not buf.endswith(".") and len(buf) < 320:
                buf += " " + s
            elif buf is not None and (not s or buf.endswith(".")):
                out.append(buf)
                buf = None
            if len(out) >= 12:
                break
        if len(out) >= 12:
            break
    if buf and len(out) < 12:
        out.append(buf)
    seen, clean = set(), []
    for r in out:
        r = re.sub(r"\s+", " ", r).strip()
        if re.search(r"\.{4,}\s*\d+$", r):
            continue
        key = r[:60].lower()
        if key not in seen:
            seen.add(key)
            clean.append(r[:300])
    if clean:
        x.put("risk_factors", clean, page_used, clean[0], "medium", "First risk-factor headings in the Risk Factors section")


def _misc(d: Doc, x: Extraction):
    m, i = d.find(r"(?:top|largest)\s*(?:ten|10|five|5|three|3)\s*customers[^%]{0,220}?(\d{1,3}(?:\.\d{1,2})?)\s*%")
    if m:
        v = to_num(m.group(1))
        if v is not None and 0 < v <= 100:
            x.put("top_customer_concentration_pct", v, i, _snippet(d.flat[i], m.start(), m.end()), "medium")
    m, i = d.find(r"contingent liabilities[^.]{0,260}?" + RUPEE + r"\s*(" + NUM + r")\s*(crores?|million|lakhs?|billion)")
    if m:
        cr = _amount_cr(m.group(1), m.group(2))
        if cr is not None and cr >= 0:
            x.put("contingent_liabilities_cr", round(cr, 2), i, _snippet(d.flat[i], m.start(), m.end()), "medium")
    lp = d.heading_page(r"summary of outstanding litigation(?:s)?(?: and material developments)?", min_chars=200)
    if lp is not None:
        p = d.pages[lp]
        k = p.lower().find("summary of outstanding litigation")
        txt = re.sub(r"\s+", " ", p[k: k + 700]).strip()
        x.put("litigation_notes", txt, lp, txt[:200], "low", "Opening text of the litigation summary; read the full section.")
    bp = d.heading_page(r"our business", min_chars=600)
    if bp is not None:
        paras = [re.sub(r"\s+", " ", para).strip() for para in re.split(r"\n\s*\n|\n(?=[A-Z])", d.pages[bp])]
        long = next((p for p in paras if len(p) > 200 and not p.lower().startswith("our business")), None)
        if long:
            x.put("business_summary", long[:700], bp, long[:200], "medium")


def parse_offer_document(pages: list[str]) -> dict[str, Any]:
    d = Doc(pages)
    x = Extraction()
    doc_type = _doc_type(d)
    _company_name(d, x)
    _issue(d, x)
    _shares_and_promoters(d, x)
    _financials(d, x)
    _objects(d, x)
    _peers(d, x)
    _risks(d, x)
    _misc(d, x)

    dr = x.draft
    hi = dr.get("price_band_high")
    # Derive amounts from share counts when the document gives shares but not rupee amounts
    for amt, sh in (("fresh_issue_cr", "fresh_issue_shares"), ("ofs_cr", "ofs_shares")):
        if amt not in dr and dr.get(sh) and hi:
            x.put(amt, round(dr[sh] * hi / 1e7, 2), x.evidence[sh]["page"] - 1, x.evidence[sh]["snippet"], "medium",
                  "Computed as shares offered × upper price band")
    if "pre_issue_shares" in dr and "post_issue_shares" not in dr and dr.get("fresh_issue_shares"):
        x.put("post_issue_shares", dr["pre_issue_shares"] + dr["fresh_issue_shares"], None,
              "pre-issue shares + fresh-issue shares", "medium", "Computed")

    required = ["company_name", "price_band_low", "price_band_high", "pre_issue_shares", "financials"]
    expected = required + ["fresh_issue_cr", "ofs_cr", "lot_size", "use_of_proceeds", "manual_peers", "risk_factors",
                           "promoter_pre_pct", "promoter_post_pct", "top_customer_concentration_pct",
                           "contingent_liabilities_cr", "open_date"]
    found = [f for f in expected if f in dr]
    if doc_type == "DRHP":
        x.warnings.insert(0, "This is a DRHP (draft): price band, dates and final issue size are usually not fixed yet "
                             "and figures can change in the RHP.")
    dr["source_note"] = f"Extracted automatically from {doc_type} upload; verify against the document."
    return {"draft": dr, "evidence": x.evidence, "doc_type": doc_type, "warnings": x.warnings,
            "found": found, "missing": [f for f in expected if f not in dr],
            "missing_required": [f for f in required if f not in dr],
            "coverage": len(found) / len(expected)}
