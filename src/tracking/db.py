"""SQLite persistence layer — PRD v3.0 schema."""

from __future__ import annotations

import sqlite3
from pathlib import Path

_DEFAULT_DB = Path("data/tracking.db")

VALID_STATUSES: frozenset[str] = frozenset({
    "new", "scored", "ready", "applied", "skipped", "discarded",
    "phone_screen", "technical", "offer", "negotiating",
    "accepted", "withdrawn", "rejected", "ghosted",
})

# All writable job columns in order (excludes id, created_at, updated_at).
_JOB_COLUMNS = (
    "url", "title", "company", "location", "remote",
    "source", "dedup_hash",
    "salary_min", "salary_max", "salary_currency", "salary_period",
    "date_posted", "date_found", "description",
    "stage1_score", "stage1_reasoning",
    "stage2_score", "priority_score",
    "status",
    "evaluation_report_path", "tailored_resume_path",
    "cover_letter_path", "outreach_draft_path",
    "outreach_status",
    "referral_contact",
    "deadline",
    "applied_date",
    "follow_up_1_date", "follow_up_2_date", "ghosted_date",
    "notes",
)

_DDL = """
CREATE TABLE IF NOT EXISTS jobs (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    url                     TEXT    NOT NULL UNIQUE,
    title                   TEXT    NOT NULL DEFAULT '',
    company                 TEXT    NOT NULL DEFAULT '',
    location                TEXT             DEFAULT '',
    remote                  INTEGER          DEFAULT 0,
    source                  TEXT             DEFAULT '',
    dedup_hash              TEXT             DEFAULT '',
    salary_min              INTEGER          DEFAULT NULL,
    salary_max              INTEGER          DEFAULT NULL,
    salary_currency         TEXT             DEFAULT 'USD',
    salary_period           TEXT             DEFAULT 'year',
    date_posted             TEXT             DEFAULT '',
    date_found              TEXT             DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    description             TEXT             DEFAULT '',
    stage1_score            INTEGER          DEFAULT NULL,
    stage1_reasoning        TEXT             DEFAULT '',
    stage2_score            INTEGER          DEFAULT NULL,
    priority_score          INTEGER          DEFAULT 0,
    status                  TEXT    NOT NULL DEFAULT 'new',
    evaluation_report_path  TEXT             DEFAULT '',
    tailored_resume_path    TEXT             DEFAULT '',
    cover_letter_path       TEXT             DEFAULT '',
    outreach_draft_path     TEXT             DEFAULT '',
    outreach_status         TEXT             DEFAULT 'none',
    referral_contact        TEXT             DEFAULT '',
    deadline                TEXT             DEFAULT '',
    applied_date            TEXT             DEFAULT '',
    follow_up_1_date        TEXT             DEFAULT '',
    follow_up_2_date        TEXT             DEFAULT '',
    ghosted_date            TEXT             DEFAULT '',
    notes                   TEXT             DEFAULT '',
    created_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_jobs_status   ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_company  ON jobs(company);
CREATE INDEX IF NOT EXISTS idx_jobs_hash     ON jobs(dedup_hash);
CREATE INDEX IF NOT EXISTS idx_jobs_created  ON jobs(created_at DESC);

CREATE TABLE IF NOT EXISTS discarded_hashes (
    hash            TEXT PRIMARY KEY,
    title           TEXT NOT NULL DEFAULT '',
    company         TEXT NOT NULL DEFAULT '',
    source          TEXT NOT NULL DEFAULT '',
    discarded_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS contacts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    company     TEXT    NOT NULL DEFAULT '',
    title       TEXT             DEFAULT '',
    source      TEXT    NOT NULL DEFAULT 'manual',
    added_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(name, company)
);

CREATE TABLE IF NOT EXISTS outreach_messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id          INTEGER          REFERENCES jobs(id),
    type            TEXT    NOT NULL DEFAULT 'email',
    to_name         TEXT             DEFAULT '',
    to_email        TEXT             DEFAULT '',
    to_linkedin     TEXT             DEFAULT '',
    subject         TEXT             DEFAULT '',
    body            TEXT             DEFAULT '',
    status          TEXT    NOT NULL DEFAULT 'draft',
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    sent_at         TEXT             DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS idx_outreach_job ON outreach_messages(job_id);

CREATE TABLE IF NOT EXISTS scraper_runs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source              TEXT    NOT NULL,
    run_date            TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    jobs_found          INTEGER NOT NULL DEFAULT 0,
    jobs_passed_stage1  INTEGER NOT NULL DEFAULT 0,
    error_message       TEXT             DEFAULT NULL,
    duration_seconds    REAL             DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS idx_scraper_runs_source ON scraper_runs(source);
CREATE INDEX IF NOT EXISTS idx_scraper_runs_date   ON scraper_runs(run_date DESC);
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path = _DEFAULT_DB) -> None:
    """Create all tables and indexes. Safe to call on every startup."""
    with _connect(db_path) as conn:
        conn.executescript(_DDL)


def _validate_status(status: str) -> None:
    if status not in VALID_STATUSES:
        raise ValueError(
            f"Invalid status '{status}'. Must be one of {sorted(VALID_STATUSES)}"
        )


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def insert_job(record: dict, db_path: Path = _DEFAULT_DB) -> None:
    """
    Upsert a job record keyed on `url`.

    Only keys present in `record` that match known columns are written.
    Raises ValueError on missing url or invalid status.
    """
    if not record.get("url"):
        raise ValueError("record must have a non-empty 'url' key")
    if "status" in record:
        _validate_status(record["status"])

    cols = [c for c in _JOB_COLUMNS if c in record and c != "url"]
    values = [record[c] for c in cols]

    col_list = "url, " + ", ".join(cols)
    placeholders = "?, " + ", ".join("?" * len(cols))
    update_set = ", ".join(f"{c} = excluded.{c}" for c in cols)

    sql = f"""
    INSERT INTO jobs ({col_list})
    VALUES ({placeholders})
    ON CONFLICT(url) DO UPDATE SET
        {update_set},
        updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now')
    """

    with _connect(db_path) as conn:
        conn.execute(sql, [record["url"]] + values)


def update_job(url: str, fields: dict, db_path: Path = _DEFAULT_DB) -> bool:
    """
    Update specific fields on an existing job by URL.

    Returns True if a row was updated, False if URL not found.
    Raises ValueError on invalid status.
    """
    if "status" in fields:
        _validate_status(fields["status"])

    cols = [c for c in _JOB_COLUMNS if c in fields and c != "url"]
    if not cols:
        return False

    set_clause = ", ".join(f"{c} = ?" for c in cols)
    values = [fields[c] for c in cols] + [url]

    with _connect(db_path) as conn:
        cursor = conn.execute(
            f"UPDATE jobs SET {set_clause}, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE url = ?",
            values,
        )
        return cursor.rowcount > 0


def get_job(url: str, db_path: Path = _DEFAULT_DB) -> dict | None:
    """Return a single job by URL, or None if not found."""
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE url = ?", (url,)).fetchone()
    return _row_to_dict(row) if row else None


def get_all_jobs(db_path: Path = _DEFAULT_DB) -> list[dict]:
    """Return all jobs ordered newest first."""
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
    return [_row_to_dict(r) for r in rows]


def get_jobs_by_status(status: str, db_path: Path = _DEFAULT_DB) -> list[dict]:
    """Return all jobs with a given status, newest first."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC", (status,)
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def count_by_status(db_path: Path = _DEFAULT_DB) -> dict[str, int]:
    """Return {status: count} for all statuses with at least one job."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM jobs GROUP BY status"
        ).fetchall()
    return {row["status"]: row["n"] for row in rows}


def mark_discarded(
    hash_: str,
    title: str,
    company: str,
    source: str,
    db_path: Path = _DEFAULT_DB,
) -> None:
    """Insert a hash into discarded_hashes. No-op if already present."""
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO discarded_hashes (hash, title, company, source)
            VALUES (?, ?, ?, ?)
            """,
            (hash_, title, company, source),
        )


