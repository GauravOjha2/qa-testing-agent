"""SiteSentinel web app — FastAPI entrypoint.

    py -m uvicorn server:app --port 8000      # local dev
    uvicorn server:app --host 0.0.0.0 --port 8080   # Cloud Run

Endpoints
    GET  /                          landing page (SPA)
    POST /api/scan                  start a scan -> {scan_id}
    GET  /api/scan/{id}/events      Server-Sent Events progress stream
    GET  /api/scan/{id}             job status + result JSON
    GET  /api/scan/{id}/report.pdf  A4 PDF report
    GET  /api/scan/{id}/report.json structured findings JSON
    GET  /api/scan/{id}/shot/{name} evidence screenshot (jpg/png)
    GET  /api/health                liveness + capability probe
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import re
import socket
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app import config
from app.engine import run_scan
from app.jobs import JobStore, sse

app = FastAPI(title="SiteSentinel — Website QA & Vulnerability Scanner", version="1.0.0")

# The UI can be hosted separately (e.g. Vercel) and call this engine directly,
# so cross-origin access to the read-only API is allowed. Set
# SITESENTINEL_ALLOWED_ORIGINS to a comma-separated list to lock it down.
_origins = [o.strip() for o in os.environ.get("SITESENTINEL_ALLOWED_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins or ["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
    max_age=86400,
)

store = JobStore()

_URL_RE = re.compile(r"^https?://[^\s/$.?#].[^\s]*$", re.IGNORECASE)
_BLOCKED_HOSTS = {"localhost", "metadata.google.internal"}

# Dev/CI only: allow scanning loopback + private-range hosts (used by the
# local fixture site in tests/fixture_site). Never enabled in production.
ALLOW_PRIVATE_TARGETS = os.environ.get("SITESENTINEL_ALLOW_PRIVATE_TARGETS") == "1"


def _validate_url(raw: str) -> str:
    """Normalise + guard the target. Blocks non-HTTP schemes, loopback,
    private ranges and cloud metadata endpoints (SSRF protection)."""
    raw = (raw or "").strip()
    if not raw:
        raise HTTPException(400, "Enter a website URL.")
    if not raw.startswith(("http://", "https://")):
        raw = f"https://{raw}"
    if not _URL_RE.match(raw):
        raise HTTPException(400, "That does not look like a valid http(s) URL.")
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if not host:
        raise HTTPException(400, "URL has no hostname.")
    if host in _BLOCKED_HOSTS or host.endswith(".local") or host.endswith(".internal"):
        raise HTTPException(400, "That host is not scannable.")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise HTTPException(400, f"Could not resolve {host}. Check the URL and try again.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            if not ALLOW_PRIVATE_TARGETS:
                raise HTTPException(400, "That host resolves to a private address and is not scannable.")
    return raw


async def _drive(job) -> None:
    job.status = "running"
    job.emit({"type": "status", "status": "running", "url": job.url})
    try:
        result = await run_scan(job.id, job.url, job.run_dir, job.emit)
        job.result = result.model_dump()
        job.status = "done"
        job.emit({"type": "done", "result": job.result})
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI verbatim
        job.status = "error"
        job.error = f"{type(exc).__name__}: {exc}"
        job.emit({"type": "error", "message": job.error})


@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok",
        "model": config.GEMINI_MODEL,
        "ai_enabled": bool(config.gemini_api_key()),
        "axe_core": config.AXE_PATH.is_file(),
        "private_targets_allowed": ALLOW_PRIVATE_TARGETS,
        "throttle_seconds": config.THROTTLE_SECONDS,
    }


@app.post("/api/scan")
async def start_scan(payload: dict) -> dict:
    url = _validate_url(str(payload.get("url", "")))
    job = store.create(url)
    asyncio.create_task(_drive(job))
    return {"scan_id": job.id, "url": url, "status": job.status}


@app.get("/api/scan/{scan_id}")
async def scan_status(scan_id: str) -> JSONResponse:
    job = store.get(scan_id)
    if not job:
        raise HTTPException(404, "Unknown scan id (it may have expired).")
    return JSONResponse(store.public(job))


@app.get("/api/scan/{scan_id}/events")
async def scan_events(scan_id: str, request: Request) -> StreamingResponse:
    job = store.get(scan_id)
    if not job:
        raise HTTPException(404, "Unknown scan id (it may have expired).")

    async def generator():
        try:
            async for event in job.stream():
                if await request.is_disconnected():
                    break
                yield sse(event)
        except asyncio.CancelledError:  # client navigated away
            return

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


def _artifact(scan_id: str, name: str) -> Path:
    job = store.get(scan_id)
    if not job:
        raise HTTPException(404, "Unknown scan id (it may have expired).")
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, "Invalid artifact name.")
    path = (job.run_dir / name).resolve()
    if job.run_dir.resolve() not in path.parents or not path.is_file():
        raise HTTPException(404, "Artifact not found.")
    return path


@app.get("/api/scan/{scan_id}/report.pdf")
async def report_pdf(scan_id: str) -> FileResponse:
    path = _artifact(scan_id, "report.pdf")
    return FileResponse(path, filename=f"SiteSentinel-QA-{scan_id}.pdf", media_type="application/pdf")


@app.get("/api/scan/{scan_id}/report.json")
async def report_json(scan_id: str) -> FileResponse:
    path = _artifact(scan_id, "report.json")
    return FileResponse(path, filename=f"SiteSentinel-QA-{scan_id}.json", media_type="application/json")


@app.get("/api/scan/{scan_id}/shot/{name}")
async def shot(scan_id: str, name: str) -> FileResponse:
    """Serve an evidence capture. Only a bare file name is accepted, and it
    must resolve inside that job's own shots/ directory."""
    job = store.get(scan_id)
    if not job:
        raise HTTPException(404, "Unknown scan id (it may have expired).")
    if not name or name != Path(name).name or ".." in name:
        raise HTTPException(400, "Invalid capture name.")
    path = (job.run_dir / "shots" / name).resolve()
    if path.parent != (job.run_dir / "shots").resolve() or not path.is_file():
        raise HTTPException(404, "Capture not found.")
    media = "image/jpeg" if path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    return FileResponse(path, media_type=media)


# The UI is plain static files served from the same origin. Mounted last so
# every /api route above wins; html=True makes "/" serve index.html.
app.mount("/", StaticFiles(directory=config.STATIC_DIR, html=True), name="ui")
