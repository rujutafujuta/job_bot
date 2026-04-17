"""FastAPI web app — Slice 1 minimal dashboard."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

from src.tracking.db import count_by_status, get_recent_activity, init_db

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
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "counts": counts,
            "activity": activity,
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
