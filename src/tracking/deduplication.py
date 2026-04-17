"""Job deduplication — title+company SHA-256 hash checked against SQLite tables."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from src.tracking.db import _DEFAULT_DB, is_discarded, is_seen, insert_job, mark_discarded


def normalize(title: str, company: str) -> str:
    """
    Produce a canonical string for hashing.

    Lowercases, strips punctuation, collapses whitespace, concatenates title + company.
    """
    def _clean(s: str) -> str:
        s = s.lower()
        s = re.sub(r"[^\w\s]", " ", s)   # replace punctuation with space
        s = re.sub(r"\s+", " ", s).strip()
        return s

    return f"{_clean(title)} {_clean(company)}"


def compute_hash(title: str, company: str) -> str:
    """Return SHA-256 hex digest of normalize(title, company)."""
    return hashlib.sha256(normalize(title, company).encode("utf-8")).hexdigest()


def is_duplicate(title: str, company: str, db_path: Path = _DEFAULT_DB) -> bool:
    """
    Return True if this title+company combination has been seen before.

    Checks discarded_hashes first (cheap), then the main jobs table.
    """
    h = compute_hash(title, company)
    return is_discarded(h, db_path) or is_seen(h, db_path)


def record_seen(
    title: str,
    company: str,
    url: str,
    source: str,
    status: str,
    db_path: Path = _DEFAULT_DB,
    extra: dict | None = None,
) -> None:
    """
    Write a job to the main jobs table with its dedup_hash set.

    Args:
        title: Job title.
        company: Company name.
        url: Unique job URL.
        source: Source scraper name.
        status: Initial status (typically "new", "scored", or "ready").
        db_path: Path to the SQLite database.
        extra: Any additional fields to store on the job record.
    """
    record: dict = {
        "url": url,
        "title": title,
        "company": company,
        "source": source,
        "status": status,
        "dedup_hash": compute_hash(title, company),
        **(extra or {}),
    }
    insert_job(record, db_path)
