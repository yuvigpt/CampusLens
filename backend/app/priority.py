"""
CampusLens - transparent priority scoring.

Pure Python. This module imports NOTHING from FastAPI, SQLite or Gemini, so it
can be unit-tested and reasoned about on its own.

Scoring system
--------------
    safety risk         High = 40   Medium = 22   Low = 8
    functional impact   High = 25   Medium = 15   Low = 5
    urgency             High = 25   Medium = 14   Low = 6
    category weight     Critical = 10   Moderate = 6   Minor = 3
    -----------------------------------------------------------------
    maximum            100          (40 + 25 + 25 + 10)
    minimum achievable  22          ( 8 +  5 +  6 +  3)  <- see note below

The final score is clamped to 0-100. With the tables above the raw sum can
never leave that range, so the clamp is defensive: it guarantees the contract
still holds if the weights are ever tuned.

Priority bands
--------------
    75-100 -> Critical
    50-74  -> High
    25-49  -> Medium
     0-24  -> Low

Note that band names (Critical/High/Medium/Low) and category-weight names
(Critical/Moderate/Minor) are two DIFFERENT vocabularies that happen to share
the word "Critical".

score_breakdown shape (compatible with app/database.py)
------------------------------------------------------
database.py stores score_breakdown as JSON text and only requires a dict of
JSON-serializable values (it calls json.dumps on it). We therefore emit a flat
dict of numbers plus two explainability keys:

    {
      "safety": 40.0, "impact": 25.0, "urgency": 6.0, "category": 3.0,
      "total": 74.0,                      # sum, clamped to 0-100
      "band": "High",                     # band for `total`
      "max_possible": 100.0,              # so the UI can render "74 / 100"
      "inputs": {                         # exactly what was scored
        "safety_risk": "High", "functional_impact": "High",
        "urgency": "Low", "category_weight": "Minor"
      }
    }

The first five keys match the shape already used and stored in Stage 1.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

# ---------------------------------------------------------------------------
# Weight tables (the single source of truth for the scoring system)
# ---------------------------------------------------------------------------
SAFETY_RISK_POINTS: Mapping[str, int] = {"High": 40, "Medium": 22, "Low": 8}
FUNCTIONAL_IMPACT_POINTS: Mapping[str, int] = {"High": 25, "Medium": 15, "Low": 5}
URGENCY_POINTS: Mapping[str, int] = {"High": 25, "Medium": 14, "Low": 6}
CATEGORY_WEIGHT_POINTS: Mapping[str, int] = {"Critical": 10, "Moderate": 6, "Minor": 3}

# The vocabulary accepted for the three levels.
ALLOWED_LEVELS: tuple[str, ...] = ("Low", "Medium", "High")
# The vocabulary accepted for category weight.
ALLOWED_CATEGORY_WEIGHTS: tuple[str, ...] = ("Critical", "Moderate", "Minor")

MAX_POSSIBLE_SCORE: float = 100.0
# 22 with today's tables: Low safety + Low impact + Low urgency + Minor category.
MIN_ACHIEVABLE_SCORE: float = float(
    min(SAFETY_RISK_POINTS.values())
    + min(FUNCTIONAL_IMPACT_POINTS.values())
    + min(URGENCY_POINTS.values())
    + min(CATEGORY_WEIGHT_POINTS.values())
)

# ---------------------------------------------------------------------------
# Priority bands
# ---------------------------------------------------------------------------
BAND_CRITICAL = "Critical"
BAND_HIGH = "High"
BAND_MEDIUM = "Medium"
BAND_LOW = "Low"

# Checked top-down: the first threshold the score reaches wins.
BAND_THRESHOLDS: tuple[tuple[float, str], ...] = (
    (75.0, BAND_CRITICAL),
    (50.0, BAND_HIGH),
    (25.0, BAND_MEDIUM),
    (0.0, BAND_LOW),
)

# Default mapping from a CampusLens complaint category to a category weight.
# This is a convenience for the API layer; override or extend it as needed.
DEFAULT_CATEGORY_CLASSES: Mapping[str, str] = {
    "Safety": "Critical",
    "Electrical": "Critical",
    "Fire Hazard": "Critical",
    "Infrastructure": "Moderate",
    "Plumbing": "Moderate",
    "WiFi/IT": "Moderate",
    "Furniture": "Minor",
    "Cleanliness": "Minor",
    "Other": "Minor",
}


class PriorityValidationError(ValueError):
    """Raised when a complaint cannot be scored because inputs are missing or invalid.

    Subclasses ValueError so callers that already catch ValueError keep working.
    """


@dataclass(frozen=True)
class PriorityResult:
    """The outcome of scoring one complaint."""

    score: float                       # 0-100
    band: str                          # Critical / High / Medium / Low
    breakdown: dict[str, Any]          # JSON-serializable; goes straight into score_breakdown

    def to_dict(self) -> dict[str, Any]:
        """Flat, JSON-serializable view for an API response."""
        return {
            "priority_score": self.score,
            "priority_band": self.band,
            "score_breakdown": self.breakdown,
        }


# ---------------------------------------------------------------------------
# Normalization helpers
#
# Levels are matched case-insensitively and whitespace is trimmed, mirroring
# database.py's _validate_level(). This is NORMALIZATION, not a fallback: an
# unrecognised value is always an error, never quietly treated as "Low".
# ---------------------------------------------------------------------------
def _canonical(value: str) -> str:
    """'  high ' -> 'High'; 'MODERATE' -> 'Moderate'."""
    return value.strip().title()


def _check_choice(value: Any, allowed: tuple[str, ...], field: str, problems: list[str]) -> None:
    """Append a precise problem description if `value` is missing or not in `allowed`."""
    if value is None:
        problems.append(f"'{field}' is required but was missing (None)")
        return
    if not isinstance(value, str):
        problems.append(f"'{field}' must be a string, got {type(value).__name__} ({value!r})")
        return
    if not value.strip():
        problems.append(f"'{field}' must not be blank")
        return
    if _canonical(value) not in allowed:
        problems.append(f"'{field}' must be one of {list(allowed)}, got {value!r}")


# ---------------------------------------------------------------------------
# Building blocks (each independently testable)
# ---------------------------------------------------------------------------
def clamp_score(value: Any) -> float:
    """Clamp any real number into the 0-100 range. Raises on non-numeric input."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PriorityValidationError(
            f"score must be a number, got {type(value).__name__} ({value!r})"
        )
    return max(0.0, min(MAX_POSSIBLE_SCORE, float(value)))


