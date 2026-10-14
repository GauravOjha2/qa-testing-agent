"""Shim so `adk web` discovers this package.

ADK's NestedAgentLoader (web UI) only lists directories containing an
agent.py or root_agent.yaml - a bare __init__.py exporting root_agent is
invisible to it. Re-exporting here satisfies both discovery patterns;
the real definition stays in agents.py.
"""

from . import root_agent

__all__ = ["root_agent"]
