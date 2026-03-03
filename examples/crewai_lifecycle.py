#!/usr/bin/env python3
"""CrewAI integration pattern: govern crew member output before handoff.

Shows how to gate a CrewAI task's output through Governor before the
next crew member picks it up. Prevents bad output from propagating
through your crew pipeline.

NOTE: This example requires ``crewai`` installed separately.
      Governor itself has zero dependencies.

      pip install crewai ai-governor
      python examples/crewai_lifecycle.py

This file is a **pattern reference** showing the integration approach.
"""

from governor.backend.memory_backend import MemoryBackend
from governor.engine.transition_engine import TransitionEngine
import governor.guards.executor_guards  # noqa: F401

# -- Setup ----------------------------------------------------------------

backend = MemoryBackend()
engine = TransitionEngine(backend=backend)


def govern_crew_task(
    task_id: str,
    crew_member: str,
    task_type: str,
    output: str,
    self_review_rating: float = 7.5,
) -> dict:
    """Gate a CrewAI task through Governor before the next crew member sees it.

    In a CrewAI pipeline, each crew member produces output that feeds into
    the next. Governor sits between them to ensure quality.

    Returns the Governor transition result.
    """
    # 1. Register the crew member's output as a Governor task
    backend.create_task({
        "task_id": task_id,
        "task_name": f"{crew_member}: {task_id}",
        "task_type": task_type,
        "role": "DEVELOPER",
        "status": "ACTIVE",
        "priority": "HIGH",
        "content": output,
    })

    # 2. The crew member's self-assessment
    backend.add_review(task_id, {
        "review_type": "SELF_REVIEW",
        "rating": self_review_rating,
        "content": f"Self-review by {crew_member}",
    })

    # 3. Link the output as a report
    backend.add_report(task_id, {
        "report_type": task_type,
        "content": output,
    })

    # 4. Run through quality gate
    result = engine.transition_task(task_id, "READY_FOR_REVIEW", "EXECUTOR")
    return result


# -- Demo: 3-member crew pipeline ----------------------------------------

if __name__ == "__main__":
    # Crew member 1: Researcher
    r1 = govern_crew_task(
        task_id="CREW_RESEARCH_001",
        crew_member="Researcher",
        task_type="INVESTIGATION",
        output=(
            "## Research Findings\n"
            "Source: internal docs. Evidence: API logs confirm 3x latency spike.\n"
            "Verified against monitoring dashboard. Cross-referenced with incident report.\n"
        ),
    )
    print(f"Researcher: {r1['result']}")

    # Crew member 2: Developer
    r2 = govern_crew_task(
        task_id="CREW_DEV_001",
        crew_member="Developer",
        task_type="IMPLEMENTATION",
        output=(
            "## Implementation\n"
            "Added connection pooling to reduce latency.\n\n"
            "## Tests\n"
            "Load test confirms 60% latency reduction.\n"
        ),
    )
    print(f"Developer:  {r2['result']}")

    # Crew member 3: Deployer
    r3 = govern_crew_task(
        task_id="CREW_DEPLOY_001",
        crew_member="Deployer",
        task_type="DEPLOY",
        output=(
            "## Deployment Plan\n"
            "Rolling deploy to staging, then production.\n\n"
            "## Rollback Strategy\n"
            "Revert to previous container image if health checks fail.\n"
        ),
    )
    print(f"Deployer:   {r3['result']}")

    print("\nAll crew outputs governed before handoff.")
