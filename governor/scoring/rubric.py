"""Scoring engine for Governor task reviews.

Implements a base-plus-excellence scoring model with configurable deductions.
"""

import json
import os
from typing import Any, Dict, List, Optional


class ScoringRubric:
    """Configurable scoring rubric engine.

    The default scoring model:
    - Base score: 85
    - Excellence: up to +15 (value add, requires evidence)
    - Deductions: uncapped negative points

    Usage::

        rubric = ScoringRubric()
        score = rubric.score(task_data, review_data)
    """

    def __init__(self, rubric_path: Optional[str] = None) -> None:
        if rubric_path is None:
            rubric_path = os.path.join(
                os.path.dirname(__file__), "rubrics", "default_rubric.json"
            )
        try:
            with open(rubric_path, "r", encoding="utf-8") as f:
                self._rubric = json.load(f)
        except FileNotFoundError:
            raise ValueError(
                f"Scoring rubric file not found: {rubric_path}. "
                "Pass a valid path or use the default rubric."
            )
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Scoring rubric is not valid JSON ({rubric_path}): {exc}"
            ) from exc
        self._categories = self._rubric.get("categories", {})
        self._category_max_points = {
            name: int(defn.get("max_points", 0))
            for name, defn in self._categories.items()
            if isinstance(defn, dict)
        }

    @property
    def base_score(self) -> int:
        return self._rubric.get("base_score", 85)

    @property
    def excellence_max(self) -> int:
        return self._rubric.get("excellence_max", 15)

    def score(
        self,
        categories: Dict[str, int],
        deductions: Optional[List[Dict[str, Any]]] = None,
        excellence: int = 0,
    ) -> Dict[str, Any]:
        """Calculate a final score.

        Args:
            categories: Dict of category name -> points awarded (0 to max).
            deductions: List of dicts with 'type' and 'points' keys.
            excellence: Points for excellence (0 to excellence_max).

        Returns:
            Dict with: base_score, categories, deductions, excellence,
            final_score, rating.
        """
        deductions = deductions or []

        self._validate_categories(categories)

        # Sum category scores, each capped at rubric-defined max points.
        category_total = 0
        for category_name, points in categories.items():
            max_points = self._category_max_points[category_name]
            category_total += min(int(points), max_points)
        category_total = min(category_total, self.base_score)

        # Sum deductions — clamp each to >= 0 so negative values cannot
        # inject positive points into the final score.
        deduction_total = sum(max(0, d.get("points", 0)) for d in deductions)

        # Cap excellence and apply evidence gate
        excellence = min(int(excellence), self.excellence_max)
        evidence_gate = self._rubric.get("evidence_gate", 80)
        if category_total < evidence_gate:
            excellence = 0  # Gate: base must meet threshold for excellence

        final_score = category_total + excellence - deduction_total
        final_score = max(0, min(final_score, self.base_score + self.excellence_max))

        return {
            "base_score": self.base_score,
            "category_total": category_total,
            "categories": categories,
            "deductions": deductions,
            "deduction_total": deduction_total,
            "excellence": excellence,
            "final_score": final_score,
            "rating": self._rating(final_score),
        }

    def _validate_categories(self, categories: Dict[str, int]) -> None:
        configured = set(self._category_max_points.keys())
        provided = set(categories.keys())
        unknown = sorted(provided - configured)
        if unknown:
            raise ValueError(
                f"Unknown scoring categories: {unknown}. "
                f"Allowed categories: {sorted(configured)}"
            )

        for category_name, points in categories.items():
            if not isinstance(points, (int, float)):
                raise ValueError(
                    f"Category '{category_name}' points must be numeric, got {type(points).__name__}"
                )
            if points < 0:
                raise ValueError(f"Category '{category_name}' points must be >= 0")

    def _rating(self, score: int) -> str:
        thresholds = self._rubric.get("rating_thresholds", {})
        if score >= thresholds.get("EXCEPTIONAL", 95):
            return "EXCEPTIONAL"
        elif score >= thresholds.get("EXCELLENT", 85):
            return "EXCELLENT"
        else:
            return "NEEDS_IMPROVEMENT"