def is_discarded(hash_: str, db_path: Path = _DEFAULT_DB) -> bool:
    """Return True if this hash is in the discarded_hashes table."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM discarded_hashes WHERE hash = ?", (hash_,)
        ).fetchone()
    return row is not None


def is_seen(hash_: str, db_path: Path = _DEFAULT_DB) -> bool:
    """Return True if this dedup_hash exists in the main jobs table."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM jobs WHERE dedup_hash = ?", (hash_,)
        ).fetchone()
    return row is not None


def add_contact(
    name: str,
    company: str,
    title: str,
    source: str,
    db_path: Path = _DEFAULT_DB,
) -> None:
    """Insert or replace a contact. Upserts on (name, company)."""
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO contacts (name, company, title, source)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(name, company) DO UPDATE SET
                title = excluded.title,
                source = excluded.source
            """,
            (name, company, title, source),
        )


def get_job_by_id(job_id: int, db_path: Path = _DEFAULT_DB) -> dict | None:
    """Return a single job by integer primary key, or None if not found."""
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_dict(row) if row else None


def update_job_by_id(job_id: int, fields: dict, db_path: Path = _DEFAULT_DB) -> bool:
    """
    Update specific fields on an existing job by integer id.

    Returns True if a row was updated, False if id not found.
    Raises ValueError on invalid status.
    """
    if "status" in fields:
        _validate_status(fields["status"])

    cols = [c for c in _JOB_COLUMNS if c in fields and c != "url"]
    if not cols:
        return False

    set_clause = ", ".join(f"{c} = ?" for c in cols)
    values = [fields[c] for c in cols] + [job_id]

    with _connect(db_path) as conn:
        cursor = conn.execute(
            f"UPDATE jobs SET {set_clause}, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id = ?",
            values,
        )
        return cursor.rowcount > 0


def get_jobs_by_statuses(statuses: list[str], db_path: Path = _DEFAULT_DB) -> list[dict]:
    """Return all jobs whose status is in the given list, newest first."""
    if not statuses:
        return []
    placeholders = ", ".join("?" * len(statuses))
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM jobs WHERE status IN ({placeholders}) ORDER BY created_at DESC",
            statuses,
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_priority_queue(db_path: Path = _DEFAULT_DB) -> list[dict]:
    """Return all scored+ready jobs sorted by priority_score descending."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM jobs
            WHERE status IN ('scored', 'ready')
            ORDER BY priority_score DESC, created_at DESC
            """,
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_followup_due(db_path: Path = _DEFAULT_DB) -> list[dict]:
    """Return applied jobs where follow_up_1_date or follow_up_2_date is today or past."""
    today = __import__("datetime").date.today().isoformat()
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM jobs
            WHERE status = 'applied'
              AND (
                (follow_up_1_date != '' AND follow_up_1_date <= ?)
                OR (follow_up_2_date != '' AND follow_up_2_date <= ?)
              )
            ORDER BY follow_up_1_date ASC
            """,
            (today, today),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


