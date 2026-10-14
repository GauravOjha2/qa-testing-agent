"""Google ADK multi-agent refactor of the procedural Xoxoday QA pipeline.

Package layout:
    tools.py   - deterministic execution layer (Playwright / axe-core / Lighthouse)
    agents.py  - brain & routing layer (specialists + safety guardrail + supervisor)
    main.py    - orchestrator (runs the supervisor, aggregates structured JSON)

The original raw-Python procedural pipeline is preserved on the
`procedural-pipeline` branch; this package wraps its battle-tested
helpers under src/xoxoday_qa/ instead of duplicating them.
"""

try:
    from . import agents as _agents

    root_agent = _agents.qa_supervisor_agent
except Exception:  # pragma: no cover - allows `adk web` to boot without creds
    root_agent = None

__all__ = ["root_agent"]
