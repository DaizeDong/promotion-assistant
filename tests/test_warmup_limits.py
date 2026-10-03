"""Generated synthetic warmup-limit regressions; see tools/make_fixtures.py."""
import math

import pytest

from scripts import deliverability


@pytest.mark.parametrize('age', [2000, 1000000, 1e100])
def test_old_mailbox_reaches_cap_without_exponent_overflow(age):
    assert deliverability.recommend_cap(100, inbox_rate=1.0, mailbox_age_days=age) == 100
    assert deliverability.recommend_cap(100, inbox_rate=0.4, mailbox_age_days=age) == 0


@pytest.mark.parametrize('age, expected', [(0, 10), (2.5, 10 * 2 ** 2.5),
                                         (2.999, 10 * 2 ** 2.999), (3, 80), (3.001, 80), (2000, 80)])
def test_warmup_respects_fractional_age_and_cap_boundary(age, expected):
    assert deliverability.warmup_ramp(age, start=10, daily_growth=2.0, steady=80) == pytest.approx(expected)


@pytest.mark.parametrize('growth', [1.0, 1.000001])
def test_slow_or_constant_growth_keeps_its_original_ceiling(growth):
    assert deliverability.warmup_ramp(2000, start=10, daily_growth=growth, steady=80) == pytest.approx(
        min(80, 10 * growth ** 2000))


def test_start_at_or_above_steady_is_already_capped():
    assert deliverability.warmup_ramp(2000, start=80, daily_growth=2.0, steady=80) == 80
    assert deliverability.warmup_ramp(2000, start=100, daily_growth=2.0, steady=80) == 80


def test_finite_result_can_survive_large_intermediate_growth():
    result = deliverability.warmup_ramp(2000, start=1e-300, daily_growth=2.0, steady=1e308)
    assert math.isfinite(result) and result == pytest.approx(math.ldexp(1e-300, 2000))


@pytest.mark.parametrize('growth', [0.0, 0.5, -1.0, float('nan'), float('inf')])
def test_warmup_rejects_invalid_growth(growth):
    with pytest.raises(ValueError):
        deliverability.warmup_ramp(2000, daily_growth=growth)


@pytest.mark.parametrize('field', ['age_days', 'start', 'steady'])
@pytest.mark.parametrize('value', [float('nan'), float('inf')])
def test_warmup_requires_finite_age_and_limits(field, value):
    kwargs = {'age_days': 2000, field: value}
    with pytest.raises(ValueError):
        deliverability.warmup_ramp(**kwargs)
