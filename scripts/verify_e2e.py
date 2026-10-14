"""End-to-end verification of the SiteSentinel flow.

Runs against a live server (default http://127.0.0.1:8080) and exercises
exactly what a user does:

    landing page -> POST /api/scan -> SSE progress stream -> results
    -> download PDF -> download JSON

It asserts the contract the product promises: five stages reported,
findings deduplicated, forms never submitted, a real multi-page A4 PDF
produced, and screenshots captured.

Usage:
    python scripts/verify_e2e.py http://127.0.0.1:8080 http://127.0.0.1:8099/
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080"
TARGET = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8099/"
OUT = Path("local_verify")
FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"{'PASS' if condition else 'FAIL'}  {label}{' — ' + detail if detail else ''}")
    if not condition:
        FAILURES.append(label)


def main() -> int:
    OUT.mkdir(exist_ok=True)
    with httpx.Client(timeout=120.0) as client:
        # --- 1. landing page + assets ------------------------------------
        home = client.get(f"{BASE}/")
        check("landing page serves HTML", home.status_code == 200 and "Caliber" in home.text,
              f"{home.status_code}, {len(home.text)} bytes")
        for marker in ("What it checks", "How it works", "Safety", "The report",
                       "checkList", "stepList", "factList", "report-shot",
                       "view-progress", "view-results", "view-error"):
            check(f"landing markup contains {marker}", marker in home.text)
        for gone in ("Playwright", "axe-core", "Lighthouse", "gemini-flash-latest"):
            check(f"landing does not name the tooling ({gone})", gone not in home.text)
        for asset in ("app.css", "app.js", "app-config.js", "favicon.svg"):
            res = client.get(f"{BASE}/{asset}")
            check(f"static asset /{asset}", res.status_code == 200, str(res.status_code))
        for asset in ("img/pdf-cover.png",):
            res = client.get(f"{BASE}/{asset}")
            check(f"static asset /{asset}", res.status_code == 200, str(res.status_code))
        health = client.get(f"{BASE}/api/health").json()
        check("health reports gemini-flash-latest", health.get("model") == "gemini-flash-latest",
              json.dumps(health))

        # --- 2. start the scan -------------------------------------------
        started = time.time()
        resp = client.post(f"{BASE}/api/scan", json={"url": TARGET})
        check("POST /api/scan accepted", resp.status_code == 200, resp.text[:200])
        scan_id = resp.json()["scan_id"]
        print(f"      scan_id = {scan_id}")

        # --- 3. stream progress (SSE) -------------------------------------
        stages: dict[str, dict] = {}
        logs = 0
        result = None
        with client.stream("GET", f"{BASE}/api/scan/{scan_id}/events", timeout=600.0) as stream:
            for line in stream.iter_lines():
                if not line.startswith("data: "):
                    continue
                event = json.loads(line[6:])
                if event["type"] == "log":
                    logs += 1
                    print(f"      · {event['message']}")
                elif event["type"] == "stage":
                    if event["status"] == "running":
                        print(f"      [running ] {event['label']}")
                        continue
                    stages[event["key"]] = event
                    print(f"      [{event['status']:8}] {event['label']} ({event.get('elapsed_seconds')}s)")
                elif event["type"] == "done":
                    result = event["result"]
                    break
                elif event["type"] == "error":
                    check("scan completed", False, event.get("message", ""))

        check("five stages reported", len(stages) == 5, ", ".join(sorted(stages)))
        check("no stage hard-failed", all(s["status"] != "failed" for s in stages.values()),
              json.dumps({k: v["status"] for k, v in stages.items()}))
        check("progress log streamed", logs > 0, f"{logs} lines")
        if result is None:
            print("no result payload — aborting")
            return 1

        # --- 4. result contract ------------------------------------------
        findings = result["findings"]
        ids = [f["id"] for f in findings]
        check("findings returned", len(findings) > 0, f"{len(findings)} findings")
        check("findings deduplicated", len(ids) == len(set(ids)))
        check("severity counts consistent",
              sum(result["severity_counts"].values()) == len(findings),
              json.dumps(result["severity_counts"]))
        check("forms never submitted", result["safety"]["forms_submitted"] == 0)
        check("screenshots captured", len(result["screenshots"]) == 3,
              ", ".join(s["viewport"] for s in result["screenshots"]))
        check("executive summary present", bool(result["executive_summary"].strip()))
        check("top risks present", len(result["top_risks"]) > 0)
        check("model is gemini-flash-latest", result["model"] == "gemini-flash-latest")
        categories = sorted({f["category"] for f in findings})
        print(f"      categories: {categories}")
        print(f"      severities: {result['severity_counts']}")

        # --- 5. artifacts --------------------------------------------------
        pdf = client.get(f"{BASE}/api/scan/{scan_id}/report.pdf")
        (OUT / "report.pdf").write_bytes(pdf.content)
        check("PDF downloads", pdf.status_code == 200 and pdf.content[:4] == b"%PDF",
              f"{len(pdf.content)} bytes")
        pages = pdf.content.count(b"/Type /Page") or pdf.content.count(b"/Type/Page")
        check("PDF has multiple A4 pages", pages >= 3, f"~{pages} pages")

        raw = client.get(f"{BASE}/api/scan/{scan_id}/report.json")
        (OUT / "report.json").write_bytes(raw.content)
        check("JSON downloads", raw.status_code == 200 and "findings" in raw.text,
              f"{len(raw.content)} bytes")

        shot = client.get(f"{BASE}/api/scan/{scan_id}/shot/mobile.jpg")
        (OUT / "mobile.jpg").write_bytes(shot.content)
        check("evidence screenshot serves", shot.status_code == 200 and len(shot.content) > 5000,
              f"{len(shot.content)} bytes")

        check("scan completed in a sane window", time.time() - started < 600,
              f"{time.time() - started:.0f}s")

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
        return 1
    print("All end-to-end checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
