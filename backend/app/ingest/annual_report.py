"""Extract governance and bank asset-quality facts from an uploaded annual report (any format).

These facts are not available from free market-data sources. Each one is returned with page evidence and
a confidence level; nothing is saved until the user reviews and confirms it.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from .rhp import NUM, RUPEE, UNIT_TO_CR, Doc, _snippet, to_num

PCT = r"(\d{1,3}(?:\.\d{1,2})?)\s*%"


def _put(out: dict, ev: dict, field: str, value: Any, d: Doc, i: Optional[int], m, conf: str, note: str | None = None):
    if value is None:
        return
    out[field] = value
    ev[field] = {"page": None if i is None else i + 1, "snippet": _snippet(d.flat[i], m.start(), m.end()) if m and i is not None else "",
                 "confidence": conf, "note": note}


def _auditor_pages(d: Doc) -> range:
    idx = [i for i, p in enumerate(d.lower) if "independent auditor" in p and "opinion" in p]
    if not idx:
        return range(len(d.pages))
    return range(max(0, idx[0] - 1), min(len(d.pages), idx[0] + 12))


def parse_annual_report(pages: list[str]) -> dict[str, Any]:
    d = Doc(pages)
    facts: dict[str, Any] = {}
    ev: dict[str, Any] = {}
    warnings: list[str] = []

    # Fiscal year of the report
    m, i = d.find(r"for the (?:financial )?year ended\s+(?:on\s+)?(march\s*31,?\s*\d{4}|31(?:st)?\s*march,?\s*\d{4})", range(0, min(30, len(d.pages))))
    if m:
        yr = re.search(r"\d{4}", m.group(1)).group(0)
        _put(facts, ev, "as_of", f"FY{yr}", d, i, m, "high")

    # Auditor's opinion
    rng = _auditor_pages(d)
    m, i = d.find(r"basis for (?:qualified|adverse) opinion|disclaimer of opinion|we do not express an opinion|adverse opinion", rng)
    if m:
        _put(facts, ev, "auditor_qualification", True, d, i, m, "medium",
             "The auditor's report contains a modified opinion. Read the 'Basis for' paragraph.")
        facts["auditor_note"] = ev["auditor_qualification"]["snippet"][:300]
    else:
        m, i = d.find(r"basis for qualified opinion|qualified opinion", rng)
        if m and not re.search(r"not\s+(?:a\s+)?qualified", d.flat[i][max(0, m.start() - 40):m.end()], re.I):
            _put(facts, ev, "auditor_qualification", True, d, i, m, "medium", "Mentions a qualified opinion.")
            facts["auditor_note"] = ev["auditor_qualification"]["snippet"][:300]
        else:
            m, i = d.find(r"(?:in our opinion and to the best of our information[^.]{0,200}?true and fair view|unmodified opinion)", rng)
            if m:
                _put(facts, ev, "auditor_qualification", False, d, i, m, "medium", "Unmodified ('clean') audit opinion found.")
    m, i = d.find(r"emphasis of matter")
    if m:
        ev["emphasis_of_matter"] = {"page": i + 1, "snippet": _snippet(d.flat[i], m.start(), m.end(), 160),
                                    "confidence": "medium", "note": "An emphasis of matter is not a qualification, but flags an "
                                                                    "issue the auditor wants readers to notice."}
    m, i = d.find(r"(?:statutory\s+)?auditors?[^.]{0,120}?(?:resigned|resignation)")
    if m:
        _put(facts, ev, "auditor_resigned", True, d, i, m, "low", "Check whether this refers to the statutory auditor mid-term.")

    # Shareholding: promoter holding and pledge
    sh_pages = [k for k in range(len(d.pages)) if "shareholding pattern" in d.lower[k] or "distribution of shareholding" in d.lower[k]]
    for k in sh_pages:
        for ln in d.pages[k].split("\n"):
            if re.match(r"^\s*(?:total\s+)?(?:shareholding\s+of\s+)?promoters?(?:\s*(?:&|and)\s*promoter\s*group)?\b", ln, re.I):
                nums = [to_num(t) for t in re.findall(NUM, ln)]
                pcts = [v for v in nums if v is not None and 0 < v <= 100]
                if pcts:
                    facts["promoter_holding_pct"] = pcts[-1]
                    ev["promoter_holding_pct"] = {"page": k + 1, "snippet": ln.strip()[:200], "confidence": "low",
                                                  "note": "Last percentage on the promoter row of the shareholding table."}
                    break
        if "promoter_holding_pct" in facts:
            break
    m, i = d.find(r"(?:no|nil|none of the)\s+(?:equity\s+)?shares?[^.]{0,60}?(?:are|were|have been)?\s*pledged|pledged[^.]{0,40}?\bnil\b")
    if m:
        _put(facts, ev, "promoter_pledge_pct", 0.0, d, i, m, "medium", "Report states no promoter shares are pledged.")
    else:
        m, i = d.find(r"pledged[^.%]{0,160}?" + PCT)
        if m:
            v = to_num(m.group(1))
            if v is not None and v <= 100:
                _put(facts, ev, "promoter_pledge_pct", v, d, i, m, "low", "Check whether this % is of promoter holding or total shares.")

    # Contingent liabilities
    m, i = d.find(r"contingent liabilit(?:y|ies)[^.]{0,220}?" + RUPEE + r"?\s*(" + NUM + r")\s*(crores?|million|lakhs?|billion)")
    if m:
        v, factor = to_num(m.group(1)), UNIT_TO_CR.get(m.group(2).lower())
        if v is not None and factor:
            _put(facts, ev, "contingent_liabilities_cr", round(v * factor, 2), d, i, m, "low",
                 "First amount stated near 'contingent liabilities'; confirm against the notes to accounts.")

    # Related-party transactions: point to the disclosure; judgement stays with the user
    m, i = d.find(r"material related party transactions?|related party transactions?[^.]{0,80}(?:approval|omnibus|arm'?s length)")
    if m:
        ev["related_party"] = {"page": i + 1, "snippet": _snippet(d.flat[i], m.start(), m.end(), 160), "confidence": "low",
                               "note": "Related-party disclosure found. Read it and decide whether the amounts are a concern."}
    m, i = d.find(r"(?:material|significant|pending)\s+(?:litigations?|legal proceedings)")
    if m:
        ev["litigation"] = {"page": i + 1, "snippet": _snippet(d.flat[i], m.start(), m.end(), 160), "confidence": "low",
                            "note": "Litigation disclosure found; mark 'material litigation' only if it is significant."}

    # Banks / NBFCs
    bank_patterns = {
        "gnpa_pct": r"gross\s+(?:npas?|non[- ]performing\s+(?:assets?|advances|loans))(?:\s*\(\s*gnpa\s*\))?[^%]{0,90}?" + PCT,
        "nnpa_pct": r"net\s+(?:npas?|non[- ]performing\s+(?:assets?|advances|loans))(?:\s*\(\s*nnpa\s*\))?[^%]{0,90}?" + PCT,
        "car_pct": r"(?:capital (?:to risk[- ]weighted assets ratio|adequacy ratio)|\bcrar\b|\bcar\b)[^%]{0,90}?" + PCT,
        "pcr_pct": r"provision(?:ing)? coverage ratio(?:\s*\(\s*pcr\s*\))?[^%]{0,90}?" + PCT,
    }
    for field, rx in bank_patterns.items():
        m, i = d.find(rx)
        if m:
            v = to_num(m.group(1))
            if v is not None and 0 <= v <= 100:
                _put(facts, ev, field, v, d, i, m, "medium", "First figure stated in the report; make sure it is the year-end value.")
    if any(k in facts for k in bank_patterns):
        facts["bank_as_of"] = facts.get("as_of")

    found = [k for k in ("auditor_qualification", "promoter_holding_pct", "promoter_pledge_pct", "contingent_liabilities_cr",
                         "gnpa_pct", "nnpa_pct", "car_pct", "pcr_pct") if k in facts]
    if not found:
        warnings.append("No governance or asset-quality facts were recognised. Is this an annual report (or results document)?")
    return {"facts": facts, "evidence": ev, "found": found, "warnings": warnings,
            "note": "Extracted automatically by pattern matching. Review each fact against the page shown before saving."}
