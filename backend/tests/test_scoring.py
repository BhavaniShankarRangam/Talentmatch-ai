from decimal import Decimal

import pytest

from app.scoring import (
    RubricValidationError,
    compute_score,
    range_bounds_e4,
    required_status_for,
    summarize_required,
    to_e4,
    validate_weights,
)


def test_weighted_score_is_deterministic_sum_of_weight_times_level():
    items = [(30, "strong"), (25, "substantial"), (20, "partial"), (15, "limited"), (10, "none")]
    b = compute_score(items)
    # 30*1 + 25*.75 + 20*.5 + 15*.25 + 10*0
    assert b.total == Decimal("62.5")
    assert b.contributions == [Decimal("30"), Decimal("18.75"), Decimal("10.0"), Decimal("3.75"), Decimal("0")]
    assert compute_score(items).total == b.total


def test_all_strong_is_exactly_100_and_all_none_is_0():
    assert compute_score([(60, "strong"), (40, "strong")]).total == 100
    assert compute_score([(60, "none"), (40, "none")]).total == 0


def test_fractional_weights_are_exact():
    b = compute_score([(33.33, "strong"), (33.33, "strong"), (33.34, "substantial")])
    assert b.total == Decimal("91.665")
    assert to_e4(b.total) == 916650


@pytest.mark.parametrize("weights", [[50, 40], [50, 60], [100, 0], [-10, 110], [33.333, 66.667], []])
def test_invalid_weights_rejected(weights):
    with pytest.raises(RubricValidationError):
        validate_weights(weights)


def test_unknown_level_rejected():
    with pytest.raises(ValueError):
        compute_score([(100, "excellent")])


def test_inclusive_bounds_conversion():
    assert range_bounds_e4(98, 100) == (980000, 1000000)
    # More precision than stored: never widen the user's range
    assert range_bounds_e4("97.99995", "99.99995") == (980000, 999999)


def test_required_status_mapping():
    assert required_status_for("strong") == "supported"
    assert required_status_for("substantial") == "supported"
    assert required_status_for("partial") == "needs_clarification"
    assert required_status_for("limited") == "needs_clarification"
    assert required_status_for("none") == "not_supported"
    assert summarize_required([]) == "none_required"
    assert summarize_required(["supported", "needs_clarification"]) == "needs_clarification"
    assert summarize_required(["supported", "not_supported", "needs_clarification"]) == "not_supported"
