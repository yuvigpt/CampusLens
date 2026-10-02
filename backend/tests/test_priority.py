"""
Unit tests for app/priority.py (Stage 2).

Run with the project venv, from anywhere:

    backend\\venv\\Scripts\\python.exe backend\\tests\\test_priority.py

or with unittest discovery from the project root:

    backend\\venv\\Scripts\\python.exe -m unittest discover -s backend\\tests -t backend -v

Covers: every level, every category weight, every band boundary, invalid input,
missing input, minimum and maximum scores, the score_breakdown shape, and a
compatibility check that the breakdown can be stored by app/database.py.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# Make "from app import ..." work regardless of the current working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import priority  # noqa: E402

# The lowest-scoring valid combination: Low + Low + Low + Minor = 22.
BASE = {
    "safety_risk": "Low",
    "functional_impact": "Low",
    "urgency": "Low",
    "category_weight": "Minor",
}
BASE_SCORE = 22.0


def score(**overrides):
    """Score using BASE with the given fields overridden."""
    kwargs = dict(BASE)
    kwargs.update(overrides)
    return priority.score_complaint(**kwargs)


class LevelWeightsTest(unittest.TestCase):
    """Every level of every field contributes the documented number of points."""

    def test_safety_risk_points(self):
        self.assertEqual(priority.SAFETY_RISK_POINTS, {"High": 40, "Medium": 22, "Low": 8})
        self.assertEqual(score(safety_risk="Low").score, 22.0)      # base
        self.assertEqual(score(safety_risk="Medium").score, 36.0)   # 22 - 8 + 22
        self.assertEqual(score(safety_risk="High").score, 54.0)     # 22 - 8 + 40

    def test_functional_impact_points(self):
        self.assertEqual(priority.FUNCTIONAL_IMPACT_POINTS, {"High": 25, "Medium": 15, "Low": 5})
        self.assertEqual(score(functional_impact="Low").score, 22.0)
        self.assertEqual(score(functional_impact="Medium").score, 32.0)
        self.assertEqual(score(functional_impact="High").score, 42.0)

    def test_urgency_points(self):
        self.assertEqual(priority.URGENCY_POINTS, {"High": 25, "Medium": 14, "Low": 6})
        self.assertEqual(score(urgency="Low").score, 22.0)
        self.assertEqual(score(urgency="Medium").score, 30.0)
        self.assertEqual(score(urgency="High").score, 41.0)

    def test_each_field_is_scored_independently(self):
        """Changing one field must not disturb the other three components."""
        result = score(safety_risk="High")
        self.assertEqual(result.breakdown["safety"], 40.0)
        self.assertEqual(result.breakdown["impact"], 5.0)
        self.assertEqual(result.breakdown["urgency"], 6.0)
        self.assertEqual(result.breakdown["category"], 3.0)

    def test_levels_are_normalized_but_not_guessed(self):
        """Case/whitespace are tolerated; unknown words are still rejected."""
        for variant in ("High", "high", "HIGH", "  High  ", "hIgH"):
            self.assertEqual(score(urgency=variant).score, 41.0, f"variant {variant!r}")

    def test_all_27_triples_are_accepted(self):
        """3 x 3 x 3 level combinations all produce a valid score."""
        seen = set()
        for safety in priority.ALLOWED_LEVELS:
            for impact in priority.ALLOWED_LEVELS:
                for urgency in priority.ALLOWED_LEVELS:
                    for category in priority.ALLOWED_CATEGORY_WEIGHTS:
                        result = priority.score_complaint(
                            safety_risk=safety,
                            functional_impact=impact,
                            urgency=urgency,
                            category_weight=category,
                        )
                        seen.add(result.score)
        # 81 combinations, and the achievable score set is 22..100
        self.assertIn(22.0, seen)
        self.assertIn(100.0, seen)
        for value in seen:
            self.assertGreaterEqual(value, priority.MIN_ACHIEVABLE_SCORE)
            self.assertLessEqual(value, priority.MAX_POSSIBLE_SCORE)


class CategoryWeightTest(unittest.TestCase):
    """Every category weight contributes the documented number of points."""

    def test_category_weight_points(self):
        self.assertEqual(
            priority.CATEGORY_WEIGHT_POINTS, {"Critical": 10, "Moderate": 6, "Minor": 3}
        )

    def test_minor(self):
        self.assertEqual(score(category_weight="Minor").score, 22.0)

    def test_moderate(self):
        self.assertEqual(score(category_weight="Moderate").score, 25.0)   # 22 - 3 + 6

    def test_critical(self):
        self.assertEqual(score(category_weight="Critical").score, 29.0)   # 22 - 3 + 10

    def test_category_weight_is_normalized(self):
        for variant in ("Critical", "critical", "CRITICAL", "  Critical "):
            self.assertEqual(score(category_weight=variant).score, 29.0, f"variant {variant!r}")


class BandBoundaryTest(unittest.TestCase):
    """Band thresholds are inclusive at the bottom of each band."""

    def test_band_for_score_at_every_boundary(self):
        cases = {
            0.0: "Low", 1.0: "Low", 24.0: "Low",          # Low:  0-24
            25.0: "Medium", 25.1: "Medium", 49.0: "Medium",  # Medium: 25-49
            50.0: "High", 74.0: "High", 74.9: "High",     # High: 50-74
            75.0: "Critical", 99.0: "Critical", 100.0: "Critical",  # Critical: 75-100
        }
        for value, expected in cases.items():
            with self.subTest(score=value):
                self.assertEqual(priority.band_for_score(value), expected)

    def test_reachable_scores_on_band_edges(self):
        """Real input combinations that land exactly on each boundary."""
        cases = [
            (dict(safety_risk="Low", functional_impact="Low", urgency="Low",
                  category_weight="Minor"), 22.0, "Low"),            # minimum achievable
            (dict(safety_risk="Low", functional_impact="Low", urgency="Low",
                  category_weight="Moderate"), 25.0, "Medium"),      # bottom of Medium
            (dict(safety_risk="Medium", functional_impact="Medium", urgency="Low",
                  category_weight="Moderate"), 49.0, "Medium"),      # top of Medium
            (dict(safety_risk="Low", functional_impact="High", urgency="Medium",
                  category_weight="Minor"), 50.0, "High"),           # bottom of High
            (dict(safety_risk="High", functional_impact="High", urgency="Low",
                  category_weight="Minor"), 74.0, "High"),           # top of High
            (dict(safety_risk="High", functional_impact="Medium", urgency="Medium",
                  category_weight="Moderate"), 75.0, "Critical"),    # bottom of Critical
            (dict(safety_risk="High", functional_impact="High", urgency="High",
                  category_weight="Critical"), 100.0, "Critical"),   # maximum
        ]
        for kwargs, expected_score, expected_band in cases:
            with self.subTest(**kwargs):
                result = priority.score_complaint(**kwargs)
                self.assertEqual(result.score, expected_score)
                self.assertEqual(result.band, expected_band)
                self.assertEqual(result.breakdown["band"], expected_band)

    def test_band_for_score_rejects_out_of_range(self):
        for bad in (-0.1, -1, 100.1, 101, 1000):
            with self.subTest(score=bad):
                with self.assertRaises(priority.PriorityValidationError):
                    priority.band_for_score(bad)

    def test_band_for_score_rejects_non_numeric(self):
        for bad in ("75", None, [75], True):
            with self.subTest(score=bad):
                with self.assertRaises(priority.PriorityValidationError):
                    priority.band_for_score(bad)

    def test_bands_are_ordered_and_complete(self):
        self.assertEqual(
            [band for _, band in priority.BAND_THRESHOLDS],
            ["Critical", "High", "Medium", "Low"],
        )


class MinimumMaximumTest(unittest.TestCase):
    """The extremes of the scoring system."""

    def test_maximum_score_is_100(self):
        result = score(safety_risk="High", functional_impact="High",
                       urgency="High", category_weight="Critical")
        self.assertEqual(result.score, 100.0)
        self.assertEqual(result.score, priority.MAX_POSSIBLE_SCORE)
        self.assertEqual(result.band, "Critical")
        self.assertEqual(
            result.breakdown["safety"] + result.breakdown["impact"]
            + result.breakdown["urgency"] + result.breakdown["category"],
            100.0,
        )

    def test_minimum_achievable_score_is_22(self):
        result = score()  # Low + Low + Low + Minor
        self.assertEqual(result.score, 22.0)
        self.assertEqual(result.score, priority.MIN_ACHIEVABLE_SCORE)
        self.assertEqual(result.band, "Low")

    def test_no_valid_combination_exceeds_the_maximum(self):
        highest = max(
            priority.score_complaint(
                safety_risk=s, functional_impact=i, urgency=u, category_weight=c
            ).score
            for s in priority.ALLOWED_LEVELS
            for i in priority.ALLOWED_LEVELS
            for u in priority.ALLOWED_LEVELS
            for c in priority.ALLOWED_CATEGORY_WEIGHTS
        )
        self.assertEqual(highest, 100.0)

    def test_clamp_score(self):
        self.assertEqual(priority.clamp_score(-10), 0.0)
        self.assertEqual(priority.clamp_score(0), 0.0)
        self.assertEqual(priority.clamp_score(50), 50.0)
        self.assertEqual(priority.clamp_score(100), 100.0)
        self.assertEqual(priority.clamp_score(150), 100.0)
        self.assertEqual(priority.clamp_score(1e9), 100.0)

    def test_clamp_score_rejects_non_numeric(self):
        for bad in ("50", None, [50], True):
            with self.subTest(value=bad):
                with self.assertRaises(priority.PriorityValidationError):
                    priority.clamp_score(bad)


class InvalidInputTest(unittest.TestCase):
    """Invalid values raise; they are never quietly turned into a Low score."""

    def test_unknown_level_words_are_rejected(self):
        for field in ("safety_risk", "functional_impact", "urgency"):
            for bad in ("Extreme", "Severe", "Very High", "None", "N/A", "Highh", "Lo"):
                with self.subTest(field=field, value=bad):
                    with self.assertRaises(priority.PriorityValidationError):
                        score(**{field: bad})

    def test_unknown_category_weight_is_rejected(self):
        for bad in ("Severe", "Trivial", "Critical!", "important", "Low"):
            with self.subTest(value=bad):
                with self.assertRaises(priority.PriorityValidationError):
                    score(category_weight=bad)

    def test_blank_strings_are_rejected(self):
        for field in ("safety_risk", "functional_impact", "urgency", "category_weight"):
            for bad in ("", "   ", "\t", "\n"):
                with self.subTest(field=field, value=repr(bad)):
                    with self.assertRaises(priority.PriorityValidationError):
                        score(**{field: bad})

    def test_wrong_types_are_rejected(self):
        for field in ("safety_risk", "functional_impact", "urgency", "category_weight"):
            for bad in (123, 1.5, True, False, ["High"], {"level": "High"}, ("High",)):
                with self.subTest(field=field, value=repr(bad)):
                    with self.assertRaises(priority.PriorityValidationError):
                        score(**{field: bad})

    def test_invalid_input_does_not_fall_back_to_low(self):
        """A missing level must NOT produce the same score as an explicit Low."""
        low_score = score(safety_risk="Low").score          # valid, = 22.0
        for bad in (None, "", "unknown"):
            with self.subTest(value=repr(bad)):
                with self.assertRaises(priority.PriorityValidationError):
                    score(safety_risk=bad)                  # must raise, not return 22.0
        self.assertEqual(low_score, 22.0)

    def test_validation_error_lists_every_problem_at_once(self):
        with self.assertRaises(priority.PriorityValidationError) as ctx:
            priority.score_complaint(
                safety_risk="Extreme",
                functional_impact=None,
                urgency="",
                category_weight="Nonsense",
            )
        message = str(ctx.exception)
        for expected in ("safety_risk", "functional_impact", "urgency", "category_weight"):
            self.assertIn(expected, message)
        # Four problems joined by '; ' -> exactly three separators.
        self.assertEqual(message.count("; "), 3)

    def test_priority_validation_error_is_a_value_error(self):
        """Subclassing ValueError keeps existing callers working."""
        self.assertTrue(issubclass(priority.PriorityValidationError, ValueError))
        with self.assertRaises(ValueError):
            score(urgency="Nope")

    def test_validate_inputs_returns_empty_list_when_valid(self):
        self.assertEqual(
            priority.validate_inputs(
                safety_risk="High", functional_impact="Medium",
                urgency="Low", category_weight="Moderate",
            ),
            [],
        )

    def test_validate_inputs_never_raises(self):
        problems = priority.validate_inputs(
            safety_risk=None, functional_impact=42,
            urgency="", category_weight="Bogus",
        )
        self.assertEqual(len(problems), 4)
        self.assertTrue(all(isinstance(p, str) and p for p in problems))


class MissingInputTest(unittest.TestCase):
    """Omitting an argument entirely is a TypeError, not a guessed score."""

    def test_omitting_each_argument_raises_type_error(self):
        for field in ("safety_risk", "functional_impact", "urgency", "category_weight"):
            with self.subTest(missing=field):
                kwargs = dict(BASE)
                del kwargs[field]
                with self.assertRaises(TypeError):
                    priority.score_complaint(**kwargs)

    def test_omitting_everything_raises_type_error(self):
        with self.assertRaises(TypeError):
            priority.score_complaint()

    def test_positional_arguments_are_not_accepted(self):
        """All four are keyword-only, so positional use fails loudly."""
        with self.assertRaises(TypeError):
            priority.score_complaint("High", "High", "High", "Critical")


class ScoreBreakdownShapeTest(unittest.TestCase):
    """The breakdown is flat, numeric, JSON-serializable and self-consistent."""

    REQUIRED_KEYS = {
        "safety", "impact", "urgency", "category",
        "total", "band", "max_possible", "inputs",
    }

    def test_breakdown_has_exactly_the_documented_keys(self):
        self.assertEqual(set(score().breakdown.keys()), self.REQUIRED_KEYS)

    def test_component_values_are_floats(self):
        breakdown = score().breakdown
        for key in ("safety", "impact", "urgency", "category", "total", "max_possible"):
            self.assertIsInstance(breakdown[key], float, f"{key} should be a float")

    def test_components_always_sum_to_total(self):
        for safety in priority.ALLOWED_LEVELS:
            for impact in priority.ALLOWED_LEVELS:
                for urgency in priority.ALLOWED_LEVELS:
                    for category in priority.ALLOWED_CATEGORY_WEIGHTS:
                        result = priority.score_complaint(
                            safety_risk=safety, functional_impact=impact,
                            urgency=urgency, category_weight=category,
                        )
                        breakdown = result.breakdown
                        self.assertEqual(
                            breakdown["safety"] + breakdown["impact"]
                            + breakdown["urgency"] + breakdown["category"],
                            breakdown["total"],
                            f"components do not sum to total for {safety}/{impact}/{urgency}/{category}",
                        )

    def test_total_matches_score_and_band(self):
        result = score(safety_risk="High")
        self.assertEqual(result.breakdown["total"], result.score)
        self.assertEqual(result.breakdown["band"], result.band)

    def test_max_possible_is_recorded(self):
        self.assertEqual(score().breakdown["max_possible"], 100.0)

    def test_inputs_echo_the_canonical_values(self):
        result = score(
            safety_risk="high", functional_impact="  MEDIUM  ",
            urgency="Low", category_weight="critical",
        )
        self.assertEqual(result.breakdown["inputs"], {
            "safety_risk": "High",
            "functional_impact": "Medium",
            "urgency": "Low",
            "category_weight": "Critical",
        })

    def test_inputs_are_a_dict_not_a_tuple(self):
        """database.py only accepts a dict of JSON-serializable values."""
        self.assertIsInstance(score().breakdown["inputs"], dict)

    def test_breakdown_is_json_serializable_and_round_trips(self):
        result = score(safety_risk="High", functional_impact="High",
                       urgency="High", category_weight="Critical")
        text = json.dumps(result.breakdown)
        self.assertEqual(json.loads(text), result.breakdown)
        self.assertIn('"total"', text)

    def test_to_dict_is_json_serializable(self):
        result = score()
        payload = result.to_dict()
        self.assertEqual(
            set(payload.keys()),
            {"priority_score", "priority_band", "score_breakdown"},
        )
        self.assertEqual(payload["priority_score"], result.score)
        self.assertEqual(payload["priority_band"], result.band)
        self.assertEqual(json.loads(json.dumps(payload))["score_breakdown"], result.breakdown)

    def test_result_is_immutable(self):
        result = score()
        with self.assertRaises(AttributeError):     # FrozenInstanceError subclasses it
            result.score = 999.0


class CategoryWeightLookupTest(unittest.TestCase):
    """The optional category -> category-weight helper."""

    def test_known_categories_map_to_the_expected_class(self):
        expected = {
            "Electrical": "Critical", "Safety": "Critical", "Fire Hazard": "Critical",
            "Plumbing": "Moderate", "Infrastructure": "Moderate", "WiFi/IT": "Moderate",
            "Cleanliness": "Minor", "Furniture": "Minor", "Other": "Minor",
        }
        for category, weight_class in expected.items():
            with self.subTest(category=category):
                self.assertEqual(priority.category_weight_class(category), weight_class)

    def test_lookup_is_case_and_space_insensitive(self):
        for variant in ("electrical", "ELECTRICAL", "  Electrical  "):
            with self.subTest(variant=variant):
                self.assertEqual(priority.category_weight_class(variant), "Critical")

    def test_unknown_category_returns_none_by_default(self):
        """This module never invents a weight; the caller decides."""
        for unknown in ("Mystery", "Alien Abduction", "", "   ", None, 42):
            with self.subTest(category=repr(unknown)):
                self.assertIsNone(priority.category_weight_class(unknown))

    def test_unknown_category_can_use_an_explicit_default(self):
        self.assertEqual(priority.category_weight_class("Mystery", default="Minor"), "Minor")
        self.assertEqual(priority.category_weight_class(None, default="moderate"), "Moderate")

    def test_invalid_default_is_rejected(self):
        with self.assertRaises(priority.PriorityValidationError):
            priority.category_weight_class("Mystery", default="Trivial")

    def test_custom_mapping_is_honoured(self):
        self.assertEqual(
            priority.category_weight_class("Roof Leak", mapping={"Roof Leak": "Critical"}),
            "Critical",
        )

    def test_every_mapped_class_is_a_valid_weight(self):
        for category, weight_class in priority.DEFAULT_CATEGORY_CLASSES.items():
            with self.subTest(category=category):
                self.assertIn(weight_class, priority.ALLOWED_CATEGORY_WEIGHTS)


class DatabaseCompatibilityTest(unittest.TestCase):
    """The scorer's output can be stored and read back by app/database.py.

    This is the only test that touches the database layer. It uses a temporary
    file, so the real backend/campuslens.db is never affected. The scorer
    itself imports neither sqlite3 nor the database module.
    """

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="campuslens_priority_test_"))
        self.db_path = self.tmp_dir / "temp_priority_test.db"
        from app import database          # local import keeps priority.py decoupled
        self.database = database
        database.init_db(db_path=self.db_path)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_priority_module_stays_independent(self):
        """priority.py must not import FastAPI, sqlite3, Gemini or the db layer."""
        import re
        source = Path(priority.__file__).read_text(encoding="utf-8")
        forbidden = re.search(
            r"^\s*(?:import|from)\s+(sqlite3|fastapi|google|database|app)\b",
            source,
            re.MULTILINE,
        )
        found = forbidden.group(0) if forbidden else None
        self.assertIsNone(forbidden, f"priority.py must not import: {found}")

    def test_breakdown_round_trips_through_the_database(self):
        result = priority.score_complaint(
            safety_risk="High", functional_impact="High",
            urgency="Low", category_weight="Minor",
        )
        self.assertEqual(result.score, 74.0)

        created = self.database.create_complaint(
            description="[TEMP TEST DATA] priority/database compatibility check",
            location="Test Location (temporary)",
            category="Electrical",
            safety_risk="High",
            functional_impact="High",
            urgency="Low",
            priority_score=result.score,
            score_breakdown=result.breakdown,
            db_path=self.db_path,
        )

        # Both the REAL priority_score column and the JSON blob.
        self.assertEqual(created["priority_score"], 74.0)
        self.assertEqual(created["score_breakdown"], result.breakdown)

        fetched = self.database.get_complaint(created["id"], db_path=self.db_path)
        self.assertEqual(fetched["score_breakdown"]["total"], 74.0)
        self.assertEqual(fetched["score_breakdown"]["band"], "High")
        self.assertEqual(fetched["score_breakdown"]["inputs"]["safety_risk"], "High")

    def test_priority_score_sorting_uses_the_scorer_output(self):
        """Two complaints scored by priority.py sort highest-first in the DB."""
        low = priority.score_complaint(
            safety_risk="Low", functional_impact="Low",
            urgency="Low", category_weight="Minor",
        )
        high = priority.score_complaint(
            safety_risk="High", functional_impact="High",
            urgency="High", category_weight="Critical",
        )
        self.assertLess(low.score, high.score)

        for index, result in ((1, low), (2, high)):
            self.database.create_complaint(
                description=f"[TEMP TEST DATA] sorting check {index}",
                location="Test Location (temporary)",
                priority_score=result.score,
                score_breakdown=result.breakdown,
                db_path=self.db_path,
            )

        rows = self.database.list_complaints(db_path=self.db_path)
        self.assertEqual([row["priority_score"] for row in rows], [100.0, 22.0])

    def test_real_database_is_untouched(self):
        """Every call above passed an explicit temp path."""
        self.assertNotEqual(self.db_path, self.database.DB_PATH)


if __name__ == "__main__":
    unittest.main(verbosity=2)