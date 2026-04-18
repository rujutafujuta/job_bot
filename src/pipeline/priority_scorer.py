"""
Priority score computation — pure function, no Claude, no DB.

Scoring table (PRD v3.0):
  +30  deadline <3 days away
  +25  referral contact at company
  +20  deadline <7 days away
  +20  fit score (proportional to 0-100 → 0-20)
  +10  job posted <7 days ago
  +8   positive company health signal (funding/growth keywords in notes)
  +8   salary above user minimum (not implemented until profile integration)
  +7   in queue 5+ days untouched (date_found)
  -15  negative health signal (layoffs/cuts/freeze keywords in notes)
  -5   job posted >30 days ago
"""

from __future__ import annotations

import datetime
import re

_NEGATIVE_SIGNALS = frozenset({"layoff", "layoffs", "cuts", "freeze", "downsizing", "restructur"})
_POSITIVE_SIGNALS = frozenset({"funding", "raised", "series", "growth", "hiring", "expanding"})


def _parse_date(value: str) -> datetime.date | None:
    """Parse ISO date string (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ). Returns None on failure."""
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value[:10])
    except ValueError:
        return None


def _fit_score(job: dict) -> int:
    """Use stage2_score if available, else stage1_score. Returns 0-100."""
    s2 = job.get("stage2_score")
    if s2 is not None:
        try:
            return max(0, min(100, int(s2)))
        except (TypeError, ValueError):
            pass
    s1 = job.get("stage1_score")
    if s1 is not None:
        try:
            return max(0, min(100, int(s1)))
        except (TypeError, ValueError):
            pass
    return 0


def compute_priority(job: dict) -> int:
    """
    Compute a priority score for a job dict.

    Higher = more urgent to act on. Score is clamped to >= 0.
    """
    today = datetime.date.today()
    score = 0

    # Deadline urgency
    deadline = _parse_date(job.get("deadline", ""))
    if deadline and deadline >= today:
        days_left = (deadline - today).days
        if days_left <= 3:
            score += 30
        elif days_left <= 7:
            score += 20

    # Referral contact
    if job.get("referral_contact", "").strip():
        score += 25

    # Fit score (0-100 mapped to 0-20)
    score += round(_fit_score(job) / 100 * 20)

    # Posting freshness
    date_posted = _parse_date(job.get("date_posted", ""))
    if date_posted:
        age_days = (today - date_posted).days
        if age_days <= 7:
            score += 10
        elif age_days > 30:
            score -= 5

    # Health signals from notes field
    notes_lower = (job.get("notes", "") or "").lower()
    if any(sig in notes_lower for sig in _POSITIVE_SIGNALS):
        score += 8
    if any(sig in notes_lower for sig in _NEGATIVE_SIGNALS):
        score -= 15

    # Queue age — reward jobs that have been sitting untouched
    date_found = _parse_date(job.get("date_found", ""))
    if date_found:
        queue_days = (today - date_found).days
        if queue_days >= 5:
            score += 7

    return max(0, score)


def priority_label(score: int) -> str:
    """Convert numeric priority score to a human-readable label."""
    if score >= 40:
        return "High"
    if score >= 20:
        return "Medium"
    return "Low"