def band_for_score(score: Any) -> str:
    """Map a 0-100 score to its priority band.

    Boundaries: 75->Critical, 50->High, 25->Medium, 24->Low.
    """
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise PriorityValidationError(
            f"score must be a number, got {type(score).__name__} ({score!r})"
        )
    numeric = float(score)
    if not (0.0 <= numeric <= MAX_POSSIBLE_SCORE):
        raise PriorityValidationError(
            f"score must be between 0 and {MAX_POSSIBLE_SCORE:g}, got {numeric:g}"
        )
    for threshold, band in BAND_THRESHOLDS:
        if numeric >= threshold:
            return band
    raise AssertionError("unreachable: score was already range-checked")  # pragma: no cover


def category_weight_class(
    category: Any,
    *,
    default: Optional[str] = None,
    mapping: Optional[Mapping[str, str]] = None,
) -> Optional[str]:
    """Look up the category weight class for a complaint category.

    Returns None for an unknown category unless `default` is supplied, so the
    caller - not this module - decides what an unrecognised category means.
    """
    table = mapping if mapping is not None else DEFAULT_CATEGORY_CLASSES

    if isinstance(category, str) and category.strip():
        lookup = {key.strip().casefold(): value for key, value in table.items()}
        found = lookup.get(category.strip().casefold())
        if found is not None:
            return found

    if default is None:
        return None

    problems: list[str] = []
    _check_choice(default, ALLOWED_CATEGORY_WEIGHTS, "default", problems)
    if problems:
        raise PriorityValidationError("; ".join(problems))
    return _canonical(default)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_inputs(
    *,
    safety_risk: Any,
    functional_impact: Any,
    urgency: Any,
    category_weight: Any,
) -> list[str]:
    """Return a list of human-readable problems; empty list means 'valid'.

    Never raises, so an API layer can turn the result into a 422 response.
    """
    problems: list[str] = []
    _check_choice(safety_risk, ALLOWED_LEVELS, "safety_risk", problems)
    _check_choice(functional_impact, ALLOWED_LEVELS, "functional_impact", problems)
    _check_choice(urgency, ALLOWED_LEVELS, "urgency", problems)
    _check_choice(category_weight, ALLOWED_CATEGORY_WEIGHTS, "category_weight", problems)
    return problems


