"""
URL liveness checker — detects dead job postings and marks them discarded.

Runs at the end of every scrape phase against all scored+ready jobs.
Only checks URLs the user hasn't acted on yet.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import requests

from src.tracking.db import _DEFAULT_DB, get_jobs_by_statuses, update_job

_ACTIVE_STATUSES = ["scored", "ready"]
_DEAD_CODES = {404, 410}
_TIMEOUT = 10


def _is_dead(url: str) -> bool:
    """Return True if the URL is unreachable or returns a dead-link status code."""
    try:
        resp = requests.head(url, timeout=_TIMEOUT, allow_redirects=True)
        return resp.status_code in _DEAD_CODES
    except requests.RequestException:
        return True


def check_liveness(db_path: Path = _DEFAULT_DB) -> dict:
    """
    Check URL liveness for all scored and ready jobs.

    Dead links → status=discarded with a note recording the reason and date.
    Returns {checked: int, killed: int}.
    """
    jobs = get_jobs_by_statuses(_ACTIVE_STATUSES, db_path)
    checked = 0
    killed = 0

    for job in jobs:
        url = job.get("url", "")
        if not url:
            continue
        checked += 1
        if _is_dead(url):
            update_job(
                url,
                {
                    "status": "discarded",
                    "notes": f"Application closed — URL unreachable on {date.today().isoformat()}",
                },
                db_path,
            )
            killed += 1

    return {"checked": checked, "killed": killed}
