"""Focused tests for the submission-time deterministic estimate (BCIP-1144).

Covers the full 0-100 total and every priority band, the age helper
specification, structured recurrence when enabled, the safety floor, the
LOW(0) fallback for unknown levels, and determinism.
"""
from __future__ import annotations

import pytest

from app import scoring


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _estimate(**kwargs):
    return scoring.estimate_score_complaint(**kwargs)


# ---------------------------------------------------------------------------
# Bands - every band is reachable from Low inputs
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "urgency,impact,safety,age,recurrence,expected",
    [
        ("Low", "Low", "Low", 0, 0, "Low"),          # total 0
        ("Low", "Medium", "Low", 0, 0, "Low"),       # 12
        ("Low", "Low", "Medium", 0, 0, "Low"),       # 5
        ("Low", "Low", "Low", 29, 0, "Low"),         # 15 -> 15
        ("Low", "Low", "Low", 29, 0, "Low"),         # age_points(29) = 15
    ],
)
def test_band_low_and_medium(urgency, impact, safety, age, recurrence, expected):
    result = _estimate(urgency=urgency, impact=impact, safety=safety,
                       age_days=age, recurrence_count=recurrence)
    assert result.band == expected


def test_band_medium_54():
    # 12 (impact) + 15 (urgency) + 5 (safety) = 27 -> Low? no: 30-54 = Medium
    result = _estimate(urgency="Medium", impact="High", safety="High", age_days=0, recurrence_count=0)
    assert result.band == "Medium"  # 15 + 25 + 10 = 50


def test_band_high_55():
    result = _estimate(urgency="Medium", impact="High", safety="High", age_days=0,
                       recurrence_count=5, recurrence_not_applicable=False)
    assert result.band == "High"  # 15 + 25 + 10 + 13 = 63


def test_band_high_boundary():
    # 30 + 25 + 10 = 65 -> High
    result = _estimate(urgency="High", impact="High", safety="High", age_days=0, recurrence_count=0)
    assert result.band == "High"


def test_band_critical_75():
    # 30 + 25 + 10 + 7 (age 15) + 7 (recurrence 2) = 79 -> Critical
    result = _estimate(urgency="High", impact="High", safety="High",
                       age_days=30, recurrence_count=2)
    assert result.band == "Critical"


# ---------------------------------------------------------------------------
# Factor specifications
# ---------------------------------------------------------------------------

def test_urgency_points_0_15_30():
    assert _estimate(urgency="Low", impact="Low", safety="Low").urgency == 0
    assert _estimate(urgency="Medium", impact="Low", safety="Low").urgency == 15
    assert _estimate(urgency="High", impact="Low", safety="Low").urgency == 30


def test_impact_points_0_12_25():
    assert _estimate(urgency="Low", impact="Low", safety="Low").impact == 0
    assert _estimate(urgency="Low", impact="Medium", safety="Low").impact == 12
    assert _estimate(urgency="Low", impact="High", safety="Low").impact == 25


def test_safety_points_0_5_10():
    assert _estimate(urgency="Low", impact="Low", safety="Low").safety == 0
    assert _estimate(urgency="Low", impact="Low", safety="Medium").safety == 5
    assert _estimate(urgency="Low", impact="Low", safety="High").safety == 10


def test_age_max_15_floor_0():
    assert scoring.age_points(0) == 0
    assert scoring.age_points(1) == 1
    assert scoring.age_points(2) == 1
    assert scoring.age_points(3) == 2
    assert scoring.age_points(29) == 15
    assert scoring.age_points(30) == 15
    assert scoring.age_points(100) == 15


def test_recurrence_disabled_returns_zero():
    result = _estimate(urgency="High", impact="High", safety="High",
                       age_days=30, recurrence_count=50)
    assert result.recurrence == 0
    assert result.total == 80.0  # 30+25+10+15+0
    assert result.band == "Critical"


def test_recurrence_points_when_enabled():
    assert scoring.recurrence_points(0) == 0
    assert scoring.recurrence_points(1) == 7
    assert scoring.recurrence_points(2) == 7
    assert scoring.recurrence_points(3) == 13
    assert scoring.recurrence_points(5) == 13
    assert scoring.recurrence_points(6) == 20
    assert scoring.recurrence_points(50) == 20


def test_recurrence_not_applicable_short_circuits_to_zero():
    result = _estimate(urgency="High", impact="High", safety="High",
                       age_days=0, recurrence_count=50,
                       recurrence_not_applicable=True)
    assert result.recurrence == 0
    assert result.total == 65.0


# ---------------------------------------------------------------------------
# Error fallbacks and safety floor
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [None, "Severe", 12345, ""])
def test_unknown_levels_fallback_to_low(bad):
    result = _estimate(urgency=bad, impact="Medium", safety="Low")
    assert result.urgency == 0
    assert result.band == "Low"  # 0 + 12 + 0 = 12


def test_safety_floor_only_raises_band():
    # High safety + low raw total must display Medium, raw score untouched.
    result = _estimate(urgency="Low", impact="Low", safety="High",
                       age_days=0, recurrence_count=0)
    assert result.total == 10.0
    assert result.band == "Medium"


def test_deterministic_and_frozen():
    a = _estimate(urgency="Medium", impact="High", safety="Low", age_days=7,
                  recurrence_count=2, recurrence_not_applicable=False)
    b = _estimate(urgency="Medium", impact="High", safety="Low", age_days=7,
                  recurrence_count=2, recurrence_not_applicable=False)
    assert a == b
    assert a.to_dict()["total"] == 15 + 25 + 0 + 4 + 7
    assert isinstance(a.to_dict()["breakdown"], dict)
