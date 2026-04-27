"""
Stage 1 fast scorer — Claude Code subprocess, no web search.

Scores each new job 0-100 against the user profile.
Routes by score:
  <70  → discarded_hashes table, nothing else stored
  70-94 → main jobs table, status=scored
  95+   → main jobs table, status=ready (Stage 2 triggered by orchestrator)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from src.scrapers.base import JobPosting
from src.tracking.db import _DEFAULT_DB, mark_discarded
from src.tracking.deduplication import compute_hash, record_seen
from src.utils.claude_runner import run_claude

_MAX_DESCRIPTION_CHARS = 6000

_PROMPT_TEMPLATE = """You are a technical recruiter evaluating a job posting against a candidate profile.

Score how well this job matches the candidate. Return ONLY valid JSON — no explanation.

Format:
{{"score": <integer 0-100>, "reasoning": "<1-2 sentences>"}}

Scoring:
- 95-100: Near-perfect match — strong fit on role, skills, level, location preference
- 70-94: Good match — worth applying, some gaps but manageable
- 0-69: Poor match — significant gaps, wrong level, excluded industry, or sponsorship conflict

Auto-score 0 if: candidate requires sponsorship (`requires_sponsorship: true`) and the role requires citizenship or states "no sponsorship".

=== CANDIDATE PROFILE SUMMARY ===
Name: {name}
Target roles: {target_roles}
Remote preference: {remote_preference}
Target locations: {target_locations}
Primary skills: {primary_skills}
Years of experience: {years_experience}
Work authorization: {work_auth}
Requires sponsorship: {requires_sponsorship}
Industries to avoid: {excluded_industries}

=== JOB POSTING ===
Title: {title}
Company: {company}
Location: {location}
Description:
{description}
"""


@dataclass
class Stage1Result:
    score: int
    reasoning: str


def score_job(posting: JobPosting, profile: dict) -> Stage1Result:
    """
    Score a job posting using Claude Code CLI subprocess.

    No web search tools — this must stay fast (<10s target).
    """
    personal = profile.get("personal", {})
    target = profile.get("target", {})
    skills = profile.get("skills", {})
    visa = profile.get("visa", {})

    target_locations = target.get("locations", [])
    locations_str = ", ".join(target_locations) if target_locations else "anywhere"

    # Visa supports both new (statuses: list) and legacy (status: str) schemas
    statuses = visa.get("statuses") or ([visa["status"]] if visa.get("status") else [])
    work_auth_str = ", ".join(s for s in statuses if s) or "unknown"

    prompt = _PROMPT_TEMPLATE.format(
        name=personal.get("full_name", "Candidate"),
        target_roles=", ".join(target.get("roles", [])),
        remote_preference=target.get("remote_preference", "any"),
        target_locations=locations_str,
        primary_skills=", ".join(skills.get("primary", [])),
        years_experience=skills.get("years_experience", 0),
        work_auth=work_auth_str,
        requires_sponsorship="yes" if visa.get("requires_sponsorship") else "no",
        excluded_industries=", ".join(target.get("industries_excluded", [])) or "none",
        title=posting.title,
        company=posting.company,
        location=posting.location,
        description=posting.description[:_MAX_DESCRIPTION_CHARS],
    )

    try:
        raw = run_claude(prompt, timeout=30)
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not json_match:
            snippet = (raw or "<empty>")[:200].replace("\n", " ")
            print(f"[stage1] No JSON in response for {posting.company}/{posting.title}: {snippet}")
            return Stage1Result(score=0, reasoning=f"Parse error: no JSON ({snippet[:80]})")
        data = json.loads(json_match.group())
        return Stage1Result(
            score=max(0, min(100, int(data.get("score", 0)))),
            reasoning=str(data.get("reasoning", "")),
        )
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        print(f"[stage1] Parse error for {posting.company}/{posting.title}: {e}")
        return Stage1Result(score=0, reasoning=f"Parse error: {e}")
    except Exception as e:
        print(f"[stage1] Claude error for {posting.company}/{posting.title}: {e}")
        return Stage1Result(score=0, reasoning=f"Claude error: {e}")


def route_job(
    result: Stage1Result,
    posting: JobPosting,
    db_path: Path = _DEFAULT_DB,
) -> str:
    """
    Store the job based on its Stage 1 score.

    Returns the action taken: "discarded", "scored", or "ready".
    """
    h = compute_hash(posting.title, posting.company)

    if result.score < 70:
        mark_discarded(h, posting.title, posting.company, posting.source, db_path)
        return "discarded"

    status = "ready" if result.score >= 95 else "scored"

    record_seen(
        title=posting.title,
        company=posting.company,
        url=posting.url,
        source=posting.source,
        status=status,
        db_path=db_path,
        extra={
            "location": posting.location,
            "description": posting.description,
            "date_posted": posting.date_posted,
            "salary_min": None,
            "salary_max": None,
            "stage1_score": result.score,
            "stage1_reasoning": result.reasoning,
        },
    )

    return status
