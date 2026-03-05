/**
 * Scoring engine for Governor task reviews.
 *
 * Implements a base-plus-excellence scoring model with configurable
 * deductions. Wire-compatible with the Python ScoringRubric.
 *
 * @example
 * ```ts
 * import { ScoringRubric } from "@governor/core";
 *
 * const rubric = new ScoringRubric();
 * const result = rubric.score(
 *   { completion_gate: 20, core_execution: 18, code_quality: 22, documentation_quality: 18 },
 *   [{ type: "linter_errors", points: 5 }],
 *   10,
 * );
 * console.log(result.final_score); // 83
 * ```
 */

import defaultRubric from "./rubrics/default_rubric.json" with { type: "json" };

// ------------------------------------------------------------------
// Types
// ------------------------------------------------------------------

export interface RubricCategoryDef {
  max_points: number;
  description?: string;
}

export interface RubricDef {
  rubric_name?: string;
  version?: string;
  description?: string;
  base_score: number;
  excellence_max: number;
  evidence_gate?: number;
  categories: Record<string, RubricCategoryDef>;
  rating_thresholds?: Record<string, number>;
  deduction_types?: Record<string, { points: number; description?: string }>;
}

export interface Deduction {
  type: string;
  points: number;
}

export interface ScoreResult {
  base_score: number;
  category_total: number;
  categories: Record<string, number>;
  deductions: Deduction[];
  deduction_total: number;
  excellence: number;
  final_score: number;
  rating: string;
}

// ------------------------------------------------------------------
// ScoringRubric
// ------------------------------------------------------------------

export class ScoringRubric {
  private readonly _rubric: RubricDef;
  private readonly _categoryMaxPoints: Record<string, number>;

  constructor(rubric?: RubricDef) {
    this._rubric = rubric ?? (defaultRubric as RubricDef);
    this._categoryMaxPoints = {};
    for (const [name, defn] of Object.entries(this._rubric.categories)) {
      if (defn && typeof defn === "object" && "max_points" in defn) {
        this._categoryMaxPoints[name] = defn.max_points;
      }
    }
  }

  get baseScore(): number {
    return this._rubric.base_score ?? 85;
  }

  get excellenceMax(): number {
    return this._rubric.excellence_max ?? 15;
  }

  /**
   * Calculate a final score.
   *
   * @param categories - Category name to points awarded (0 to max).
   * @param deductions - List of deduction objects with type and points.
   * @param excellence - Points for excellence (0 to excellence_max).
   */
  score(
    categories: Record<string, number>,
    deductions: Deduction[] = [],
    excellence: number = 0,
  ): ScoreResult {
    this._validateCategories(categories);

    // Sum category scores, each capped at rubric-defined max points.
    let categoryTotal = 0;
    for (const [name, points] of Object.entries(categories)) {
      const maxPts = this._categoryMaxPoints[name];
      categoryTotal += Math.min(points, maxPts);
    }
    categoryTotal = Math.min(categoryTotal, this.baseScore);

    // Sum deductions -- clamp each to >= 0.
    const deductionTotal = deductions.reduce(
      (sum, d) => sum + Math.max(0, d.points ?? 0),
      0,
    );

    // Cap excellence and apply evidence gate.
    let cappedExcellence = Math.min(Math.floor(excellence), this.excellenceMax);
    const evidenceGate = this._rubric.evidence_gate ?? 80;
    if (categoryTotal < evidenceGate) {
      cappedExcellence = 0;
    }

    const rawScore = categoryTotal + cappedExcellence - deductionTotal;
    const finalScore = Math.max(0, Math.min(rawScore, this.baseScore + this.excellenceMax));

    return {
      base_score: this.baseScore,
      category_total: categoryTotal,
      categories,
      deductions,
      deduction_total: deductionTotal,
      excellence: cappedExcellence,
      final_score: finalScore,
      rating: this._rating(finalScore),
    };
  }

  private _validateCategories(categories: Record<string, number>): void {
    const configured = new Set(Object.keys(this._categoryMaxPoints));
    const provided = new Set(Object.keys(categories));

    const unknown = [...provided].filter((k) => !configured.has(k)).sort();
    if (unknown.length > 0) {
      throw new Error(
        `Unknown scoring categories: [${unknown.join(", ")}]. ` +
          `Allowed categories: [${[...configured].sort().join(", ")}]`,
      );
    }

    for (const [name, points] of Object.entries(categories)) {
      if (typeof points !== "number") {
        throw new Error(
          `Category '${name}' points must be numeric, got ${typeof points}`,
        );
      }
      if (points < 0) {
        throw new Error(`Category '${name}' points must be >= 0`);
      }
    }
  }

  private _rating(score: number): string {
    const thresholds = this._rubric.rating_thresholds ?? {};
    if (score >= (thresholds.EXCEPTIONAL ?? 95)) return "EXCEPTIONAL";
    if (score >= (thresholds.EXCELLENT ?? 85)) return "EXCELLENT";
    return "NEEDS_IMPROVEMENT";
  }
}