_APPLIED_PIPELINE_STATUSES = (
    "applied", "phone_screen", "technical", "offer", "negotiating",
    "accepted", "withdrawn", "rejected", "ghosted",
)


def get_applied_jobs(db_path: Path = _DEFAULT_DB) -> list[dict]:
    """Return all jobs in post-application pipeline statuses, newest first."""
    placeholders = ", ".join("?" * len(_APPLIED_PIPELINE_STATUSES))
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM jobs WHERE status IN ({placeholders}) ORDER BY applied_date DESC, created_at DESC",
            list(_APPLIED_PIPELINE_STATUSES),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_pending_outreach(db_path: Path = _DEFAULT_DB) -> list[dict]:
    """Return jobs with outreach drafts waiting for user action."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE outreach_status = 'pending_user_input' ORDER BY created_at DESC"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def compute_followup_dates(applied_date_str: str) -> tuple[str, str, str]:
    """
    Given an applied date string (YYYY-MM-DD), return follow-up cadence dates.

    Returns:
        (follow_up_1_date +7d, follow_up_2_date +14d, ghosted_date +30d)
    """
    from datetime import date, timedelta
    applied = date.fromisoformat(applied_date_str)
    return (
        (applied + timedelta(days=7)).isoformat(),
        (applied + timedelta(days=14)).isoformat(),
        (applied + timedelta(days=30)).isoformat(),
    )


def mark_ghosted_jobs(db_path: Path = _DEFAULT_DB) -> int:
    """
    Mark applied jobs as ghosted when their ghosted_date has passed.

    Returns:
        Number of jobs updated.
    """
    today = __import__("datetime").date.today().isoformat()
    with _connect(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE jobs
            SET status = 'ghosted', updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now')
            WHERE status = 'applied'
              AND ghosted_date != ''
              AND ghosted_date <= ?
            """,
            (today,),
        )
        return cursor.rowcount


