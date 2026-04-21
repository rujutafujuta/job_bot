"""FastAPI web app — Slice 1 dashboard + Slice 2 review + Slice 3 apply/outreach."""

from __future__ import annotations

import asyncio
import datetime
import io
import sys
from pathlib import Path

import yaml
import tempfile

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

import threading

from src.contacts.importer import import_linkedin_csv
from src.pipeline.integrity_checker import get_latest_integrity_result
from src.pipeline.priority_scorer import priority_label
from src.tracking.db import (
    add_contact,
    compute_followup_dates,
    count_by_status,
    count_contacts,
    get_applied_jobs,
    get_followup_due,
    get_job_by_id,
    get_jobs_by_status,
    get_pending_outreach,
    get_priority_queue,
    get_recent_activity,
    init_db,
    list_contacts,
    get_scraper_health,
    get_stale_scrapers,
    list_outreach_messages,
    update_job_by_id,
    update_outreach_status,
)
from src.utils.backup import create_backup, restore_backup
from src.utils.config_loader import load_settings, save_settings
from src.pipeline.outreach import migrate_pending_outreach_files

_DB_PATH = Path("data/tracking.db")
_DATA_DIR = Path("data")
_BACKUPS_DIR = Path("backups")
_TEMPLATES_DIR = Path(__file__).parent / "templates"
_PROFILE_PATH = Path("config/user_profile.yaml")
_ROLES_PATH = Path("config/target_roles.yaml")
_CV_PATH = Path("data/cv.md")

app = FastAPI(title="Job Bot")
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

_pipeline_lock = threading.Lock()


@app.on_event("startup")
async def startup() -> None:
    init_db(_DB_PATH)
    migrate_pending_outreach_files(db_path=_DB_PATH)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    counts = count_by_status(_DB_PATH)
    activity = get_recent_activity(limit=10, db_path=_DB_PATH)
    priority_queue = get_priority_queue(db_path=_DB_PATH)
    followups_due = get_followup_due(db_path=_DB_PATH)
    integrity = get_latest_integrity_result()
    stale_scrapers = get_stale_scrapers(threshold_days=3, db_path=_DB_PATH)
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "counts": counts,
            "activity": activity,
            "priority_queue": priority_queue,
            "followups_due": followups_due,
            "priority_label": priority_label,
            "total": sum(counts.values()),
            "ready": counts.get("ready", 0),
            "scored": counts.get("scored", 0),
            "applied": counts.get("applied", 0),
            "integrity": integrity,
            "stale_scrapers": stale_scrapers,
        },
    )


@app.get("/health")
async def health() -> JSONResponse:
    counts = count_by_status(_DB_PATH)
    return JSONResponse({"status": "ok", "jobs": sum(counts.values()), "counts": counts})


@app.get("/stats", response_class=HTMLResponse)
async def stats_fragment(request: Request) -> HTMLResponse:
    """HTMX fragment — returns the stats grid div for auto-refresh."""
    counts = count_by_status(_DB_PATH)
    total = sum(counts.values())
    ready = counts.get("ready", 0)
    scored = counts.get("scored", 0)
    applied = counts.get("applied", 0)
    html = (
        f'<div class="grid grid-4" hx-get="/stats" hx-trigger="every 30s" hx-swap="outerHTML">'
        f'<div class="card stat ready"><div class="number" id="stat-ready">{ready}</div>'
        f'<div class="label">Ready to apply</div></div>'
        f'<div class="card stat scored"><div class="number" id="stat-scored">{scored}</div>'
        f'<div class="label">Scored (70–94)</div></div>'
        f'<div class="card stat applied"><div class="number" id="stat-applied">{applied}</div>'
        f'<div class="label">Applied</div></div>'
        f'<div class="card stat total"><div class="number" id="stat-total">{total}</div>'
        f'<div class="label">Total tracked</div></div>'
        f'</div>'
    )
    return HTMLResponse(html)


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
        context={"ready_jobs": ready_jobs, "scored_jobs": scored_jobs, "priority_label": priority_label},
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


@app.get("/outreach", response_class=HTMLResponse)
async def outreach_page(request: Request) -> HTMLResponse:
    messages = list_outreach_messages(_DB_PATH)
    return templates.TemplateResponse(
        request=request,
        name="outreach.html",
        context={"drafts": messages},
    )


@app.post("/outreach/{message_id}/mark-sent", response_class=HTMLResponse)
async def mark_outreach_sent(message_id: int) -> HTMLResponse:
    """Flip draft → sent; remove card from UI."""
    update_outreach_status(message_id, "sent", _DB_PATH)
    return HTMLResponse("")


