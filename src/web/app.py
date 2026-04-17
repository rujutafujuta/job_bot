"""FastAPI web app — Slice 1 dashboard + Slice 2 review page."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

from src.tracking.db import (
    count_by_status,
    get_followup_due,
    get_job_by_id,
    get_jobs_by_status,
    get_priority_queue,
    get_recent_activity,
    init_db,
    update_job_by_id,
)

_DB_PATH = Path("data/tracking.db")
_TEMPLATES_DIR = Path(__file__).parent / "templates"

app = FastAPI(title="Job Bot")
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@app.on_event("startup")
async def startup() -> None:
    init_db(_DB_PATH)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    counts = count_by_status(_DB_PATH)
    activity = get_recent_activity(limit=10, db_path=_DB_PATH)
    priority_queue = get_priority_queue(limit=5, db_path=_DB_PATH)
    followups_due = get_followup_due(db_path=_DB_PATH)
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "counts": counts,
            "activity": activity,
            "priority_queue": priority_queue,
            "followups_due": followups_due,
            "total": sum(counts.values()),
            "ready": counts.get("ready", 0),
            "scored": counts.get("scored", 0),
            "applied": counts.get("applied", 0),
        },
    )


@app.get("/health")
async def health() -> JSONResponse:
    counts = count_by_status(_DB_PATH)
    return JSONResponse({"status": "ok", "jobs": sum(counts.values()), "counts": counts})


@app.get("/review", response_class=HTMLResponse)
async def review(request: Request) -> HTMLResponse:
    ready_jobs = get_jobs_by_status("ready", _DB_PATH)
    scored_jobs = get_jobs_by_status("scored", _DB_PATH)

    # Attach report text for ready jobs that have a report on disk
    for job in ready_jobs:
        rp = job.get("evaluation_report_path", "")
        job["_report_text"] = Path(rp).read_text(encoding="utf-8") if rp and Path(rp).exists() else ""
        cl = job.get("cover_letter_path", "")
        job["_cover_letter_text"] = Path(cl).read_text(encoding="utf-8") if cl and Path(cl).exists() else ""

    return templates.TemplateResponse(
        request=request,
        name="review.html",
        context={"ready_jobs": ready_jobs, "scored_jobs": scored_jobs},
    )


@app.post("/prepare/{job_id}")
async def prepare_job(job_id: int, request: Request) -> EventSourceResponse:
    """Trigger Stage 2 prepare phase for a job and stream progress via SSE."""

    async def _stream():
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "src.pipeline.orchestrator",
            "--phase", "prepare", "--job-id", str(job_id),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        async for line in proc.stdout:
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                yield {"data": text}
        await proc.wait()
        yield {"data": f"[done] job_id={job_id}"}

    return EventSourceResponse(_stream())


@app.post("/skip/{job_id}")
async def skip_job(job_id: int) -> JSONResponse:
    """Mark a job as skipped."""
    updated = update_job_by_id(job_id, {"status": "skipped"}, _DB_PATH)
    return JSONResponse({"ok": updated})


@app.post("/run")
async def run_pipeline(request: Request) -> EventSourceResponse:
    """Trigger --phase scrape as a background subprocess and stream output via SSE."""

    async def _stream():
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "src.pipeline.orchestrator",
            "--phase", "scrape",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        async for line in proc.stdout:
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                yield {"data": text}
        await proc.wait()
        code = proc.returncode
        yield {"data": f"[done] Exit code: {code}"}

    return EventSourceResponse(_stream())
