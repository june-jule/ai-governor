import { describe, it, expect } from "vitest";
import { ScoringRubric } from "../src/scoring/rubric.js";
import type { RubricDef } from "../src/scoring/rubric.js";

describe("ScoringRubric", () => {
  it("uses default rubric when none provided", () => {
    const rubric = new ScoringRubric();
    expect(rubric.baseScore).toBe(85);
    expect(rubric.excellenceMax).toBe(15);
  });

  it("accepts a custom rubric", () => {
    const custom: RubricDef = {
      base_score: 100,
      excellence_max: 10,
      categories: { only_cat: { max_points: 100 } },
    };
    const rubric = new ScoringRubric(custom);
    expect(rubric.baseScore).toBe(100);
    expect(rubric.excellenceMax).toBe(10);
  });

  it("scores a perfect run as EXCEPTIONAL", () => {
    const rubric = new ScoringRubric();
    const result = rubric.score(
      { completion_gate: 20, core_execution: 20, code_quality: 25, documentation_quality: 20 },
      [],
      15,
    );
    expect(result.final_score).toBe(100);
    expect(result.rating).toBe("EXCEPTIONAL");
  });

  it("caps category scores at rubric-defined max", () => {
    const rubric = new ScoringRubric();
    const result = rubric.score(
      { completion_gate: 999, core_execution: 20, code_quality: 25, documentation_quality: 20 },
      [],
      0,
    );
    // completion_gate capped at 20
    expect(result.category_total).toBe(85);
  });

  it("applies deductions", () => {
    const rubric = new ScoringRubric();
    const result = rubric.score(
      { completion_gate: 20, core_execution: 20, code_quality: 25, documentation_quality: 20 },
      [{ type: "linter_errors", points: 5 }],
      0,
    );
    expect(result.deduction_total).toBe(5);
    expect(result.final_score).toBe(80);
  });

  it("gates excellence below evidence threshold", () => {
    const rubric = new ScoringRubric();
    // Total = 60, below evidence_gate of 80
    const result = rubric.score(
      { completion_gate: 15, core_execution: 15, code_quality: 15, documentation_quality: 15 },
      [],
      15,
    );
    expect(result.excellence).toBe(0); // Gated
    expect(result.final_score).toBe(60);
  });

  it("clamps final score to 0 minimum", () => {
    const rubric = new ScoringRubric();
    const result = rubric.score(
      { completion_gate: 5, core_execution: 5, code_quality: 5, documentation_quality: 5 },
      [{ type: "generic_evidence", points: 100 }],
      0,
    );
    expect(result.final_score).toBe(0);
  });

  it("clamps final score to base+excellence maximum", () => {
    const rubric = new ScoringRubric();
    const result = rubric.score(
      { completion_gate: 20, core_execution: 20, code_quality: 25, documentation_quality: 20 },
      [],
      99,
    );
    expect(result.final_score).toBe(100); // 85 + 15 max
  });

  it("throws on unknown category", () => {
    const rubric = new ScoringRubric();
    expect(() =>
      rubric.score({ bogus_category: 10 }),
    ).toThrow("Unknown scoring categories");
  });

  it("throws on negative points", () => {
    const rubric = new ScoringRubric();
    expect(() =>
      rubric.score({ completion_gate: -5 }),
    ).toThrow("must be >= 0");
  });

  it("returns NEEDS_IMPROVEMENT for low scores", () => {
    const rubric = new ScoringRubric();
    const result = rubric.score(
      { completion_gate: 10, core_execution: 10, code_quality: 10, documentation_quality: 10 },
      [],
      0,
    );
    expect(result.rating).toBe("NEEDS_IMPROVEMENT");
  });

  it("returns EXCELLENT at exactly 85", () => {
    const rubric = new ScoringRubric();
    const result = rubric.score(
      { completion_gate: 20, core_execution: 20, code_quality: 25, documentation_quality: 20 },
      [],
      0,
    );
    expect(result.final_score).toBe(85);
    expect(result.rating).toBe("EXCELLENT");
  });
});
