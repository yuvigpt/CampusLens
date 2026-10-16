"""The deterministic five-factor scorer."""

import pytest

from app import scoring


def test_band_boundaries_are_exact():
    assert scoring.band_for_score(0) == "Low"
    assert scoring.band_for_score(29) == "Low"
    assert scoring.band_for_score(30) == "Medium"
    assert scoring.band_for_score(54) == "Medium"
    assert scoring.band_for_score(55) == "High"
    assert scoring.band_for_score(74) == "High"
    assert scoring.band_for_score(75) == "Critical"
    assert scoring.band_for_score(100) == "Critical"


def test_weight_tables_match_the_agreed_formula():
    assert scoring.URGENCY_POINTS == {"Low": 0, "Medium": 15, "High": 30}
    assert scoring.IMPACT_POINTS == {"Low": 0, "Medium": 12, "High": 25}
    assert scoring.SAFETY_POINTS == {"Low": 0, "Medium": 5, "High": 10}


def test_age_uses_completed_24_hour_periods():
    assert [scoring.age_points(d) for d in (0, 1, 2, 3, 29, 30, 31)] == [0, 1, 1, 2, 15, 15, 15]


def test_recurrence_tiers():
    assert [scoring.recurrence_points(n) for n in (0, 1, 2, 3, 5, 6, 50)] == [0, 7, 7, 13, 13, 20, 20]


def test_recurrence_not_applicable_scores_zero():
    assert scoring.recurrence_points(99, not_applicable=True) == 0


def test_safety_floor_floors_the_band_but_not_the_number():
    r = scoring.score_complaint(urgency="Low", impact="Low", safety="High",
                                age_days=0, recurrence_count=0)
    assert r.score == 10.0
    assert r.band_raw == "Low"
    assert r.band == "Medium"
    assert r.safety_floor_applied is True


def test_a_zero_score_is_real_not_unscored():
    r = scoring.score_complaint(urgency="Low", impact="Low", safety="Low",
                                age_days=0, recurrence_count=0)
    assert r.score == 0.0
    assert r.band == "Low"


def test_all_low_with_high_safety_floors():
    r = scoring.score_complaint(urgency="Low", impact="Low", safety="High",
                                age_days=0, recurrence_count=0)
    assert r.breakdown["safety_floor_applied"] is True


def test_maximum_is_one_hundred():
    r = scoring.score_complaint(urgency="High", impact="High", safety="High",
                                age_days=365, recurrence_count=99)
    assert r.score == 100.0
    assert r.band == "Critical"


def test_invalid_level_raises_and_returns_no_score():
    with pytest.raises(scoring.ScoringError):
        scoring.score_complaint(urgency="Severe", impact="Low", safety="Low",
                                age_days=0, recurrence_count=0)


def test_breakdown_is_nested_and_complete():
    r = scoring.score_complaint(urgency="High", impact="Medium", safety="Low",
                                age_days=7, recurrence_count=3)
    b = r.breakdown
    assert b["urgency"]["max"] == 30 and b["impact"]["max"] == 25
    assert b["recurrence"]["window_days"] == 90 and b["recurrence"]["max"] == 20
    assert b["age"]["max"] == 15 and b["age"]["rule"] == "completed 24-hour periods"
    assert b["safety"]["max"] == 10
    assert b["max_possible"] == 100
    assert b["version"] == "v1"
