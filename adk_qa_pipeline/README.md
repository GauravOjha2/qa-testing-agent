# Legacy: Google ADK pipeline (archived)

This directory is the **original prototype** of the scanner, built on the
[Google ADK](https://google.github.io/adk-docs/) agent framework. It was retired in
commit `34dc899` when the product was rebuilt as the production FastAPI engine in
`app/` (orchestrator in `app/engine.py`, stages in `app/stages/`).

It is kept for reference and demonstration — it is **not** imported, tested, or run
by the current product, and nothing in `app/`, `server.py`, or `static/` depends on it.

## What it shows

- `agent.py` / `agents.py` — the ADK agent graph: root orchestrator agent with
  sub-agents for visual, forms, accessibility/performance, and GEO/AEO checks.
- `tools.py` — the tool layer the agents called (Playwright capture, axe-core,
  Lighthouse, form probing).
- `main.py` — the interactive runner (`adk web`).
- `generate_pdf.py` — the first PDF report generator.
- `../src/xoxoday_qa/` — the shared scanning library the agents wrapped
  (crawler, config, DOM and Playwright utilities).
- `../webapp.py` — the first minimal web UI for the ADK pipeline.

## Running it (optional, demo only)

```powershell
python -m pip install -r adk_qa_pipeline/requirements.txt
adk web        # then open the ADK dev UI
```

Requires a `GEMINI_API_KEY`. The ADK packages are not installed by the main
`requirements.txt`; install them only if you want to demo this prototype.