# ---------------------------------------------------------------------------
# The scorer
# ---------------------------------------------------------------------------
def score_complaint(
    *,
    safety_risk: Any,
    functional_impact: Any,
    urgency: Any,
    category_weight: Any,
) -> PriorityResult:
    """Score one complaint and explain the result.

    All four arguments are required keyword arguments. Values are matched
    case-insensitively and trimmed, then must resolve to a known level.

    Raises:
        PriorityValidationError: if anything is missing or invalid. The message
            lists every problem at once, and NO score is returned - a partial
            or guessed score is never produced.
    """
    problems = validate_inputs(
        safety_risk=safety_risk,
        functional_impact=functional_impact,
        urgency=urgency,
        category_weight=category_weight,
    )
    if problems:
        raise PriorityValidationError(
            "Cannot score complaint - " + "; ".join(problems)
        )

    # Safe to canonicalize now that everything has been validated.
    safety_label = _canonical(safety_risk)
    impact_label = _canonical(functional_impact)
    urgency_label = _canonical(urgency)
    category_label = _canonical(category_weight)

    safety_points = SAFETY_RISK_POINTS[safety_label]
    impact_points = FUNCTIONAL_IMPACT_POINTS[impact_label]
    urgency_points = URGENCY_POINTS[urgency_label]
    category_points = CATEGORY_WEIGHT_POINTS[category_label]

    raw_total = safety_points + impact_points + urgency_points + category_points
    total = clamp_score(raw_total)
    band = band_for_score(total)

    breakdown: dict[str, Any] = {
        "safety": float(safety_points),
        "impact": float(impact_points),
        "urgency": float(urgency_points),
        "category": float(category_points),
        "total": total,
        "band": band,
        "max_possible": MAX_POSSIBLE_SCORE,
        "inputs": {
            "safety_risk": safety_label,
            "functional_impact": impact_label,
            "urgency": urgency_label,
            "category_weight": category_label,
        },
    }

    return PriorityResult(score=total, band=band, breakdown=breakdown)


# ---------------------------------------------------------------------------
# Manual use: prints the full scoring table.
#   backend\venv\Scripts\python.exe backend\app\priority.py
# ---------------------------------------------------------------------------
def _main() -> int:
    print("CampusLens priority scoring table")
    print(f"maximum possible  : {MAX_POSSIBLE_SCORE:g}")
    print(f"minimum achievable: {MIN_ACHIEVABLE_SCORE:g}  (Low + Low + Low + Minor)")
    print()
    print(f"{'Safety':7} {'Impact':7} {'Urgency':8} {'Category':9} {'Score':6} Band")
    print("-" * 52)
    for safety in ALLOWED_LEVELS:
        for impact in ALLOWED_LEVELS:
            for urgency in ALLOWED_LEVELS:
                for category in ALLOWED_CATEGORY_WEIGHTS:
                    result = score_complaint(
                        safety_risk=safety,
                        functional_impact=impact,
                        urgency=urgency,
                        category_weight=category,
                    )
                    print(
                        f"{safety:7} {impact:7} {urgency:8} {category:9} "
                        f"{result.score:6.1f} {result.band}"
                    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())