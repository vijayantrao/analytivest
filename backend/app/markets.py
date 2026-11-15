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
    cost_of_equity_basis: str = ""  # where the default cost of equity comes from (shown beside the DCF)


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
        cost_of_equity_basis="Indian 10-year government bond yield (~7%) + equity risk premium (~5%)",
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
        cost_of_equity_basis="US 10-year Treasury yield (~4%) + equity risk premium (~5%)",
    ),
}

CURRENCY_SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥"}


def money(value: float, currency: str | None, decimals: int = 2) -> str:
    """A per-share or price amount in its own currency: ₹1,234.50, $356.27, or 'CHF 12.00'."""
    cur = (currency or "INR").upper()
    sym = CURRENCY_SYMBOLS.get(cur)
    return f"{sym}{value:,.{decimals}f}" if sym else f"{cur} {value:,.{decimals}f}"


def large_amount(value: float, currency: str | None) -> str:
    """A statement-sized amount in the units readers of that market expect: ₹ crore, else million/billion."""
    cur = (currency or "INR").upper()
    if cur == "INR":
        return f"₹{value / 1e7:,.0f} Cr"
    sym = CURRENCY_SYMBOLS.get(cur, cur + " ")
    return f"{sym}{value / 1e9:,.1f} billion" if abs(value) >= 1e9 else f"{sym}{value / 1e6:,.0f} million"


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