@app.post("/outreach/{message_id}/mark-replied", response_class=HTMLResponse)
async def mark_outreach_replied(message_id: int) -> HTMLResponse:
    """Flip sent → replied; update status badge in UI."""
    update_outreach_status(message_id, "replied", _DB_PATH)
    return HTMLResponse(
        f'<span class="status-badge" style="background:#7c3aed;color:#e9d5ff;'
        f'padding:2px 8px;border-radius:4px;font-size:0.75rem">replied</span>'
    )


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


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request) -> HTMLResponse:
    """Render the settings page with current YAML content for editing."""
    profile_text = _PROFILE_PATH.read_text(encoding="utf-8") if _PROFILE_PATH.exists() else ""
    roles_text = _ROLES_PATH.read_text(encoding="utf-8") if _ROLES_PATH.exists() else ""
    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={"profile_text": profile_text, "roles_text": roles_text},
    )


@app.post("/settings/profile", response_class=HTMLResponse)
async def save_profile(request: Request, content: str = Form(...)) -> HTMLResponse:
    """Save updated user_profile.yaml. Returns 400 on invalid YAML."""
    try:
        yaml.safe_load(content)
    except yaml.YAMLError as exc:
        return HTMLResponse(f"Invalid YAML: {exc}", status_code=400)
    _PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if _PROFILE_PATH.exists():
        _PROFILE_PATH.with_suffix(".yaml.bak").write_bytes(_PROFILE_PATH.read_bytes())
    _PROFILE_PATH.write_text(content, encoding="utf-8")
    return HTMLResponse('<p class="text-muted" style="color:#4ade80">Profile saved.</p>')


@app.post("/settings/roles", response_class=HTMLResponse)
async def save_roles(request: Request, content: str = Form(...)) -> HTMLResponse:
    """Save updated target_roles.yaml. Returns 400 on invalid YAML."""
    try:
        yaml.safe_load(content)
    except yaml.YAMLError as exc:
        return HTMLResponse(f"Invalid YAML: {exc}", status_code=400)
    _ROLES_PATH.parent.mkdir(parents=True, exist_ok=True)
    if _ROLES_PATH.exists():
        _ROLES_PATH.with_suffix(".yaml.bak").write_bytes(_ROLES_PATH.read_bytes())
    _ROLES_PATH.write_text(content, encoding="utf-8")
    return HTMLResponse('<p class="text-muted" style="color:#4ade80">Roles saved.</p>')


@app.get("/settings/contacts", response_class=HTMLResponse)
async def contacts_fragment(request: Request) -> HTMLResponse:
    contacts = list_contacts(_DB_PATH)
    total = count_contacts(_DB_PATH)
    rows = "".join(
        f"<tr><td>{c['name']}</td><td>{c['company']}</td><td>{c.get('title','')}</td>"
        f"<td style='color:#666;font-size:0.8rem'>{c.get('source','manual')}</td></tr>"
        for c in contacts
    )
    table = (
        f"<p style='color:#888;font-size:0.85rem'>{total} contact(s) loaded.</p>"
        + (
            f"<table><thead><tr><th>Name</th><th>Company</th><th>Title</th><th>Source</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
            if contacts
            else ""
        )
    )
    return HTMLResponse(table)


@app.post("/settings/contacts/import", response_class=HTMLResponse)
async def import_contacts(csv_file: UploadFile = File(...)) -> HTMLResponse:
    """Import LinkedIn Connections.csv and upsert into contacts table."""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
            tmp.write(await csv_file.read())
            tmp_path = Path(tmp.name)
        count = import_linkedin_csv(tmp_path, _DB_PATH)
        tmp_path.unlink(missing_ok=True)
        total = count_contacts(_DB_PATH)
        return HTMLResponse(
            f'<p style="color:#4ade80">Imported {count} contact(s). Total: {total}.</p>',
            status_code=200,
        )
    except Exception as exc:
        return HTMLResponse(f'<p style="color:#f87171">Import failed: {exc}</p>', status_code=400)


@app.post("/settings/contacts/add", response_class=HTMLResponse)
async def add_contact_manual(
    name: str = Form(...),
    company: str = Form(...),
    title: str = Form(""),
) -> HTMLResponse:
    """Manually add a single contact."""
    if not name.strip() or not company.strip():
        return HTMLResponse('<p style="color:#f87171">Name and company are required.</p>', status_code=400)
    add_contact(name=name.strip(), company=company.strip(), title=title.strip(), source="manual", db_path=_DB_PATH)
    total = count_contacts(_DB_PATH)
    return HTMLResponse(
        f'<p style="color:#4ade80">Contact added. Total: {total}.</p>',
        status_code=200,
    )


