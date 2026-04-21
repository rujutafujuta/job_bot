"""Job scoring via Claude — returns 0-100 match score + reasoning."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from src.scrapers.base import JobPosting
from src.utils import claude_client

_SYSTEM = (
    "You are an expert career coach and technical recruiter. "
    "You evaluate job postings against a candidate's profile with precision and candor."
)

_PROMPT_TEMPLATE = """
Evaluate how well this job posting matches the candidate's profile.

=== CANDIDATE PROFILE ===
Name: {full_name}
Target roles: {roles}
Target seniority: {seniority}
Locations: {locations} (remote preference: {remote_preference})
Requires sponsorship: {requires_sponsorship}
Primary skills: {primary_skills}
Secondary skills: {secondary_skills}
Years of experience: {years_experience}
Industries preferred: {industries_preferred}
Industries excluded: {industries_excluded}
Motivation: {motivation}

=== JOB POSTING ===
Title: {job_title}
Company: {company}
Location: {job_location}
Description:
{job_description}

=== INSTRUCTIONS ===
Return ONLY valid JSON in this exact format:
{{
  "score": <integer 0-100>,
  "reasoning": "<2-3 sentence explanation of the score>",
  "keywords": ["<key skill or requirement from JD>", ...],
  "disqualifiers": ["<any hard blockers>"]
}}

Scoring guide:
- 90-100: Near-perfect match, apply immediately
- 70-89: Strong match, worth applying
- 50-69: Partial match, significant gaps
- Below 50: Poor match, skip
- Auto-disqualify (score 0) if: sponsorship required but candidate needs it, or job is excluded industry
"""


@dataclass
class MatchResult:
    score: int
    reasoning: str
    keywords: list[str]
    disqualifiers: list[str]


def score_job(posting: JobPosting, profile: dict) -> MatchResult:
    """
    Score a job posting against the user profile using Claude.

    Returns a MatchResult with score (0-100), reasoning, and keywords.
    """
    personal = profile.get("personal", {})
    target = profile.get("target", {})
    skills = profile.get("skills", {})
    visa = profile.get("visa", {})

    prompt = _PROMPT_TEMPLATE.format(
        full_name=personal.get("full_name", ""),
        roles=", ".join(target.get("roles", [])),
        seniority=", ".join(target.get("seniority", [])),
        locations=", ".join(target.get("locations", [])) or "anywhere",
        remote_preference=target.get("remote_preference", "any"),
        requires_sponsorship=visa.get("requires_sponsorship", False),
        primary_skills=", ".join(skills.get("primary", [])),
        secondary_skills=", ".join(skills.get("secondary", [])),
        years_experience=skills.get("years_experience", 0),
        industries_preferred=", ".join(target.get("industries_preferred", [])),
        industries_excluded=", ".join(target.get("industries_excluded", [])),
        motivation=profile.get("motivation", ""),
        job_title=posting.title,
        company=posting.company,
        job_location=posting.location,
        job_description=posting.description[:4000],  # Truncate very long JDs
    )

    raw = claude_client.ask_structured(prompt, system=_SYSTEM)

    try:
        # Extract JSON even if Claude adds explanation text around it
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not json_match:
            raise ValueError("No JSON found in Claude response")
        data = json.loads(json_match.group())
        return MatchResult(
            score=int(data.get("score", 0)),
            reasoning=str(data.get("reasoning", "")),
            keywords=list(data.get("keywords", [])),
            disqualifiers=list(data.get("disqualifiers", [])),
        )
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        print(f"[matcher] Failed to parse Claude response for {posting.company}: {e}")
        return MatchResult(score=0, reasoning="Parse error", keywords=[], disqualifiers=[])
