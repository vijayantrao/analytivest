"""Pure, guarded financial formulas.

Every function returns a ``Calc``: either a numeric ``value`` or ``value=None`` with a
human-readable ``reason`` explaining why the result is not meaningful. Callers never
receive a silently-wrong number (e.g. growth off a negative base, or a ratio over
negative equity).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

Number = Optional[float]

# Treat absolute values below this as zero when dividing (statement values are in currency units).
_EPS = 1e-9


@dataclass(frozen=True)
class Calc:
    value: Number
    reason: Optional[str] = None  # set when value is None (or as a caveat when value exists)
    status: str = "ok"  # ok | missing | not_meaningful

    @property
    def ok(self) -> bool:
        return self.value is not None


def missing(what: str = "input") -> Calc:
    return Calc(None, f"{what} not available", "missing")


def nm(reason: str) -> Calc:
    return Calc(None, reason, "not_meaningful")


def is_num(x) -> bool:
    return x is not None and isinstance(x, (int, float)) and not math.isnan(x) and not math.isinf(x)


def ratio(num: Number, den: Number, *, name: str = "ratio", den_must_be_positive: bool = True,
          scale: float = 1.0) -> Calc:
    """num / den × scale with guards.

    ``den_must_be_positive``: ratios like D/E, ROE, P/E are not meaningful over a negative base.
    """
    if not is_num(num) or not is_num(den):
        return missing("numerator" if not is_num(num) else "denominator")
    if abs(den) < _EPS:
        return nm(f"{name}: denominator is zero")
    if den_must_be_positive and den < 0:
        return nm(f"{name}: denominator is negative, so the ratio is not meaningful")
    return Calc(num / den * scale)


def pct(num: Number, den: Number, *, name: str = "margin", den_must_be_positive: bool = True) -> Calc:
    return ratio(num, den, name=name, den_must_be_positive=den_must_be_positive, scale=100.0)


def growth(current: Number, previous: Number) -> Calc:
    """YoY growth % = (current / previous − 1) × 100.

    Undefined when the previous value is ≤ 0: growth from a loss or from zero has no
    sensible percentage interpretation.
    """
    if not is_num(current) or not is_num(previous):
        return missing("current or previous period value")
    if abs(previous) < _EPS:
        return nm("previous period value is zero")
    if previous < 0:
        return nm("previous period value is negative (e.g. a loss), so % growth is not meaningful")
    return Calc((current / previous - 1.0) * 100.0)


def cagr(begin: Number, end: Number, years: float) -> Calc:
    """CAGR % = ((end / begin) ^ (1 / years) − 1) × 100. Requires begin > 0 and end > 0."""
    if not is_num(begin) or not is_num(end):
        return missing("start or end value")
    if years is None or years <= 0:
        return nm("period length must be positive")
    if begin <= 0 or end <= 0:
        return nm("CAGR is undefined when the start or end value is zero or negative")
    return Calc(((end / begin) ** (1.0 / years) - 1.0) * 100.0)


def average(a: Number, b: Number) -> Calc:
    """Average of two balances. Falls back to the available one with a caveat."""
    if is_num(a) and is_num(b):
        return Calc((a + b) / 2.0)
    if is_num(a):
        return Calc(a, "prior-period balance missing; closing balance used instead of average")
    if is_num(b):
        return Calc(b, "closing balance missing; opening balance used instead of average")
    return missing("balance")


def interest_coverage(ebit: Number, interest: Number) -> Calc:
    """EBIT / interest expense. Interest ≈ 0 → coverage is effectively unlimited."""
    if not is_num(ebit):
        return missing("EBIT")
    if not is_num(interest) or abs(interest) < _EPS:
        return Calc(None, "no material interest expense reported", "not_meaningful")
    interest = abs(interest)
    return Calc(ebit / interest)


def net_debt(total_debt: Number, cash: Number) -> Calc:
    if not is_num(total_debt):
        return missing("total debt")
    if not is_num(cash):
        return missing("cash")
    return Calc(total_debt - cash)


def stdev(values: Sequence[float]) -> Number:
    v = [x for x in values if is_num(x)]
    if len(v) < 2:
        return None
    m = sum(v) / len(v)
    return math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))


def median(values: Sequence[float]) -> Number:
    v = sorted(x for x in values if is_num(x))
    if not v:
        return None
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0


def percentile(values: Sequence[float], q: float) -> Number:
    """Linear-interpolated percentile, q in [0, 100]."""
    v = sorted(x for x in values if is_num(x))
    if not v:
        return None
    if len(v) == 1:
        return v[0]
    k = (len(v) - 1) * q / 100.0
    lo, hi = math.floor(k), math.ceil(k)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def lerp_score(x: Number, points: Sequence[tuple[float, float]]) -> Number:
    """Piecewise-linear score: points = [(x0, s0), (x1, s1), ...] sorted by x. Clamped at the ends."""
    if not is_num(x):
        return None
    pts = sorted(points)
    if x <= pts[0][0]:
        return pts[0][1]
    if x >= pts[-1][0]:
        return pts[-1][1]
    for (x0, s0), (x1, s1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            if x1 == x0:
                return s1
            return s0 + (s1 - s0) * (x - x0) / (x1 - x0)
    return None