@app.post("/settings/rejection-analysis")
async def rejection_analysis(request: Request) -> EventSourceResponse:
    """Run rejection analysis and stream output."""
    from src.pipeline.rejection_analyzer import run_rejection_analysis

    async def _stream():
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-c",
                (
                    "from src.pipeline.rejection_analyzer import run_rejection_analysis; "
                    "p = run_rejection_analysis(); print(f'[done] Report written to {p}')"
                ),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            async for line in proc.stdout:
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    yield {"data": text}
            await proc.wait()
        except Exception as exc:
            yield {"data": f"[error] {exc}"}

    return EventSourceResponse(_stream())


@app.get("/settings/regenerate-roles")
async def regenerate_roles_status(request: Request) -> HTMLResponse:
    """Return CV-changed banner if cv.md is newer than target_roles.yaml."""
    cv_newer = _CV_PATH.exists() and (
        not _ROLES_PATH.exists()
        or _CV_PATH.stat().st_mtime > _ROLES_PATH.stat().st_mtime
    )
    if cv_newer:
        return HTMLResponse(
            '<div id="cv-banner" style="background:#422006;border:1px solid #78350f;'
            'border-radius:6px;padding:12px 16px;margin-bottom:16px;color:#fbbf24">'
            '⚠ cv.md was updated after target_roles.yaml — roles may be stale. '
            '<button hx-post="/settings/regenerate-roles" hx-target="#cv-banner" '
            'hx-swap="outerHTML" class="btn btn-primary" style="margin-left:12px;font-size:0.82rem">'
            'Regenerate Roles</button></div>'
        )
    return HTMLResponse('<div id="cv-banner"></div>')


@app.post("/settings/regenerate-roles")
async def regenerate_roles(request: Request) -> EventSourceResponse:
    """Trigger --phase roles regeneration and stream output."""

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
        yield {"data": "[done] Roles regenerated."}

    return EventSourceResponse(_stream())


@app.get("/settings/scraper-toggles", response_class=HTMLResponse)
async def scraper_toggles_fragment(request: Request) -> HTMLResponse:
    """Return scraper toggle checkboxes as an HTMX fragment."""
    settings = load_settings()
    toggles = settings.get("scrapers", {})
    scraper_names = ["apify", "himalayas", "remotive", "remoteok", "simplify", "adzuna", "jobicy"]
    checkboxes = "".join(
        f'<label style="display:flex;align-items:center;gap:8px;margin-bottom:8px;cursor:pointer">'
        f'<input type="checkbox" name="scrapers[]" value="{name}" '
        f'{"checked" if toggles.get(name, True) else ""}> {name}</label>'
        for name in scraper_names
    )
    return HTMLResponse(
        f'<form hx-post="/settings/scraper-toggles" hx-target="#scraper-status" hx-swap="innerHTML">'
        f'{checkboxes}'
        f'<button type="submit" class="btn btn-primary" style="margin-top:8px">Save Toggles</button>'
        f'</form>'
        f'<div id="scraper-status" style="min-height:1.4em;margin-top:8px;font-size:0.85rem"></div>'
    )


@app.post("/settings/scraper-toggles", response_class=HTMLResponse)
async def save_scraper_toggles(request: Request) -> HTMLResponse:
    """Save scraper enable/disable toggles to config/settings.yaml."""
    form = await request.form()
    enabled = set(form.getlist("scrapers[]"))
    scraper_names = ["apify", "himalayas", "remotive", "remoteok", "simplify", "adzuna", "jobicy"]
    settings = load_settings()
    settings["scrapers"] = {name: (name in enabled) for name in scraper_names}
    save_settings(settings)
    return HTMLResponse('<p style="color:#4ade80">Scraper settings saved.</p>')