def get_contacts_for_company(company: str, db_path: Path = _DEFAULT_DB) -> list[dict]:
    """Return contacts whose company name contains the given string (case-insensitive)."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM contacts WHERE LOWER(company) = LOWER(?) ORDER BY name ASC",
            (company,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def list_contacts(db_path: Path = _DEFAULT_DB) -> list[dict]:
    """Return all contacts ordered by company, then name."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM contacts ORDER BY company ASC, name ASC"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def count_contacts(db_path: Path = _DEFAULT_DB) -> int:
    """Return total contact count."""
    with _connect(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM contacts").fetchone()
    return row["n"] if row else 0


def get_recent_activity(limit: int = 10, db_path: Path = _DEFAULT_DB) -> list[dict]:
    """Return the most recently updated jobs for the activity feed."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT title, company, status, updated_at FROM jobs ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Outreach messages
# ---------------------------------------------------------------------------

def save_outreach_draft(
    job_id: int | None,
    msg_type: str,
    to_name: str,
    to_email: str,
    to_linkedin: str,
    subject: str,
    body: str,
    db_path: Path = _DEFAULT_DB,
) -> int:
    """Insert a new outreach message record with status='draft'. Returns its id."""
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO outreach_messages
                (job_id, type, to_name, to_email, to_linkedin, subject, body, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'draft')
            """,
            (job_id, msg_type, to_name, to_email, to_linkedin, subject, body),
        )
        return cur.lastrowid


def list_outreach_messages(db_path: Path = _DEFAULT_DB) -> list[dict]:
    """Return all outreach messages, newest first."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM outreach_messages ORDER BY created_at DESC"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def update_outreach_status(
    message_id: int,
    status: str,
    db_path: Path = _DEFAULT_DB,
) -> bool:
    """Update the status of an outreach message. Returns True if a row was changed."""
    sent_at_clause = ", sent_at = strftime('%Y-%m-%dT%H:%M:%SZ','now')" if status == "sent" else ""
    with _connect(db_path) as conn:
        cur = conn.execute(
            f"UPDATE outreach_messages SET status = ?{sent_at_clause} WHERE id = ?",
            (status, message_id),
        )
        return cur.rowcount > 0


def count_outreach_for_company(company: str, db_path: Path = _DEFAULT_DB) -> int:
    """Return how many outreach messages exist for jobs at the given company."""
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM outreach_messages om
            JOIN jobs j ON om.job_id = j.id
            WHERE j.company = ?
            """,
            (company,),
        ).fetchone()
    return row["n"] if row else 0


# ---------------------------------------------------------------------------
# Scraper health
# ---------------------------------------------------------------------------

def record_scraper_run(
    source: str,
    jobs_found: int,
    jobs_passed_stage1: int,
    error_message: str | None,
    duration_seconds: float,
    db_path: Path = _DEFAULT_DB,
) -> None:
    """Insert one row per scraper per pipeline run."""
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO scraper_runs
                (source, jobs_found, jobs_passed_stage1, error_message, duration_seconds)
            VALUES (?, ?, ?, ?, ?)
            """,
            (source, jobs_found, jobs_passed_stage1, error_message, duration_seconds),
        )


def get_scraper_health(db_path: Path = _DEFAULT_DB) -> list[dict]:
    """Return per-source summary: last run date, last jobs found, consecutive zero days."""
    with _connect(db_path) as conn:
        sources = [
            r["source"]
            for r in conn.execute(
                "SELECT DISTINCT source FROM scraper_runs ORDER BY source"
            ).fetchall()
        ]
        result = []
        for source in sources:
            rows = conn.execute(
                """
                SELECT jobs_found, run_date, error_message
                FROM scraper_runs
                WHERE source = ?
                ORDER BY run_date DESC, id DESC
                """,
                (source,),
            ).fetchall()
            last = rows[0]
            consecutive_zeros = 0
            for row in rows:
                if row["jobs_found"] == 0:
                    consecutive_zeros += 1
                else:
                    break
            result.append({
                "source": source,
                "last_run_date": last["run_date"],
                "last_jobs_found": last["jobs_found"],
                "last_error": last["error_message"],
                "consecutive_zero_days": consecutive_zeros,
            })
    return result


def get_stale_scrapers(threshold_days: int = 3, db_path: Path = _DEFAULT_DB) -> list[str]:
    """Return sources with consecutive_zero_days >= threshold_days."""
    return [
        row["source"]
        for row in get_scraper_health(db_path=db_path)
        if row["consecutive_zero_days"] >= threshold_days
    ]
