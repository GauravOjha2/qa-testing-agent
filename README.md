# QA Testing Agent (Google ADK)

Multi-agent website QA auditor built on **Google Agent Development Kit (ADK)**.
A supervisor LLM orchestrates four specialist agents that run deterministic,
safety-gated Playwright / axe-core / Lighthouse audits against a target page
and aggregate the results into a structured JSON log and a PDF report.

> **Looking for the original raw-Python procedural pipeline?** It is preserved
> on the [`procedural-pipeline`](../../tree/procedural-pipeline) branch.

## Architecture

```
                    qa_supervisor_agent (gemini-flash-latest)
                    orchestrates via transfer_to_agent
        ┌───────────────┬────────────────┬────────────────┐
        ▼               ▼                ▼                ▼
 visual_qa_agent  a11y_perf_agent   forms_agent    geo_aeo_agent
 (flash)          (flash)           (flash,        (pro)
 capture @3       axe-core WCAG     guarded by     ground-truth
 breakpoints +    + Lighthouse CWV  prevent_form_  hallucination
 overflow probe   + silent failures submit_       self-consistency
                                    guardrail      check
        └───────────────┴────────────────┴────────────────┘
                            ▼
        deterministic execution layer (adk_qa_pipeline/tools.py)
        headless Chromium · robots.txt fail-closed · 1.5s throttle
```

## Safety invariants

- **robots.txt fail-closed** — every tool call re-verifies permission; an
  unreachable robots.txt blocks the scan.
- **Never submits forms** — enforced twice: `prevent_form_submit_guardrail`
  (before_tool_callback) plus hard-coded no-submit inside the tool itself.
- **Honest identity** — contactable User-Agent on every request.
- **Polite pacing** — minimum 1.5s between page loads.
- Findings come from tool payloads harvested from the ADK event stream —
  never from trusting model prose.

## Setup

```bash
pip install -r requirements.txt
playwright install chromium

# .env (gitignored):
GEMINI_API_KEY=your_key_here
```

## Run

```bash
# full audit -> structured JSON in local_findings_adk/
python adk_qa_pipeline/main.py --url https://example.com/

# render the newest run as a PDF report
python adk_qa_pipeline/generate_pdf.py
```

Optional per-domain buyer questions for the GEO/AEO hallucination check live
in `BUYER_QUESTIONS_BY_DOMAIN` (`adk_qa_pipeline/tools.py`).

## Layout

| Path | Purpose |
|---|---|
| `adk_qa_pipeline/agents.py` | Specialist agents, supervisor, submit-block guardrail |
| `adk_qa_pipeline/tools.py` | Execution layer: Playwright/axe/Lighthouse tools |
| `adk_qa_pipeline/main.py` | Async runner + JSON log aggregation |
| `adk_qa_pipeline/generate_pdf.py` | PDF report renderer (sliced screenshots) |
| `src/xoxoday_qa/` | Shared core: config, safety, Playwright helpers, robots gate |
| `tests/` | Unit tests for the shared core |

## Tests

```bash
python -m pytest tests/ -q
```