@app.get("/settings/scraper-health", response_class=HTMLResponse)
async def scraper_health_fragment(request: Request) -> HTMLResponse:
    """HTMX fragment — scraper health table for settings page."""
    health = get_scraper_health(db_path=_DB_PATH)
    if not health:
        return HTMLResponse(
            '<p style="color:#555;font-size:0.85rem">No scraper runs recorded yet. '
            'Run the pipeline first.</p>'
        )

    rows = "".join(
        f"<tr>"
        f"<td style='padding:6px 12px'>{r['source']}</td>"
        f"<td style='padding:6px 12px;color:#9ca3af'>{r['last_run_date'][:10] if r['last_run_date'] else '—'}</td>"
        f"<td style='padding:6px 12px;text-align:center'>{r['last_jobs_found']}</td>"
        f"<td style='padding:6px 12px;text-align:center;"
        f"{'color:#f87171' if r['consecutive_zero_days'] >= 3 else 'color:#4ade80'}'>"
        f"{r['consecutive_zero_days']}</td>"
        f"<td style='padding:6px 12px;color:#6b7280;font-size:0.8rem'>{r['last_error'] or '—'}</td>"
        f"</tr>"
        for r in health
    )
    return HTMLResponse(
        f'<table style="width:100%;border-collapse:collapse;font-size:0.85rem">'
        f'<thead><tr style="border-bottom:1px solid #333;color:#6b7280">'
        f'<th style="padding:6px 12px;text-align:left">Source</th>'
        f'<th style="padding:6px 12px;text-align:left">Last Run</th>'
        f'<th style="padding:6px 12px;text-align:center">Last Found</th>'
        f'<th style="padding:6px 12px;text-align:center">Consec. Zeros</th>'
        f'<th style="padding:6px 12px;text-align:left">Last Error</th>'
        f'</tr></thead><tbody>{rows}</tbody></table>'
    )


@app.post("/settings/backup", response_class=HTMLResponse)
async def create_backup_route(request: Request) -> HTMLResponse:
    """Create a backup zip of the database and data directory."""
    try:
        zip_path = create_backup(db_path=_DB_PATH, data_dir=_DATA_DIR, backups_dir=_BACKUPS_DIR)
        filename = zip_path.name
        return HTMLResponse(
            f'<p style="color:#4ade80">Backup created: '
            f'<a href="/settings/backup/download/{filename}" '
            f'style="color:#60a5fa">{filename}</a></p>'
        )
    except Exception as exc:
        return HTMLResponse(f'<p style="color:#f87171">Backup failed: {exc}</p>')


@app.get("/settings/backup/download/{filename}")
async def download_backup(filename: str):
    """Serve a backup zip file for download."""
    zip_path = _BACKUPS_DIR / filename
    if not zip_path.exists() or zip_path.suffix != ".zip":
        return HTMLResponse("Not found", status_code=404)
    return StreamingResponse(
        iter([zip_path.read_bytes()]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/settings/restore", response_class=HTMLResponse)
async def restore_backup_route(backup_file: UploadFile = File(...)) -> HTMLResponse:
    """Restore from an uploaded backup zip — replaces db and data/ in-place."""
    if not backup_file.filename or not backup_file.filename.endswith(".zip"):
        return HTMLResponse('<p style="color:#f87171">Upload a .zip backup file.</p>')
    try:
        content = await backup_file.read()
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        restore_backup(zip_path=tmp_path, db_path=_DB_PATH, data_dir=_DATA_DIR)
        tmp_path.unlink(missing_ok=True)
        return HTMLResponse('<p style="color:#4ade80">Restore complete. Restart the server to apply changes.</p>')
    except Exception as exc:
        return HTMLResponse(f'<p style="color:#f87171">Restore failed: {exc}</p>')


@app.post("/settings/upload-cv", response_class=HTMLResponse)
async def upload_cv_route(cv_file: UploadFile = File(...)) -> HTMLResponse:
    """Replace data/cv.md with the uploaded Markdown file."""
    if not cv_file.filename or not cv_file.filename.endswith(".md"):
        return HTMLResponse('<p style="color:#f87171">Please upload a .md (Markdown) file.</p>')
    try:
        content = await cv_file.read()
        _CV_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CV_PATH.write_bytes(content)
        import datetime
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        return HTMLResponse(
            f'<p style="color:#4ade80">CV uploaded successfully ({ts}). '
            f"Run <em>Regenerate Roles</em> to update target_roles.yaml.</p>"
        )
    except Exception as exc:
        return HTMLResponse(f'<p style="color:#f87171">Upload failed: {exc}</p>')


@app.get("/settings/cv-status", response_class=HTMLResponse)
async def cv_status_route() -> HTMLResponse:
    """Return current CV status snippet for HTMX polling."""
    if _CV_PATH.exists():
        import datetime
        mtime = datetime.datetime.fromtimestamp(_CV_PATH.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        return HTMLResponse(
            f'<span style="color:#4ade80">data/cv.md — last modified {mtime}</span>'
        )
    return HTMLResponse('<span style="color:#64748b">No CV uploaded yet.</span>')


@app.post("/run")
async def run_pipeline(request: Request) -> EventSourceResponse:
    """Trigger --phase scrape as a background subprocess and stream output via SSE."""

    async def _stream():
        if not _pipeline_lock.acquire(blocking=False):
            yield {"data": "[error] Pipeline already running — wait for it to finish"}
            return

        try:
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
        finally:
            _pipeline_lock.release()

    return EventSourceResponse(_stream())
