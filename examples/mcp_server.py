#!/usr/bin/env python3
"""Minimal MCP server hosting Governor quality gate tools.

Exposes 2 tools via Model Context Protocol:
- governor_transition_task — execute or dry-run transitions
- governor_get_available_transitions — query what's possible

Usage::

    pip install ai-governor[mcp]
    python examples/mcp_server.py

This file is a **pattern reference**. Adapt the backend and server
setup to your environment.
"""

from governor.backend.memory_backend import MemoryBackend
from governor.engine.transition_engine import TransitionEngine
from governor.mcp.tools import create_governor_tools
import governor.guards.executor_guards  # noqa: F401


def main():
    # 1. Configure Governor
    backend = MemoryBackend()
    engine = TransitionEngine(backend=backend)

    # 2. Create MCP tool definitions
    tools = create_governor_tools(engine)

    print("Governor MCP tools ready:")
    for tool in tools:
        print(f"  - {tool['name']}: {tool['description'][:60]}...")

    print(f"\n{len(tools)} tools available for MCP server registration.")
    print("\nTo use with an MCP server, register each tool's 'handler' callable")
    print("with your MCP server implementation (e.g. mcp.server.Server).")

    # Example: direct tool invocation (without MCP transport)
    print("\n--- Direct invocation demo ---")

    backend.create_task({
        "task_id": "MCP_DEMO_001",
        "task_name": "MCP Demo Task",
        "task_type": "IMPLEMENTATION",
        "role": "DEVELOPER",
        "status": "ACTIVE",
        "priority": "HIGH",
        "content": "Implemented feature with tests verifying correctness.",
    })
    backend.add_review("MCP_DEMO_001", {"review_type": "SELF_REVIEW", "rating": 8.0})
    backend.add_report("MCP_DEMO_001", {"report_type": "IMPLEMENTATION", "content": "Done."})

    # Call the tool handler directly
    transition_tool = tools[0]
    result = transition_tool["handler"](
        task_id="MCP_DEMO_001",
        target_state="READY_FOR_REVIEW",
        calling_role="EXECUTOR",
    )
    print(f"transition_task result: {result['result']}")


if __name__ == "__main__":
    main()
