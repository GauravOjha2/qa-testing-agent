"""Run the full pipeline locally, single-process, no GCP required.

This exists to prove the pipeline shape (crawl -> classify -> per-page
4-agent run -> synthesis -> HTML report) end-to-end before spending Cloud
Run / API budget on a real deployment. It's the same code path as
cloud_run_job/main.py, just with shard count fixed at 1 and Firestore
swapped for local JSON (QA_LOCAL_MODE=1, the default).

Usage:
    python3 scripts/run_local_demo.py --urls https://example.com https://example.com/pricing
    python3 scripts/run_local_demo.py --sitemap https://www.xoxoday.com/sitemap.xml --demo-subset

Note: this machine has no outbound network access, so a live run against
xoxoday.com (or any real site) needs to happen in an environment that does.
This script is fully wired and will work as-is there.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from xoxoday_qa.agents import a11y_perf_agent, forms_agent, geo_aeo_agent, synthesis_agent, visual_qa  # noqa: E402
from xoxoday_qa.crawler import build_target_list, classify, select_demo_subset  # noqa: E402
from xoxoday_qa.models import PageResult, PageTarget  # noqa: E402
from xoxoday_qa.playwright_utils import browser_session  # noqa: E402
from xoxoday_qa.store import save_page_result  # noqa: E402


def gather_targets(args) -> list[PageTarget]:
    if args.urls:
        return [classify(u) for u in args.urls]
    targets = build_target_list(args.sitemap)
    if args.demo_subset:
        targets = select_demo_subset(targets)
    return targets


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--urls", nargs="*", help="Explicit URL list (skips sitemap crawl)")
    parser.add_argument("--sitemap", default=None, help="Sitemap URL to crawl instead")
    parser.add_argument("--demo-subset", action="store_true", help="Trim crawled targets to the 15-25 page demo subset")
    parser.add_argument("--report-out", default="report.html")
    args = parser.parse_args()

    targets = gather_targets(args)
    if not targets:
        print("No targets found — pass --urls or a reachable --sitemap.")
        return

    print(f"Testing {len(targets)} page(s)...")
    started = time.time()

    with browser_session() as browser:
        for target in targets:
            print(f"  -> {target.url} ({target.page_type.value})")
            result = PageResult(url=target.url)
            try:
                result.findings.extend(visual_qa.run(browser, target, "screenshots/local"))
                result.findings.extend(forms_agent.run(browser, target))
                result.findings.extend(geo_aeo_agent.run(browser, target))
                result.findings.extend(a11y_perf_agent.run(browser, target))
            except Exception as e:
                result.error = f"{type(e).__name__}: {e}"
                print(f"     ERROR: {result.error}")
            save_page_result(result)

    elapsed = time.time() - started
    report_path = synthesis_agent.run(run_seconds=elapsed, pages_tested=len(targets), out_path=args.report_out)
    print(f"\nDone in {elapsed:.1f}s. Report: {report_path}")


if __name__ == "__main__":
    main()
