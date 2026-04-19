"""Integrity checker — validates DB consistency and asset availability after each scrape."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from src.tracking.db import VALID_STATUSES, _DEFAULT_DB, get_all_jobs

_LOGS_DIR = Path("data/logs")


def run_integrity_check(db_path: Path = _DEFAULT_DB) -> dict:
    """
    Validate database consistency and return a results dict.

    Checks:
      1. All status values are in VALID_STATUSES
      2. No duplicate active dedup_hashes among scored/ready/applied jobs
      3. All 'ready' jobs have evaluation_report_path and tailored_resume_path on disk
      4. Applied jobs all have follow-up dates computed

    Returns:
        {
          "passed": bool,
          "failures": list[str],
          "warnings": list[str],
          "log_path": Path,
        }
    """
    jobs = get_all_jobs(db_path)
    failures: list[str] = []
    warnings: list[str] = []

    # 1 — status enum
    for job in jobs:
        if job["status"] not in VALID_STATUSES:
            failures.append(
                f"Job id={job['id']} ({job['company']}/{job['title']}) "
                f"has invalid status '{job['status']}'"
            )

    # 2 — duplicate active hashes
    active_statuses = {"scored", "ready", "applied", "phone_screen", "technical",
                       "offer", "negotiating"}
    active_hashes: dict[str, list[int]] = {}
    for job in jobs:
        if job["status"] in active_statuses and job.get("dedup_hash"):
            active_hashes.setdefault(job["dedup_hash"], []).append(job["id"])
    for h, ids in active_hashes.items():
        if len(ids) > 1:
            failures.append(
                f"Duplicate active dedup_hash '{h[:16]}…' across job IDs: {ids}"
            )

    # 3 — ready jobs have assets on disk
    for job in jobs:
        if job["status"] != "ready":
            continue
        report = job.get("evaluation_report_path", "")
        resume = job.get("tailored_resume_path", "")
        if not report or not Path(report).exists():
            warnings.append(
                f"Job id={job['id']} ({job['company']}/{job['title']}) "
                f"is 'ready' but missing evaluation report"
            )
        if not resume or not Path(resume).exists():
            warnings.append(
                f"Job id={job['id']} ({job['company']}/{job['title']}) "
                f"is 'ready' but missing tailored resume"
            )

    # 4 — applied jobs have follow-up dates
    for job in jobs:
        if job["status"] not in {"applied", "phone_screen", "technical"}:
            continue
        if job.get("applied_date") and not job.get("follow_up_1_date"):
            warnings.append(
                f"Job id={job['id']} ({job['company']}/{job['title']}) "
                f"is applied but missing follow-up dates"
            )

    passed = len(failures) == 0
    log_path = _write_log(failures, warnings)

    return {
        "passed": passed,
        "failures": failures,
        "warnings": warnings,
        "log_path": log_path,
    }


def _write_log(failures: list[str], warnings: list[str]) -> Path:
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = _LOGS_DIR / f"integrity_{date.today().isoformat()}.log"

    lines = [f"Integrity check — {date.today().isoformat()}"]
    lines.append("=" * 60)

    if failures:
        lines.append(f"\nFAILURES ({len(failures)}):")
        for f in failures:
            lines.append(f"  [FAIL] {f}")
    else:
        lines.append("\nNo failures.")

    if warnings:
        lines.append(f"\nWARNINGS ({len(warnings)}):")
        for w in warnings:
            lines.append(f"  [WARN] {w}")
    else:
        lines.append("\nNo warnings.")

    lines.append(f"\nResult: {'PASSED' if not failures else 'FAILED'}")
    log_path.write_text("\n".join(lines), encoding="utf-8")
    return log_path


def get_latest_integrity_result() -> dict | None:
    """
    Return summary from the most recent integrity log, or None if no log exists.

    Returns dict with keys: passed, failure_count, warning_count, log_path, date.
    """
    if not _LOGS_DIR.exists():
        return None
    logs = sorted(_LOGS_DIR.glob("integrity_*.log"), reverse=True)
    if not logs:
        return None

    log_path = logs[0]
    content = log_path.read_text(encoding="utf-8")
    failure_count = content.count("[FAIL]")
    warning_count = content.count("[WARN]")

    return {
        "passed": failure_count == 0,
        "failure_count": failure_count,
        "warning_count": warning_count,
        "log_path": log_path,
        "date": log_path.stem.replace("integrity_", ""),
    }
