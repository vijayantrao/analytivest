"""Portfolio holdings import (broker CSV/XLSX exports) and symbol resolution.

Supported out of the box: Zerodha Console holdings (Instrument / Qty. / Avg. cost), Groww (Stock Name /
Quantity / Average buy price), and any file with recognisable symbol/name, quantity and average-price
columns. Detection is by header text, not column position.
"""
from __future__ import annotations

import csv
import io
import re
from typing import Any, Optional

from .ingest.extract import check_archive

SYMBOL_COLS = ("instrument", "symbol", "tradingsymbol", "trading symbol", "scrip", "scrip code", "ticker", "nse symbol")
NAME_COLS = ("stock name", "company name", "company", "name", "security name", "stock", "scrip name")
QTY_COLS = ("qty", "qty.", "quantity", "quantity available", "shares", "holding qty", "net qty", "units", "total quantity")
AVG_COLS = ("avg. cost", "avg cost", "average cost", "average price", "avg. price", "avg price", "average buy price",
            "buy avg", "buy average", "avg. buy price", "average cost price", "buy price")


class HoldingsError(Exception):
    pass


def _norm(h: Any) -> str:
    return re.sub(r"\s+", " ", str(h or "").strip().lower())


def _num(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[₹,\s]", "", str(v))
    try:
        return float(s)
    except ValueError:
        return None


def _rows(data: bytes, filename: str) -> list[list[Any]]:
    if data[:4] == b"PK\x03\x04":
        import openpyxl
        try:
            check_archive(data)
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as e:
            raise HoldingsError(f"Could not read the Excel file: {e}") from e
        best: list[list[Any]] = []
        for ws in wb.worksheets:  # brokers sometimes put holdings on a named sheet
            rows = [list(r) for r in ws.iter_rows(values_only=True)]
            if len(rows) > len(best) and _header_index(rows) is not None:
                best = rows
        if not best:
            raise HoldingsError("No sheet with symbol/name and quantity columns was found.")
        return best
    text = None
    for enc in ("utf-8-sig", "cp1252"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise HoldingsError("Unsupported file: upload the broker's holdings export as CSV or Excel.")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return [r for r in csv.reader(io.StringIO(text), dialect)]


def _find(header: list[str], names: tuple[str, ...]) -> Optional[int]:
    for n in names:
        if n in header:
            return header.index(n)
    for k, h in enumerate(header):  # looser: header contains the name
        if any(n in h for n in names if len(n) > 3):
            return k
    return None


def _header_index(rows: list[list[Any]]) -> Optional[int]:
    for k, r in enumerate(rows[:40]):
        h = [_norm(c) for c in r]
        if (_find(h, SYMBOL_COLS) is not None or _find(h, NAME_COLS) is not None) and _find(h, QTY_COLS) is not None:
            return k
    return None


def parse_holdings(data: bytes, filename: str = "holdings.csv") -> dict[str, Any]:
    rows = _rows(data, filename)
    hi = _header_index(rows)
    if hi is None:
        raise HoldingsError("Could not find the header row. The file needs a symbol or stock-name column and a "
                            "quantity column (e.g. Zerodha's 'Instrument' and 'Qty.').")
    header = [_norm(c) for c in rows[hi]]
    c_sym, c_name = _find(header, SYMBOL_COLS), _find(header, NAME_COLS)
    c_qty, c_avg = _find(header, QTY_COLS), _find(header, AVG_COLS)
    c_isin = _find(header, ("isin",))
    items, skipped = [], []
    for r in rows[hi + 1:]:
        if not r or all(c in (None, "") for c in r):
            continue
        get = lambda c: r[c] if c is not None and c < len(r) else None  # noqa: E731
        sym, name, qty = get(c_sym), get(c_name), _num(get(c_qty))
        label = str(sym or name or "").strip()
        if not label or label.lower() in ("total", "grand total") or qty is None:
            continue
        if qty <= 0:
            skipped.append(f"{label}: zero quantity")
            continue
        items.append({"raw": label, "symbol_hint": str(sym).strip() if sym else None, "name": str(name).strip() if name else None,
                      "isin": str(get(c_isin)).strip() if get(c_isin) else None, "quantity": qty,
                      "avg_cost": _num(get(c_avg))})
    if not items:
        raise HoldingsError("No holdings rows with a positive quantity were found.")
    return {"items": items, "skipped": skipped, "columns": {"symbol": c_sym, "name": c_name, "quantity": c_qty,
                                                           "avg_cost": c_avg}}


TICKER_RE = re.compile(r"^[A-Z0-9&\-]{1,20}$")


def resolve_symbol(item: dict[str, Any], search) -> tuple[Optional[str], Optional[str]]:
    """Return (yahoo_symbol, note). `search(q)` is the app's search function (grouped results)."""
    hint = (item.get("symbol_hint") or "").upper().strip()
    if hint.endswith((".NS", ".BO")) or hint.startswith("DEMO-"):
        return hint, None
    if hint and TICKER_RE.match(hint):
        base = re.sub(r"-(EQ|BE|BZ|SM|ST)$", "", hint)  # strip NSE series suffixes
        return f"{base}.NS", None
    q = item.get("name") or item.get("raw")
    if not q:
        return None, "no symbol or name"
    try:
        res = search(q).get("results", [])
    except Exception as e:  # offline / provider down
        return None, f"lookup failed: {e}"
    india = [g for g in res if g.get("market") == "IN" and not g.get("is_sample")]
    if not india:
        return None, "no NSE/BSE match found"
    return india[0]["primary_symbol"], (f"matched by name to {india[0]['name']}" if len(india) == 1 else
                                        f"best of {len(india)} name matches: {india[0]['name']}")
