"""Market registry. Adding a market = adding an entry here (plus a provider that covers it)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Market:
    code: str
    name: str
    currency: str
    exchanges: dict[str, str]  # provider exchange code -> display name
    suffixes: tuple[str, ...]  # Yahoo symbol suffixes for this market
    statutory_tax_rate: float  # used for NOPAT when the effective rate is unusable
    default_cost_of_equity: float  # % — starting DCF/DDM assumption, editable in the UI
    default_terminal_growth: float  # % nominal
    screener_region: str
    display_units: str  # "crore" | "million"
    preferred_exchange: str
    notes: tuple[str, ...] = field(default_factory=tuple)


MARKETS: dict[str, Market] = {
    "IN": Market(
        code="IN", name="India", currency="INR",
        exchanges={"NSI": "NSE", "BSE": "BSE"},
        suffixes=(".NS", ".BO"),
        # Base corporate rate under section 115BAA incl. surcharge & cess.
        statutory_tax_rate=25.17,
        # ~7% 10y G-Sec + ~5–6% equity risk premium. A starting point, not a fact.
        default_cost_of_equity=12.0,
        default_terminal_growth=5.0,
        screener_region="in",
        display_units="crore",
        preferred_exchange="NSE",
        notes=("Yahoo quotes for NSE/BSE are delayed, not real-time.",),
    ),
    "US": Market(
        code="US", name="United States", currency="USD",
        exchanges={"NMS": "NASDAQ", "NYQ": "NYSE", "NGM": "NASDAQ", "NCM": "NASDAQ", "ASE": "NYSE American"},
        suffixes=("",),
        statutory_tax_rate=21.0,
        default_cost_of_equity=9.0,
        default_terminal_growth=3.0,
        screener_region="us",
        display_units="million",
        preferred_exchange="NASDAQ",
    ),
}


def market_for_symbol(symbol: str) -> Market:
    s = symbol.upper()
    if s.endswith(".NS") or s.endswith(".BO"):
        return MARKETS["IN"]
    if "." not in s or s.startswith("DEMO"):
        # Plain tickers are treated as US; DEMO sample companies are modelled as Indian.
        return MARKETS["IN"] if s.startswith("DEMO") else MARKETS["US"]
    return MARKETS["US"]


def exchange_display(code: str | None) -> str | None:
    if not code:
        return None
    for m in MARKETS.values():
        if code in m.exchanges:
            return m.exchanges[code]
    return code


SUPPORTED_EXCHANGES = {code for m in MARKETS.values() for code in m.exchanges}
