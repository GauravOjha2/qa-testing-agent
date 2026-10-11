"""Website QA scanner UI: paste a URL, run the ADK pipeline, download the report.

Usage:
    py webapp:app                 # dev server on :8000
    uvicorn webapp:app --port 8080  # Cloud Run entrypoint

The scan runs as subprocesses (main.py then generate_pdf.py) so Playwright's
sync API never touches the event loop. Results link back to the generated PDF
and raw JSON artifacts.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

_REPO_ROOT = Path(__file__).resolve().parent
_ARTIFACTS_DIR = _REPO_ROOT / "local_findings_adk"
sys.path.insert(0, str(_REPO_ROOT))

from adk_qa_pipeline.generate_pdf import newest_log, page_slug  # noqa: E402

app = FastAPI(title="Website QA Scanner")

HOME_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Website QA Scanner</title>
  <style>
    * {box-sizing: border-box}
    body {margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
          font-family:'Segoe UI', -apple-system, Arial, sans-serif;
          background:linear-gradient(135deg,#0f172a 0%,#1e293b 100%); color:#e2e8f0; padding:24px}
    .card {width:100%; max-width:640px; background:rgba(15,23,42,.85); border:1px solid #334155;
           border-radius:16px; padding:40px 36px; box-shadow:0 20px 60px rgba(0,0,0,.5)}
    h1 {margin:0 0 8px; font-size:28px}
    .sub {color:#94a3b8; margin:0 0 28px; line-height:1.5; font-size:15px}
    label {display:block; font-weight:600; margin-bottom:8px; font-size:14px}
    input {width:100%; padding:12px 14px; font-size:15px; border-radius:10px;
           border:1px solid #475569; background:#0f172a; color:#e2e8f0; outline:none}
    input:focus {border-color:#3b82f6}
    button {margin-top:20px; width:100%; padding:13px; font-size:15px; font-weight:600;
            border:0; border-radius:10px; background:#3b82f6; color:#fff; cursor:pointer;
            transition:background .15s}
    button:hover {background:#2563eb}
    button:disabled {opacity:.5; cursor:not-allowed}
    .note {margin-top:16px; font-size:12px; color:#64748b; text-align:center}
    .error {background:#7f1d1d; border:1px solid #ef4444; border-radius:10px;
            padding:12px 14px; margin-top:20px; font-size:13px; white-space:pre-wrap}
  </style>
</head>
<body>
  <div class="card">
    <h1>Website QA Scanner</h1>
    <p class="sub">Paste a URL. The agent runs accessibility, performance, forms,
       visual QA, and AI-answer (GEO/AEO) checks, then hands you an executive PDF.</p>
    <form method="post" action="/scan" onsubmit="loading(this)">
      <label for="url">Website URL</label>
      <input id="url" name="url" type="url" required
             placeholder="https://example.com/"
             value="https://signup.xoxoday.in/plum-pricing/"/>
      <button type="submit" id="btn">Scan Website</button>
    </form>
    <div class="note">Scans take ~2&ndash;3 minutes. robots.txt is respected and form
       submission is blocked by guardrail &mdash; nothing is ever submitted.</div>
    {error}
  </div>
  <script>
    function loading(f) {{
      var b = document.getElementById('btn');
      b.disabled = true;
      b.textContent = 'Scanning&hellip; (2&ndash;3 min, please wait)';
    }}
  </script>
</body>
</html>"""

