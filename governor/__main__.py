"""Entry point for ``python -m governor``.

Subcommands:

- ``python -m governor`` or ``python -m governor demo``
    Run a quick demo showing Governor's task lifecycle.

- ``python -m governor validate [path]``
    Validate a state machine JSON file.  Defaults to the bundled
    ``governor/schema/state_machine.json``.
"""

import json
import logging
import sys

from governor.backend.memory_backend import MemoryBackend
from governor.engine.transition_engine import TransitionEngine
from governor.engine.validation import validate_state_machine
import governor.guards.executor_guards  # noqa: F401

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


def _cmd_validate(args: list) -> int:
    """Validate a state machine JSON file."""
    from importlib import resources

    if args:
        path = args[0]
    else:
        # Use bundled state machine
        try:
            bundled = resources.files("governor").joinpath("schema/state_machine.json")
            path = str(bundled)
        except Exception:
            print("ERROR: Could not locate bundled state_machine.json")
            return 1

    print(f"Validating: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            sm = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"ERROR: {e}")
        return 1

    errors = validate_state_machine(sm)
    if errors:
        print(f"\nFAILED — {len(errors)} error(s):\n")
        for err in errors:
            print(f"  - {err}")
        return 1

    # Print summary
    meta = sm.get("_meta", {})
    version = meta.get("version", "unknown")
    states = list(sm.get("states", {}).keys())
    transitions = sm.get("transitions", [])
    guard_ids: list = []
    for t in transitions:
        for g in t.get("guards", []):
            gid = g if isinstance(g, str) else (g.get("guard_id") if isinstance(g, dict) else None)
            if gid and gid not in guard_ids:
                guard_ids.append(gid)

    print(f"\nPASSED (version {version})")
    print(f"  States:      {len(states)} ({', '.join(states)})")
    print(f"  Transitions: {len(transitions)} ({', '.join(t['id'] for t in transitions)})")
    print(f"  Guards:      {len(guard_ids)} unique ({', '.join(guard_ids)})")
    return 0


def _cmd_demo() -> int:
    """Run the quick demo."""
    backend = MemoryBackend()
    engine = TransitionEngine(
        backend=backend,
        role_aliases={"DEVELOPER": "EXECUTOR"},
    )

    print("=" * 60)
    print("Governor — Quick Demo")
    print("=" * 60)

    # 1. Create a task
    task_id = "TASK_DEMO_001"
    backend.create_task({
        "task_id": task_id,
        "task_name": "Implement user authentication",
        "task_type": "IMPLEMENTATION",
        "role": "DEVELOPER",
        "status": "ACTIVE",
        "priority": "HIGH",
        "content": (
            "Implement OAuth2 authentication flow with PKCE.\n\n"
            "## Deliverables\n"
            "- `auth.py` — OAuth2 handler\n"
            "- `auth_test.py` — Test suite\n\n"
            "## Test Plan\n"
            "Run test suite to verify login flow."
        ),
    })
    print(f"\n[1] Created task: {task_id} (status=ACTIVE)")

    # 2. Check available transitions
    available = engine.get_available_transitions(task_id, "DEVELOPER")
    print("\n[2] Available transitions from ACTIVE:")
    for t in available["transitions"]:
        status = "READY" if t["ready"] else f"NOT READY ({len(t['guards_missing'])} guards unmet)"
        print(f"    -> {t['target_state']:25s} {status}")

    # 3. Try submitting without evidence (should fail)
    result = engine.transition_task(task_id, "READY_FOR_REVIEW", "DEVELOPER")
    print(f"\n[3] Submit without evidence: {result['result']}")
    for gr in result["guard_results"]:
        if not gr["passed"]:
            print(f"    FAIL {gr['guard_id']}: {gr['reason']}")

    # 4. Add evidence and retry
    backend.add_report(task_id, {
        "report_id": "REPORT_IMPL_001",
        "report_type": "IMPLEMENTATION",
        "content": "OAuth2 PKCE flow implemented. Auth handler and test suite delivered.",
    })
    backend.add_review(task_id, {
        "review_id": "REVIEW_SELF_001",
        "review_type": "SELF_REVIEW",
        "reviewer_role": "DEVELOPER",
        "rating": 8.5,
        "content": "Implemented OAuth2 PKCE flow. All 12 tests pass.",
    })
    result = engine.transition_task(task_id, "READY_FOR_REVIEW", "DEVELOPER")
    print(f"\n[4] Submit with evidence: {result['result']}")

    # 5. Reviewer approves
    result = engine.transition_task(task_id, "COMPLETED", "REVIEWER")
    print(f"\n[5] Reviewer approves: {result['result']}")

    final = backend.get_task(task_id)["task"]
    print(f"\n{'=' * 60}")
    print(f"Final status: {final['status']}")
    print("=" * 60)
    return 0


def main() -> int:
    args = sys.argv[1:]
    cmd = args[0] if args else "demo"

    if cmd == "validate":
        return _cmd_validate(args[1:])
    elif cmd in ("demo", "run"):
        return _cmd_demo()
    elif cmd in ("-h", "--help", "help"):
        print("Usage: python -m governor [command]")
        print()
        print("Commands:")
        print("  demo       Run interactive lifecycle demo (default)")
        print("  validate   Validate state machine JSON (accepts optional path)")
        print("  help       Show this help message")
        return 0
    else:
        print(f"Unknown command: {cmd}")
        print("Run 'python -m governor help' for usage.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
