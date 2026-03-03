# Why Your Agents Need Governance

Your agents are productive. That's the problem — nobody's checking their work.

Without a quality gate between execution and production, you're running on trust. Here are four failure patterns we've seen — and how Governor prevents each one.

---

## 1. The Silent Deploy

An agent marked a deployment task as complete. The team moved on. Two hours later, production went down. The deploy had no rollback plan — nobody checked, and the agent didn't volunteer that it was missing.

**What Governor does:** EG-06 blocks any DEPLOY task that doesn't mention a rollback or revert strategy. The task stays in ACTIVE until the agent adds one. No human has to remember to check.

---

## 2. The Missing Evidence

An investigation task came back "done" with a two-sentence summary. No supporting data, no source references, no linked reports. The conclusions were plausible but unverifiable.

**What Governor does:** EG-02 requires a linked report for INVESTIGATION and AUDIT tasks. EG-07 checks that AUDIT tasks reference at least two evidence sources. Thin output gets blocked, not just flagged.

---

## 3. The Self-Approver

An agent submitted work and approved it in the same step. No second pair of eyes — human or otherwise — ever evaluated the output. Over time, the team assumed everything was reviewed. It wasn't.

**What Governor does:** The state machine enforces role separation. EXECUTOR submits (ACTIVE to READY_FOR_REVIEW). REVIEWER approves (READY_FOR_REVIEW to COMPLETED). One role cannot do both. The state machine is the guarantee, not a process document.

---

## 4. The Quality Slide

Early on, every agent output was manually reviewed. As volume increased, reviews got faster and shallower. Quality degraded gradually — nobody noticed until a customer did.

**What Governor does:** The scoring rubric provides a consistent, evidence-based quality signal on every task. Guards don't get tired. They check the same things at 2 AM as they do at 2 PM. Rework loops catch issues before they reach production.

---

## The Pattern

All four failures share a root cause: **no enforcement layer between agent output and production.** Process documents, code review checklists, and team norms help — but they depend on humans remembering to follow them.

Governor is the enforcement layer. It doesn't replace review — it makes sure the basics are covered before review starts.