RESULT_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Scan Complete</title>
  <style>
    * {box-sizing: border-box}
    body {margin:0; font-family:'Segoe UI', -apple-system, Arial, sans-serif;
          background:linear-gradient(135deg,#0f172a 0%,#1e293b 100%); color:#e2e8f0; padding:32px 24px}
    .card {max-width:680px; margin:0 auto; background:rgba(15,23,42,.85); border:1px solid #334155;
           border-radius:16px; padding:36px}
    h1 {margin:0 0 4px; font-size:26px}
    .url {color:#94a3b8; font-size:13px; margin:0 0 24px; word-break:break-all}
    .stats {display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
            gap:12px; margin-bottom:24px}
    .stat {background:#0f172a; border:1px solid #334155; border-radius:12px; padding:16px; text-align:center}
    .num {font-size:28px; font-weight:700}
    .lbl {font-size:11px; color:#94a3b8; text-transform:uppercase; letter-spacing:.06em; margin-top:4px}
    .c-critical {color:#f87171} .c-high {color:#fb923c}
    .c-medium {color:#facc15} .c-ok {color:#4ade80}
    .risks {font-size:13px; line-height:1.7; color:#cbd5e1}
    .risks li {margin-bottom:4px}
    .btns {display:flex; gap:12px; margin-top:28px; flex-wrap:wrap}
    .btn {padding:12px 18px; border-radius:10px; text-decoration:none; font-weight:600;
          font-size:14px; border:1px solid #475569; color:#e2e8f0; transition:filter .15s}
    .btn:hover {filter:brightness(1.25)}
    .btn.primary {background:#3b82f6; border-color:#3b82f6}
  </style>
</head>
<body>
  <div class="card">
    <h1>Scan Complete</h1>
    <p class="url">{target_url}</p>
    <div class="stats">
      <div class="stat"><div class="num c-critical">{critical}</div><div class="lbl">Critical</div></div>
      <div class="stat"><div class="num c-high">{high}</div><div class="lbl">High</div></div>
      <div class="stat"><div class="num c-medium">{medium}</div><div class="lbl">Medium</div></div>
      <div class="stat"><div class="num">{total}</div><div class="lbl">Total findings</div></div>
      <div class="stat"><div class="num">{tools}</div><div class="lbl">Tool runs OK</div></div>
      <div class="stat"><div class="num">{elapsed}s</div><div class="lbl">Elapsed</div></div>
    </div>
    <p style="margin:0 0 6px; font-size:13px; font-weight:600; color:#94a3b8">TOP RISKS</p>
    <ol class="risks">{risks}</ol>
    <div class="btns">
      <a class="btn primary" href="/download/{pdf_name}">Download PDF Report</a>
      <a class="btn" href="/download/{json_name}">Download Raw JSON</a>
      <a class="btn" href="/">Scan Another URL</a>
    </div>
  </div>
</body>
</html>"""

ERROR_PAGE = HOME_PAGE.replace("{error}", '<div class="error">{error}</div>')


def _run_pipeline(url: str) -> Path:
    """Run main.py then generate_pdf.py as subprocesses; return the log path."""

    async def _run() -> Path:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(_REPO_ROOT / "adk_qa_pipeline" / "main.py"),
            "--url", url,
            cwd=_REPO_ROOT,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"main.py failed (exit {proc.returncode}):\n"
                f"{out.decode(errors='replace')[-2000:]}"
            )

        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(_REPO_ROOT / "adk_qa_pipeline" / "generate_pdf.py"),
            cwd=_REPO_ROOT,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"generate_pdf.py failed (exit {proc.returncode}):\n"
                f"{out.decode(errors='replace')[-2000:]}"
            )
        return newest_log()

    return asyncio.run(_run())


def _safe_artifact_path(fname: str) -> Path:
    """Resolve a download name to a real artifact, rejecting traversal."""

    if not fname or "/" in fname or "\\" in fname or ".." in fname:
        raise HTTPException(400, "Invalid file name")
    candidate = (_REPO_ROOT / fname).resolve()
    if not candidate.is_file():
        candidate = (_ARTIFACTS_DIR / fname).resolve()
    if not candidate.is_file():
        raise HTTPException(404, "File not found")
    return candidate


def _render(template: str, **values) -> str:
    """Token replace that ignores literal CSS braces (unlike str.format)."""

    for key, value in values.items():
        template = template.replace("{" + key + "}", str(value))
    return template


@app.get("/", response_class=HTMLResponse)
async def home() -> str:
    return HOME_PAGE.replace("{error}", "")


@app.post("/scan", response_class=HTMLResponse)
async def scan(url: str = Form(...)) -> str:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    try:
        log_path = await asyncio.to_thread(_run_pipeline, url)
    except Exception as exc:
        return ERROR_PAGE.replace("{error}", str(exc)[:1500])

    log = json.loads(log_path.read_text(encoding="utf-8"))
    meta = log.get("meta", {})
    counts = log.get("severity_counts", {})
    risks = log.get("top_risks") or ["No critical/high risks recorded"]
    pdf_name = f"ADK-QA-Report_{page_slug(url)}.pdf"

    return _render(
        RESULT_PAGE,
        target_url=meta.get("target_url", url),
        critical=counts.get("critical", 0),
        high=counts.get("high", 0),
        medium=counts.get("medium", 0),
        total=sum(counts.values()),
        tools=len(log.get("tool_runs", [])),
        elapsed=meta.get("elapsed_seconds", "?"),
        risks="".join(f"<li>{r}</li>" for r in risks),
        pdf_name=pdf_name,
        json_name=log_path.name,
    )


@app.get("/download/{fname}")
async def download(fname: str) -> FileResponse:
    path = _safe_artifact_path(fname)
    media = "application/pdf" if path.suffix.lower() == ".pdf" else "application/json"
    return FileResponse(path, filename=path.name, media_type=media)
