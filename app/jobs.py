"""In-process job registry + SSE fan-out.

A scan is a long-running task (~2-3 min). Each job keeps its full event
history so a client that connects late still sees the whole progress
story, and a set of live listener queues so several tabs can watch the
same scan. Artifacts live under runs/<scan_id>/ and expire via TTL sweep.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator

from . import config


@dataclass
class Job:
    id: str
    url: str
    run_dir: Path
    status: str = "queued"          # queued | running | done | error
    created: float = field(default_factory=time.time)
    events: list[dict[str, Any]] = field(default_factory=list)
    listeners: set[asyncio.Queue] = field(default_factory=set)
    result: dict[str, Any] | None = None
    error: str | None = None

    def emit(self, event: dict[str, Any]) -> None:
        """Record an event and fan it out. Synchronous on purpose: it is
        called from the scan coroutine on the same event loop."""
        self.events.append(event)
        for queue in list(self.listeners):
            queue.put_nowait(event)

    async def stream(self) -> AsyncIterator[dict[str, Any]]:
        """Yield the event history, then live events until the job ends."""
        queue: asyncio.Queue = asyncio.Queue()
        already = len(self.events)          # atomic: no await between these two lines
        self.listeners.add(queue)
        try:
            for event in self.events[:already]:
                yield event
                if event.get("type") in ("done", "error"):
                    return
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield {"type": "heartbeat", "ts": time.time()}
                    continue
                yield event
                if event.get("type") in ("done", "error"):
                    return
        finally:
            self.listeners.discard(queue)


class JobStore:
    def __init__(self, root: Path = config.RUNS_DIR) -> None:
        self._jobs: dict[str, Job] = {}
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def create(self, url: str) -> Job:
        self.sweep()
        scan_id = uuid.uuid4().hex[:16]
        run_dir = self._root / scan_id
        run_dir.mkdir(parents=True, exist_ok=True)
        job = Job(id=scan_id, url=url, run_dir=run_dir)
        self._jobs[scan_id] = job
        return job

    def get(self, scan_id: str) -> Job | None:
        return self._jobs.get(scan_id)

    def sweep(self) -> None:
        """Drop jobs (and their artifacts) older than JOB_TTL_SECONDS."""
        cutoff = time.time() - config.JOB_TTL_SECONDS
        for scan_id, job in list(self._jobs.items()):
            if job.created < cutoff:
                self._jobs.pop(scan_id, None)
                shutil.rmtree(job.run_dir, ignore_errors=True)

    def public(self, job: Job) -> dict[str, Any]:
        return {
            "scan_id": job.id,
            "url": job.url,
            "status": job.status,
            "elapsed": round(time.time() - job.created, 1),
            "error": job.error,
            "result": job.result,
        }


def sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
