"""FastAPI web app — Slice 1 dashboard + Slice 2 review + Slice 3 apply/outreach."""

from __future__ import annotations

import asyncio
import datetime
import io
import sys
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

from src.tracking.db import (
    compute_followup_dates,
    count_by_status,
    get_applied_jobs,
    get_followup_due,
    get_job_by_id,
    get_jobs_by_status,
    get_pending_outreach,
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


@app.get("/applied", response_class=HTMLResponse)
async def applied(request: Request) -> HTMLResponse:
    jobs = get_applied_jobs(_DB_PATH)
    today = datetime.date.today().isoformat()
    return templates.TemplateResponse(
        request=request,
        name="applied.html",
        context={"jobs": jobs, "today": today},
    )


@app.patch("/jobs/{job_id}/status", response_class=HTMLResponse)
async def update_job_status(job_id: int, request: Request) -> HTMLResponse:
    """HTMX endpoint — updates job status and returns a new badge span."""
    form = await request.form()
    status = form.get("status", "")
    update_job_by_id(job_id, {"status": status}, _DB_PATH)
    badge_html = f'<span class="badge badge-{status}">{status.replace("_", " ")}</span>'
    return HTMLResponse(badge_html)


@app.get("/applied/export")
async def export_applied() -> StreamingResponse:
    """Download applied jobs as an Excel file."""
    import openpyxl

    jobs = get_applied_jobs(_DB_PATH)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Applied Jobs"

    columns = ["company", "title", "status", "applied_date", "follow_up_1_date",
               "follow_up_2_date", "ghosted_date", "url", "notes"]
    ws.append(columns)
    for job in jobs:
        ws.append([job.get(c, "") for c in columns])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f"applied_{datetime.date.today().isoformat()}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


_PENDING_DIR = Path("data/pending_outreach")


def _parse_draft_file(path: Path) -> dict:
    """Parse a pending outreach draft text file into a structured dict."""
    lines = path.read_text(encoding="utf-8").splitlines()
    meta = {}
    body_lines = []
    past_sep = False
    for line in lines:
        if line == "---":
            past_sep = True
            continue
        if past_sep:
            body_lines.append(line)
        else:
            if line.startswith("TO:"):
                meta["to_email"] = line[3:].strip()
            elif line.startswith("LINKEDIN:"):
                meta["linkedin_url"] = line[9:].strip()
            elif line.startswith("CONTACT:"):
                meta["contact_name"] = line[8:].strip()
            elif line.startswith("SUBJECT:"):
                meta["subject"] = line[8:].strip()
            elif line.startswith("RESUME:"):
                meta["resume_path"] = line[7:].strip()
    meta["body"] = "\n".join(body_lines).strip()
    meta["filename"] = path.name
    return meta


@app.get("/outreach", response_class=HTMLResponse)
async def outreach_page(request: Request) -> HTMLResponse:
    drafts = []
    if _PENDING_DIR.exists():
        for txt_file in sorted(_PENDING_DIR.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True):
            draft = _parse_draft_file(txt_file)
            # Derive company/title from filename (company_slug_TIMESTAMP.txt)
            parts = txt_file.stem.rsplit("_", 2)
            draft["company"] = parts[0].replace("_", " ") if parts else ""
            draft["title"] = ""
            drafts.append(draft)

    # Enrich from DB to get job title
    db_pending = get_pending_outreach(_DB_PATH)
    draft_lookup = {d["filename"]: d for d in drafts}
    for job in db_pending:
        fname = Path(job.get("outreach_draft_path", "")).name
        if fname in draft_lookup:
            draft_lookup[fname]["title"] = job.get("title", "")
            draft_lookup[fname]["company"] = job.get("company", draft_lookup[fname]["company"])

    return templates.TemplateResponse(
        request=request,
        name="outreach.html",
        context={"drafts": drafts},
    )


@app.post("/outreach/{filename}/send", response_class=HTMLResponse)
async def mark_outreach_sent(filename: str) -> HTMLResponse:
    """Mark a draft as sent — updates DB and returns empty string (removes card)."""
    db_pending = get_pending_outreach(_DB_PATH)
    for job in db_pending:
        if Path(job.get("outreach_draft_path", "")).name == filename:
            update_job_by_id(job["id"], {"outreach_status": "sent"}, _DB_PATH)
            break
    return HTMLResponse("")


@app.delete("/outreach/{filename}", response_class=HTMLResponse)
async def delete_outreach_draft(filename: str) -> HTMLResponse:
    """Delete a pending outreach draft file and clear the DB path."""
    safe_name = Path(filename).name  # prevent path traversal
    draft_path = _PENDING_DIR / safe_name
    if draft_path.exists():
        draft_path.unlink()

    db_pending = get_pending_outreach(_DB_PATH)
    for job in db_pending:
        if Path(job.get("outreach_draft_path", "")).name == safe_name:
            update_job_by_id(job["id"], {"outreach_draft_path": "", "outreach_status": "none"}, _DB_PATH)
            break
    return HTMLResponse("")


@app.post("/apply/{job_id}")
async def apply_job(job_id: int, request: Request) -> EventSourceResponse:
    """Trigger apply phase for a job — streams progress, opens visible browser."""

    async def _stream():
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "src.pipeline.orchestrator",
            "--phase", "apply", "--job-id", str(job_id),
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
