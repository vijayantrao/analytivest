import math

import pytest

from app.engine import formulas as F


def test_growth_basic():
    assert F.growth(110, 100).value == pytest.approx(10.0)
    assert F.growth(90, 100).value == pytest.approx(-10.0)


def test_growth_negative_or_zero_base_is_not_meaningful():
    r = F.growth(50, -20)
    assert r.value is None and r.status == "not_meaningful"
    assert F.growth(50, 0).status == "not_meaningful"


def test_growth_missing():
    assert F.growth(None, 100).status == "missing"
    assert F.growth(float("nan"), 100).status == "missing"


def test_cagr_known_example():
    # 100 -> 200 in 5 years: 2^(1/5) - 1 = 14.8698%
    assert F.cagr(100, 200, 5).value == pytest.approx(14.8698355, rel=1e-6)
    # Declining: 200 -> 100 over 2 years = sqrt(0.5) - 1 = -29.29%
    assert F.cagr(200, 100, 2).value == pytest.approx((math.sqrt(0.5) - 1) * 100)


@pytest.mark.parametrize("b,e", [(-10, 20), (10, -5), (0, 10), (10, 0)])
def test_cagr_undefined_for_non_positive_endpoints(b, e):
    r = F.cagr(b, e, 3)
    assert r.value is None and r.status == "not_meaningful"


def test_ratio_guards():
    assert F.ratio(50, 100).value == 0.5
    assert F.ratio(50, 0).status == "not_meaningful"
    assert F.ratio(50, -100).status == "not_meaningful"  # e.g. D/E over negative equity
    assert F.ratio(50, -100, den_must_be_positive=False).value == -0.5


def test_margins_and_roe():
    assert F.pct(15, 100).value == pytest.approx(15.0)
    avg = F.average(900, 1100)
    assert avg.value == 1000
    assert F.pct(150, avg.value).value == pytest.approx(15.0)  # ROE on average equity


def test_average_fallback_has_caveat():
    r = F.average(1000, None)
    assert r.value == 1000 and "closing balance" in r.reason


def test_interest_coverage():
    assert F.interest_coverage(500, 100).value == 5
    assert F.interest_coverage(500, -100).value == 5  # sign convention independent
    r = F.interest_coverage(500, 0)
    assert r.value is None and "no material interest" in r.reason


def test_net_debt_and_de():
    assert F.net_debt(300, 500).value == -200  # net cash
    assert F.ratio(300, 1000).value == pytest.approx(0.3)


def test_percentile_median_lerp():
    assert F.median([1, 3, 2]) == 2
    assert F.median([1, 2, 3, 4]) == 2.5
    assert F.percentile([0, 10], 25) == 2.5
    pts = [(0, 0), (10, 100)]
    assert F.lerp_score(5, pts) == 50
    assert F.lerp_score(-5, pts) == 0 and F.lerp_score(50, pts) == 100
    assert F.lerp_score(None, pts) is None
