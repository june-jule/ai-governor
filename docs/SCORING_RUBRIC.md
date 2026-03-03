# Scoring Rubric

Evidence-based scoring model for Governor task reviews. This rubric defines how
task quality is measured, what constitutes compliance versus excellence, and how
automatic deductions are applied.

---

## Scoring Model

The scoring model separates **compliance** from **excellence**:

- **Compliance (configurable, default 85 points):** Awarded for meeting stated
  requirements, producing deliverables, and maintaining quality.
- **Excellence (configurable, default 15 points):** Bonus points locked behind
  evidence gates. Only awarded when the executor provides verifiable evidence of
  work beyond requirements.

A perfect score of 100 requires both full compliance AND proven excellence.

---

## Scoring Formula

```
category_total   = min(sum(category_scores), base_score)
excellence_total = excellence if category_total > 80 else 0
excellence_total = min(excellence_total, excellence_max)
deduction_total  = sum(deduction_points)

final_score = category_total + excellence_total - deduction_total
final_score = max(final_score, 0)
```

---

## Default Categories

The default rubric distributes the compliance score across four categories:

| Category | Max Points | Description |
|----------|-----------|-------------|
| Completion Gate | 20 | All deliverables exist, all steps complete |
| Core Execution | 20 | Correctness and completeness of the work |
| Code Quality | 25 | No linter errors, type safety, error handling |
| Documentation Quality | 20 | Clarity and maintainability |

---

## Evidence Gates

Evidence gates unlock excellence points. The principle: **points require
verifiable evidence.** Claims without proof earn zero excellence points.

- The base compliance score must exceed 80 before excellence points are
  considered.
- Each excellence claim must cite specific, verifiable evidence.

---

## Deductions

Deductions are subtracted from the total score. They are cumulative and uncapped.

| Type | Points | Trigger |
|------|--------|---------|
| Generic evidence | -10 | Citing "manual check" without logs or diffs |
| Placeholder text | -10 | `[TODO]`, `[PLACEHOLDER]`, or `TBD` in deliverables |
| Linter errors | -5 | Linter errors in final files |
| Broken paths | -5 | Referenced files do not exist |

---

## Rating Scale

| Score Range | Rating |
|-------------|--------|
| 95 - 100 | EXCEPTIONAL |
| 85 - 94 | EXCELLENT |
| Below 85 | NEEDS_IMPROVEMENT |

---

## Usage

```python
from governor.scoring.rubric import ScoringRubric

rubric = ScoringRubric()
result = rubric.score(
    categories={
        "completion_gate": 20,
        "core_execution": 20,
        "code_quality": 25,
        "documentation_quality": 20,
    },
    deductions=[{"type": "linter_errors", "points": 5}],
    excellence=10,
)
```

---

## Custom Rubrics

Provide your own rubric JSON to customize categories, deductions, and thresholds:

```python
rubric = ScoringRubric(rubric_path="/path/to/my_rubric.json")
```

See `governor/scoring/rubrics/default_rubric.json` for the JSON format.
