"""MCP (Model Context Protocol) tool wrapper for Governor.

Exposes Governor's core API as MCP tools for any MCP-compatible agent.

    pip install ai-governor[mcp]
"""

from governor.mcp.tools import create_governor_tools

__all__ = ["create_governor_tools"]
