"""SiteSentinel — website vulnerability & QA scanner.

Central configuration: identity, politeness, model, and stage budgets.
Everything tunable lives here; nothing is hard-coded in stage code.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = REPO_ROOT / "runs"
STATIC_DIR = REPO_ROOT / "static"
AXE_PATH = REPO_ROOT / "node_modules" / "axe-core" / "axe.min.js"

# --- Identity / politeness ----------------------------------------------
# Honest, contactable User-Agent. The same string is used for every HTTP
# request we make (robots fetch, Playwright contexts, Lighthouse).
USER_AGENT = (
    "SiteSentinelBot/1.0 (+https://xoxoday.com/sitesentinel; "
    "contact: qa-ops@xoxoday.com) Quality-Scanner"
)
THROTTLE_SECONDS = 1.5          # min delay between requests to a target origin
ROBOTS_TIMEOUT = 12.0           # seconds to fetch robots.txt before failing closed

# --- AI layer -------------------------------------------------------------
# Every AI layer in the product runs on this exact model. One key drives
# everything (GEMINI_API_KEY). No Gemini Pro, no other provider.
GEMINI_MODEL = "gemini-flash-latest"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
LLM_TIMEOUT = 75.0
LLM_MAX_RETRIES = 3

# --- Stage budgets (seconds) ----------------------------------------------
NAV_TIMEOUT_MS = 45_000
SCREENSHOT_SETTLE_MS = 1_500
VITALS_BUDGET = 150.0           # Lighthouse CLI can be slow
AXE_BUDGET = 60.0
FORMS_BUDGET = 120.0
AI_BUDGET = 120.0

# --- Safety ceilings --------------------------------------------------------
MAX_FORMS = 5                   # forms inspected per page
MAX_FIELDS_PER_FORM = 12        # fields filled per form
MAX_AXE_NODES_PER_RULE = 3      # evidence nodes kept per violation
MAX_GROUND_TRUTH_CHARS = 14_000 # page text sent to the AI layer
JOB_TTL_SECONDS = 2 * 60 * 60   # runs/ artifacts retained for 2 hours

VIEWPORTS = {
    "desktop": {"width": 1440, "height": 900},
    "tablet": {"width": 768, "height": 1024},
    "mobile": {"width": 390, "height": 844},
}

# Core Web Vitals thresholds (good / poor) used for severity mapping.
CWV_THRESHOLDS = {
    "lcp_ms": (2500, 4000),
    "cls": (0.1, 0.25),
    "inp_ms": (200, 500),
    "tbt_ms": (200, 600),   # lab proxy for INP when field data is absent
}

SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"]


_env_loaded = False


def load_env() -> None:
    """Populate os.environ from a local .env file (no extra dependency). Called once."""
    global _env_loaded
    if _env_loaded:
        return
    _env_loaded = True
    env_path = REPO_ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def gemini_api_key() -> str:
    load_env()
    return os.environ.get("GEMINI_API_KEY", "").strip()

# --- ADK engine (agent-graph orchestration) ---------------------------------
ENGINE = os.environ.get("SITESENTINEL_ENGINE", "adk").strip().lower()  # "adk" | "core"
ADK_STALL_TIMEOUT = 300.0   # max seconds between agent events before watchdog fires
ADK_TOTAL_BUDGET = 780.0    # hard cap for the whole agent-graph run
