"""
Pipeline orchestrator — wires all phases together.

Usage:
    python -m src.pipeline.orchestrator --phase scrape
    python -m src.pipeline.orchestrator --phase scrape --dry-run
    python -m src.pipeline.orchestrator --phase prepare --job-id 42
    python -m src.pipeline.orchestrator --phase apply --job-id 42   (Slice 3 stub)
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from src.pipeline.applicator import apply_to_job
from src.pipeline.contact_finder import find_contact
from src.pipeline.cover_letter import generate_cover_letter
from src.pipeline.liveness import check_liveness
from src.pipeline.outreach import send_cold_outreach
from src.pipeline.pdf_generator import generate_pdf
from src.pipeline.priority_scorer import compute_priority
from src.pipeline.resume_tailor import tailor_resume
from src.pipeline.role_detector import generate_roles, needs_regeneration
from src.pipeline.scraper import run_scrapers
from src.pipeline.stage1_scorer import Stage1Result, route_job, score_job
from src.pipeline.stage2_evaluator import evaluate_job
from src.scrapers.base import JobPosting
from src.tracking.db import (
    compute_followup_dates,
    count_by_status,
    get_job_by_id,
    get_jobs_by_status,
    init_db,
    mark_ghosted_jobs,
    update_job,
    update_job_by_id,
)
from src.tracking.deduplication import is_duplicate, is_fuzzy_duplicate
from src.utils.config_loader import load_env, load_profile, validate_env
from src.utils.scheduler import build_schtasks_command

_DEFAULT_DB = Path("data/tracking.db")
_DEFAULT_PROFILE = Path("config/user_profile.yaml")
_DEFAULT_ROLES = Path("config/target_roles.yaml")
_DEFAULT_CV = Path("data/cv.md")


def run_scrape_phase(
    roles_path: Path = _DEFAULT_ROLES,
    profile_path: Path = _DEFAULT_PROFILE,
    cv_path: Path = _DEFAULT_CV,
    db_path: Path = _DEFAULT_DB,
    dry_run: bool = False,
) -> dict:
    """
    Full automated scrape phase:
      1. Regenerate target_roles.yaml if cv.md changed
      2. Scrape all sources
      3. Deduplicate against DB
      4. Stage 1 score each new job
      5. Route by score: <70 → discard, 70-94 → scored, 95+ → ready + trigger Stage 2
      6. Run liveness check on all existing unacted jobs
    """
    if not dry_run:
        init_db(db_path)

    # Step 1 — role detection
    if needs_regeneration(cv_path, roles_path):
        if cv_path.exists():
            print("[orchestrator] cv.md changed — regenerating target_roles.yaml")
            if not dry_run:
                generate_roles(cv_path, roles_path, dry_run=False, force=True)
            else:
                print("[orchestrator] (dry-run) would regenerate target_roles.yaml")
        else:
            print(f"[orchestrator] Warning: {cv_path} not found — skipping role regeneration")

    # Step 2 — scrape
    print("\n[orchestrator] Phase 1: Scraping")
    postings = run_scrapers(roles_path=roles_path, db_path=db_path, dry_run=dry_run)
    print(f"[orchestrator] {len(postings)} new postings to evaluate")

    if not postings:
        if not dry_run:
            _run_liveness(db_path)
        _print_summary(0, 0, 0, 0, dry_run)
        return {"scored": 0, "ready": 0, "discarded": 0, "skipped_duplicate": 0}

    # Step 3/4/5 — dedup + score + route
    profile = load_profile(profile_path)
    print("\n[orchestrator] Phase 2: Scoring")

    n_scored = n_ready = n_discarded = n_dup = 0
    ready_job_ids: list[int] = []

    for posting in postings:
        if is_duplicate(posting.title, posting.company, db_path) or \
                is_fuzzy_duplicate(posting.title, posting.company, db_path):
            n_dup += 1
            continue

        result: Stage1Result = score_job(posting, profile)
        print(
            f"[orchestrator] {posting.company} / {posting.title}: "
            f"score={result.score} — {result.reasoning[:60]}"
        )

        if dry_run:
            if result.score >= 95:
                n_ready += 1
            elif result.score >= 70:
                n_scored += 1
            else:
                n_discarded += 1
            continue

        action = route_job(result, posting, db_path)
        if action == "ready":
            n_ready += 1
            # Collect id for Stage 2 auto-trigger
            from src.tracking.db import get_job
            job = get_job(posting.url, db_path)
            if job:
                ready_job_ids.append(job["id"])
        elif action == "scored":
            n_scored += 1
        else:
            n_discarded += 1

    # Step 6 — auto-trigger Stage 2 for 95+ jobs
    if not dry_run and ready_job_ids:
        print(f"\n[orchestrator] Phase 3: Stage 2 evaluation for {len(ready_job_ids)} ready job(s)")
        for job_id in ready_job_ids:
            try:
                run_prepare_phase(
                    job_id=job_id,
                    db_path=db_path,
                    profile_path=profile_path,
                    cv_path=cv_path,
                )
            except Exception as e:
                print(f"[orchestrator] Stage 2 failed for job {job_id}: {e}")

    # Step 7 — liveness check
    if not dry_run:
        _run_liveness(db_path)

    _print_summary(n_scored, n_ready, n_discarded, n_dup, dry_run)
    return {
        "scored": n_scored,
        "ready": n_ready,
        "discarded": n_discarded,
        "skipped_duplicate": n_dup,
    }


def run_prepare_phase(
    job_id: int,
    db_path: Path = _DEFAULT_DB,
    profile_path: Path = _DEFAULT_PROFILE,
    cv_path: Path = _DEFAULT_CV,
) -> None:
    """
    On-demand Stage 2 preparation for a single job:
      1. Stage 2 deep evaluation (6-block Claude report)
      2. Resume tailoring from Block E
      3. Cover letter generation
      4. PDF generation
      5. Priority score computation
      6. status → ready
    """
    job = get_job_by_id(job_id, db_path)
    if not job:
        raise ValueError(f"Job id={job_id} not found in database")

    profile = load_profile(profile_path)

    print(f"[orchestrator] Stage 2: {job['company']} / {job['title']}")

    # Stage 2 evaluation
    stage2 = evaluate_job(job=job, cv_path=cv_path, profile=profile)
    if stage2.error:
        print(f"[orchestrator] Stage 2 error for job {job_id}: {stage2.error}")

    # Resume tailoring
    evaluation_text = (
        stage2.report_path.read_text(encoding="utf-8")
        if stage2.report_path.exists()
        else ""
    )
    resume_md_path = tailor_resume(
        job=job,
        evaluation_report=evaluation_text,
        cv_path=cv_path,
    )

    # PDF generation
    resume_pdf_path = resume_md_path.with_suffix(".pdf")
    try:
        generate_pdf(resume_md_path, resume_pdf_path)
    except Exception as e:
        print(f"[orchestrator] PDF generation failed for job {job_id}: {e}")
        resume_pdf_path = resume_md_path  # fall back to .md path

    # Cover letter
    tailored_text = resume_md_path.read_text(encoding="utf-8") if resume_md_path.exists() else ""
    cover_letter_path = generate_cover_letter(
        job=job,
        evaluation_report=evaluation_text,
        tailored_resume=tailored_text,
        profile=profile,
    )

    # Priority score
    updated_fields = {
        "stage2_score": stage2.score,
        "evaluation_report_path": str(stage2.report_path),
        "tailored_resume_path": str(resume_pdf_path),
        "cover_letter_path": str(cover_letter_path),
        "status": "ready",
    }

    # Recompute priority with stage2 score
    merged = {**job, **updated_fields}
    updated_fields["priority_score"] = compute_priority(merged)

    update_job_by_id(job_id, updated_fields, db_path)
    print(
        f"[orchestrator] Prepared job {job_id}: score={stage2.score}, "
        f"legitimacy={stage2.legitimacy}, priority={updated_fields['priority_score']}"
    )


def run_apply_phase(
    job_id: int,
    db_path: Path = _DEFAULT_DB,
    profile_path: Path = _DEFAULT_PROFILE,
    dry_run: bool = False,
) -> dict:
    """
    Apply to a single job:
      1. Open browser (Playwright, headless=False) — user fills/submits
      2. Find hiring manager contact
      3. Generate and save cold outreach draft
      4. Write applied_date + follow-up cadence + outreach_draft_path to DB
      5. status → applied (or manual_pending if ATS unsupported)
    """
    job = get_job_by_id(job_id, db_path)
    if not job:
        raise ValueError(f"Job id={job_id} not found in database")

    profile = load_profile(profile_path)

    posting = JobPosting(
        title=job["title"],
        company=job["company"],
        location=job.get("location", ""),
        url=job["url"],
        description=job.get("description", ""),
        source=job.get("source", ""),
        date_posted=job.get("date_posted", ""),
        remote=bool(job.get("remote", 0)),
    )

    pdf_resume = Path(job.get("tailored_resume_path") or "")
    cover_letter = Path(job.get("cover_letter_path") or "")

    print(f"[orchestrator] Apply: {job['company']} / {job['title']}")

    # Step 1 — open browser, auto-fill, user submits
    apply_result = apply_to_job(
        posting=posting,
        profile=profile,
        pdf_resume=pdf_resume if pdf_resume.exists() else Path("data/cv.md"),
        cover_letter=cover_letter if cover_letter.exists() else None,
        dry_run=dry_run,
    )
    print(f"[orchestrator] Apply result: submitted={apply_result['submitted']}")

    # Step 2 — find contact
    contact = find_contact(posting.company, posting.url)
    print(f"[orchestrator] Contact found: {contact.found} — {contact.name or 'none'}")

    # Step 3 — outreach draft
    outreach_result = send_cold_outreach(
        posting=posting,
        contact=contact,
        profile=profile,
        pdf_resume=pdf_resume if pdf_resume.exists() else Path("data/cv.md"),
        dry_run=dry_run,
    )
    print(f"[orchestrator] Outreach: {outreach_result['status']}")

    # Step 4 — update DB
    applied_date = date.today().isoformat()
    f1, f2, ghosted = compute_followup_dates(applied_date)

    new_status = "applied" if apply_result["submitted"] else "ready"
    fields: dict = {
        "follow_up_1_date": f1,
        "follow_up_2_date": f2,
        "ghosted_date": ghosted,
        "outreach_status": outreach_result["status"],
    }
    if apply_result["submitted"]:
        fields["applied_date"] = applied_date
        fields["status"] = "applied"

    draft_path = _get_latest_draft(posting.company)
    if draft_path:
        fields["outreach_draft_path"] = str(draft_path)

    if not dry_run:
        update_job_by_id(job_id, fields, db_path)

    return {
        "submitted": apply_result["submitted"],
        "outreach_status": outreach_result["status"],
        "applied_date": applied_date if apply_result["submitted"] else "",
    }


def _get_latest_draft(company: str) -> Path | None:
    """Return the most recently created draft file for a company, if any."""
    import re
    pending_dir = Path("data/pending_outreach")
    if not pending_dir.exists():
        return None
    slug = re.sub(r"[^\w]", "_", company.lower())
    matches = sorted(pending_dir.glob(f"{slug}_*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def run_followup_phase(db_path: Path = _DEFAULT_DB) -> int:
    """
    Auto-mark applied jobs as ghosted when their 30-day ghosted_date has passed.

    Returns:
        Number of jobs marked ghosted.
    """
    count = mark_ghosted_jobs(db_path)
    print(f"[orchestrator] Follow-up check: {count} job(s) marked ghosted")
    return count


def _run_liveness(db_path: Path) -> None:
    print("\n[orchestrator] Phase 4: Liveness check")
    result = check_liveness(db_path)
    print(f"[orchestrator] Liveness: {result['checked']} checked, {result['killed']} killed")


def _print_summary(
    scored: int, ready: int, discarded: int, skipped: int, dry_run: bool
) -> None:
    label = "(DRY RUN) " if dry_run else ""
    print(f"\n{'='*60}")
    print(f"  Pipeline {label}complete — {date.today()}")
    print(f"  Ready (95+):      {ready}")
    print(f"  Scored (70-94):   {scored}")
    print(f"  Discarded (<70):  {discarded}")
    print(f"  Already seen:     {skipped}")
    print(f"{'='*60}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Job Bot Pipeline")
    parser.add_argument(
        "--phase",
        choices=["scrape", "prepare", "apply", "followup"],
        default="scrape",
    )
    parser.add_argument("--job-id", type=int, help="Job ID (required for prepare/apply)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--schedule",
        type=int,
        metavar="HOURS",
        help="Register a Windows Task Scheduler job to run --phase scrape every N hours",
    )
    parser.add_argument("--db", default=str(_DEFAULT_DB))
    parser.add_argument("--profile", default=str(_DEFAULT_PROFILE))
    parser.add_argument("--roles", default=str(_DEFAULT_ROLES))
    parser.add_argument("--cv", default=str(_DEFAULT_CV))
    args = parser.parse_args()

    load_env()
    validate_env()

    if args.schedule is not None:
        import subprocess
        cmd = build_schtasks_command(args.schedule)
        print(f"[orchestrator] Registering scheduled task (every {args.schedule}h)...")
        print(f"[orchestrator] {cmd}")
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            print("[orchestrator] Task registered. Run 'schtasks /Query /TN \"JobBot Scrape\"' to verify.")
        else:
            print(f"[orchestrator] schtasks failed: {result.stderr.strip()}")
            sys.exit(1)
        sys.exit(0)

    if args.phase == "scrape":
        run_scrape_phase(
            roles_path=Path(args.roles),
            profile_path=Path(args.profile),
            cv_path=Path(args.cv),
            db_path=Path(args.db),
            dry_run=args.dry_run,
        )
    elif args.phase == "prepare":
        if not args.job_id:
            parser.error("--job-id required for --phase prepare")
        run_prepare_phase(
            job_id=args.job_id,
            db_path=Path(args.db),
            profile_path=Path(args.profile),
            cv_path=Path(args.cv),
        )
    elif args.phase == "apply":
        if not args.job_id:
            parser.error("--job-id required for --phase apply")
        run_apply_phase(
            job_id=args.job_id,
            db_path=Path(args.db),
            profile_path=Path(args.profile),
            dry_run=args.dry_run,
        )
    elif args.phase == "followup":
        run_followup_phase(db_path=Path(args.db))
    else:
        parser.error(f"Unknown phase: {args.phase}")


if __name__ == "__main__":
    main()
