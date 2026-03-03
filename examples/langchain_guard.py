#!/usr/bin/env python3
"""LangChain integration pattern: govern agent output before acting on it.

Shows how to wrap a LangChain agent's final output with Governor quality
gates. The agent produces a result -> Governor validates -> approved or
sent back for rework.

NOTE: This example requires ``langchain`` installed separately.
      Governor itself has zero dependencies.

      pip install langchain ai-governor
      python examples/langchain_guard.py

This file is a **pattern reference**, not a runnable script — it shows
how the integration works without requiring LangChain installed.
"""

from governor.backend.memory_backend import MemoryBackend
from governor.engine.transition_engine import TransitionEngine
import governor.guards.executor_guards  # noqa: F401

# -- Setup ----------------------------------------------------------------

backend = MemoryBackend()
engine = TransitionEngine(backend=backend)

# -- Pattern: Govern agent output after LangChain execution ---------------

def govern_agent_output(task_id: str, agent_output: str) -> dict:
    """Run Governor quality gates on an agent's final output.

    Call this after your LangChain agent finishes. Governor checks that
    the output meets your quality bar (self-review exists, deliverables
    are present, etc.) before you act on it.

    Returns the Governor transition result with PASS/FAIL and guard details.
    """
    # 1. Store the agent's output as a Governor task
    backend.create_task({
        "task_id": task_id,
        "task_name": f"LangChain output: {task_id}",
        "task_type": "IMPLEMENTATION",
        "role": "DEVELOPER",
        "status": "ACTIVE",
        "priority": "HIGH",
        "content": agent_output,
    })

    # 2. Add a self-review (your agent should produce one)
    backend.add_review(task_id, {
        "review_type": "SELF_REVIEW",
        "rating": 8.0,
        "content": "Agent self-assessment of output quality.",
    })

    # 3. Add a report (evidence of work done)
    backend.add_report(task_id, {
        "report_type": "IMPLEMENTATION",
        "content": f"Output produced by LangChain agent for {task_id}.",
    })

    # 4. Attempt submission through Governor quality gate
    result = engine.transition_task(task_id, "READY_FOR_REVIEW", "EXECUTOR")

    if result["result"] == "PASS":
        print(f"[PASS] {task_id} passed all guards. Safe to act on output.")
    else:
        print(f"[FAIL] {task_id} blocked by guards:")
        for gr in result["guard_results"]:
            if not gr["passed"]:
                print(f"  - {gr['guard_id']}: {gr['reason']}")
                if gr.get("fix_hint"):
                    print(f"    Fix: {gr['fix_hint']}")

    return result


# -- Demo -----------------------------------------------------------------

if __name__ == "__main__":
    # Simulate LangChain agent output
    agent_output = (
        "## Implementation\n"
        "Added error handling to the payment service.\n\n"
        "## Tests\n"
        "Verified with unit tests covering edge cases.\n"
    )

    result = govern_agent_output("LANGCHAIN_TASK_001", agent_output)
    print(f"\nGovernor verdict: {result['result']}")
