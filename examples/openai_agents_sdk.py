#!/usr/bin/env python3
"""OpenAI Agents SDK integration: agent self-governs via tool call.

Shows how to register a ``governor_submit`` tool that an OpenAI agent
calls when it believes work is done. Governor evaluates guards and
returns results so the agent can self-correct if needed.

NOTE: This example requires the ``openai`` SDK installed separately.
      Governor itself has zero dependencies.

      pip install openai ai-governor
      python examples/openai_agents_sdk.py

This file is a **pattern reference** showing the integration approach.
"""

from governor.backend.memory_backend import MemoryBackend
from governor.engine.transition_engine import TransitionEngine
import governor.guards.executor_guards  # noqa: F401

# -- Setup ----------------------------------------------------------------

backend = MemoryBackend()
engine = TransitionEngine(backend=backend)


def governor_submit_tool(
    task_id: str,
    content: str,
    task_type: str = "IMPLEMENTATION",
    self_review_notes: str = "",
    self_review_rating: float = 7.5,
) -> dict:
    """Tool function an OpenAI agent calls to submit work for review.

    Register this as a tool in your OpenAI Agents SDK configuration.
    The agent calls it when it thinks its work is complete. Governor
    evaluates all guards and returns the result. On FAIL, the agent
    gets guard details and fix hints to self-correct.

    Returns:
        Dict with 'result' (PASS/FAIL), 'guard_results', and 'fix_hints'.
    """
    # Create or update task
    if not backend.task_exists(task_id):
        backend.create_task({
            "task_id": task_id,
            "task_name": f"Agent task: {task_id}",
            "task_type": task_type,
            "role": "DEVELOPER",
            "status": "ACTIVE",
            "priority": "HIGH",
            "content": content,
        })

    # Agent provides self-review
    backend.add_review(task_id, {
        "review_type": "SELF_REVIEW",
        "rating": self_review_rating,
        "content": self_review_notes or "Agent self-assessment",
    })

    # Agent output becomes the report
    backend.add_report(task_id, {
        "report_type": task_type,
        "content": content,
    })

    # Run quality gate
    result = engine.transition_task(task_id, "READY_FOR_REVIEW", "EXECUTOR")

    # Format for agent consumption
    response = {
        "result": result["result"],
        "guard_results": result["guard_results"],
        "fix_hints": [],
    }

    if result["result"] == "FAIL":
        for gr in result["guard_results"]:
            if not gr["passed"] and gr.get("fix_hint"):
                response["fix_hints"].append(f"{gr['guard_id']}: {gr['fix_hint']}")

    return response


# -- Demo: Agent self-correction loop ------------------------------------

if __name__ == "__main__":
    # Attempt 1: Agent submits incomplete work (missing test references)
    print("--- Attempt 1: Missing test references ---")
    r1 = governor_submit_tool(
        task_id="AGENT_TASK_001",
        content="Added caching to the API endpoint for faster responses.",
        task_type="IMPLEMENTATION",
        self_review_notes="Looks good to me.",
    )
    print(f"Result: {r1['result']}")
    if r1["fix_hints"]:
        print("Fix hints for agent:")
        for hint in r1["fix_hints"]:
            print(f"  - {hint}")

    # Attempt 2: Agent self-corrects based on guard feedback
    print("\n--- Attempt 2: Agent adds test references ---")
    r2 = governor_submit_tool(
        task_id="AGENT_TASK_002",
        content=(
            "Added caching to the API endpoint for faster responses.\n\n"
            "## Verification\n"
            "Test suite updated. Integration tests confirm cache hit rate > 90%.\n"
        ),
        task_type="IMPLEMENTATION",
        self_review_notes="Added test coverage after guard feedback.",
        self_review_rating=8.5,
    )
    print(f"Result: {r2['result']}")
    print(f"\nAgent learned from guard feedback and self-corrected.")
