"""Deterministic scoring. The LLM never produces the final number.

score = sum(weight_i * points(level_i)), weights sum to exactly 100.
Computed with Decimal and stored as an integer in 1/10000 units (score_e4) so range filters
are exact and inclusive on every database.
"""
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, InvalidOperation

from app.llm.base import LEVELS

SCORING_LOGIC_VERSION = "weighted-levels-v1"

LEVEL_POINTS: dict[str, Decimal] = {
    "strong": Decimal("1"),
    "substantial": Decimal("0.75"),
    "partial": Decimal("0.5"),
    "limited": Decimal("0.25"),
    "none": Decimal("0"),
}
assert set(LEVEL_POINTS) == set(LEVELS)

E4 = Decimal(10000)


class RubricValidationError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def to_decimal(value) -> Decimal:
    try:
        return Decimal(str(value))
    except InvalidOperation:
        raise RubricValidationError([f"Invalid number: {value!r}"])


def weight_errors(weights: list) -> list[str]:
    errors: list[str] = []
    if not weights:
        return ["A rubric needs at least one criterion."]
    decs = [to_decimal(w) for w in weights]
    for i, d in enumerate(decs, start=1):
        if d <= 0 or d > 100:
            errors.append(f"Criterion {i}: weight must be greater than 0 and at most 100.")
        if d.as_tuple().exponent < -2:
            errors.append(f"Criterion {i}: weight may have at most 2 decimal places.")
    total = sum(decs)
    if total != Decimal(100):
        errors.append(f"Weights must total exactly 100% (currently {total}%).")
    return errors


def validate_weights(weights: list) -> None:
    errors = weight_errors(weights)
    if errors:
        raise RubricValidationError(errors)


def contribution(weight, level: str) -> Decimal:
    if level not in LEVEL_POINTS:
        raise ValueError(f"Unknown assessment level: {level!r}")
    return to_decimal(weight) * LEVEL_POINTS[level]


@dataclass
class ScoreBreakdown:
    total: Decimal
    contributions: list[Decimal]


def compute_score(items: list[tuple[float, str]]) -> ScoreBreakdown:
    """items: (weight, level) per criterion."""
    validate_weights([w for w, _ in items])
    contributions = [contribution(w, lvl) for w, lvl in items]
    total = sum(contributions, Decimal(0))
    assert Decimal(0) <= total <= Decimal(100)
    return ScoreBreakdown(total=total, contributions=contributions)


def to_e4(value: Decimal) -> int:
    return int((value * E4).to_integral_value())


def from_e4(value: int) -> float:
    return float(Decimal(value) / E4)


def range_bounds_e4(min_score, max_score) -> tuple[int, int]:
    """Inclusive bounds in e4 units. A bound with more precision than stored is tightened
    (min rounds up, max rounds down) so nothing outside the user's range is included."""
    lo = (to_decimal(min_score) * E4).to_integral_value(rounding=ROUND_CEILING)
    hi = (to_decimal(max_score) * E4).to_integral_value(rounding=ROUND_FLOOR)
    return int(lo), int(hi)


def required_status_for(level: str) -> str:
    if level in ("strong", "substantial"):
        return "supported"
    if level in ("partial", "limited"):
        return "needs_clarification"
    return "not_supported"


def summarize_required(statuses: list[str]) -> str:
    if not statuses:
        return "none_required"
    if "not_supported" in statuses:
        return "not_supported"
    if "needs_clarification" in statuses:
        return "needs_clarification"
    return "all_supported"
