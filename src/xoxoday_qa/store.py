"""Findings persistence.

Every page's results are written to ./local_findings/ as one JSON file,
so the full evidence trail is inspectable without any infrastructure.
"""

from __future__ import annotations

import json
import os

from .config import RUN
from .models import PageResult


def save_page_result(result: PageResult) -> None:
    os.makedirs(RUN.findings_dir, exist_ok=True)
    safe_name = "".join(c if c.isalnum() else "_" for c in result.url)[:120]
    path = os.path.join(RUN.findings_dir, f"{safe_name}.json")
    payload = {
        "url": result.url,
        "tested_at": result.tested_at,
        "error": result.error,
        "console_errors": result.console_errors,
        "network_failures": result.network_failures,
        "findings": [f.to_dict() for f in result.findings],
    }
    with open(path, "w") as f:
        json.dump(payload, f, indent=2, default=str)


def load_all_results() -> list[dict]:
    """Used by the synthesis agent."""
    results = []
    if not os.path.isdir(RUN.findings_dir):
        return results
    for fname in os.listdir(RUN.findings_dir):
        if fname.endswith(".json"):
            with open(os.path.join(RUN.findings_dir, fname)) as f:
                results.append(json.load(f))
    return results
