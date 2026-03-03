"""Tests for the ScoringRubric engine."""

from governor.scoring.rubric import ScoringRubric


class TestScoringRubric:

    def setup_method(self):
        self.rubric = ScoringRubric()
        self.valid_categories = {
            "completion_gate": 20,
            "core_execution": 20,
            "code_quality": 25,
            "documentation_quality": 20,
        }

    def test_default_base_score(self):
        assert self.rubric.base_score == 85

    def test_default_excellence_max(self):
        assert self.rubric.excellence_max == 15

    def test_perfect_score(self):
        result = self.rubric.score(self.valid_categories, excellence=15)
        assert result["final_score"] == 100
        assert result["rating"] == "EXCEPTIONAL"

    def test_category_total_capped_at_base(self):
        categories = {
            "completion_gate": 999,
            "core_execution": 999,
            "code_quality": 999,
            "documentation_quality": 999,
        }
        result = self.rubric.score(categories)
        assert result["category_total"] == 85

    def test_excellence_capped_at_max(self):
        categories = self.valid_categories
        result = self.rubric.score(categories, excellence=50)
        assert result["excellence"] == 15  # Capped at excellence_max

    def test_evidence_gate_blocks_excellence(self):
        categories = {
            "completion_gate": 20,
            "core_execution": 20,
            "code_quality": 20,
            "documentation_quality": 10,  # 70 total
        }
        result = self.rubric.score(categories, excellence=10)
        assert result["excellence"] == 0
        assert result["final_score"] == 70

    def test_evidence_gate_allows_excellence(self):
        categories = self.valid_categories
        result = self.rubric.score(categories, excellence=10)
        assert result["excellence"] == 10
        assert result["final_score"] == 95

    def test_deductions_reduce_score(self):
        categories = self.valid_categories
        deductions = [{"type": "generic_evidence", "points": 10}]
        result = self.rubric.score(categories, deductions=deductions)
        assert result["deduction_total"] == 10
        assert result["final_score"] == 75

    def test_score_cannot_go_below_zero(self):
        categories = {"completion_gate": 20}
        deductions = [{"type": "major_issue", "points": 100}]
        result = self.rubric.score(categories, deductions=deductions)
        assert result["final_score"] == 0

    def test_score_cannot_exceed_max(self):
        categories = self.valid_categories
        result = self.rubric.score(categories, excellence=15)
        assert result["final_score"] <= 100

    def test_rating_exceptional(self):
        categories = self.valid_categories
        result = self.rubric.score(categories, excellence=15)
        assert result["rating"] == "EXCEPTIONAL"

    def test_rating_excellent(self):
        categories = self.valid_categories
        result = self.rubric.score(categories, excellence=5)
        assert result["rating"] == "EXCELLENT"

    def test_rating_needs_improvement(self):
        categories = {"completion_gate": 60}
        result = self.rubric.score(categories)
        assert result["rating"] == "NEEDS_IMPROVEMENT"

    def test_empty_deductions(self):
        categories = self.valid_categories
        result = self.rubric.score(categories)
        assert result["deductions"] == []
        assert result["deduction_total"] == 0

    def test_result_contains_all_keys(self):
        result = self.rubric.score({"completion_gate": 20, "core_execution": 20, "code_quality": 10})
        expected_keys = {"base_score", "category_total", "categories", "deductions",
                         "deduction_total", "excellence", "final_score", "rating"}
        assert set(result.keys()) == expected_keys

    def test_unknown_category_raises(self):
        try:
            self.rubric.score({"A": 10})
            assert False, "Expected ValueError for unknown category"
        except ValueError as e:
            assert "Unknown scoring categories" in str(e)

    def test_negative_points_raise(self):
        try:
            self.rubric.score({"completion_gate": -1})
            assert False, "Expected ValueError for negative points"
        except ValueError as e:
            assert "must be >= 0" in str(e)
