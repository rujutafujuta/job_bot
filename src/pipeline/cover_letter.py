"""Cover letter generation via Claude."""

from __future__ import annotations

from pathlib import Path
import re

from src.scrapers.base import JobPosting
from src.pipeline.matcher import MatchResult
from src.utils import claude_client

_SYSTEM = (
    "You are an expert cover letter writer. "
    "You write concise, specific, compelling cover letters that don't sound generic. "
    "No fluff. No clichés. Max 3 short paragraphs."
)

_PROMPT_TEMPLATE = """
Write a cover letter for this job application.

=== CANDIDATE ===
Name: {full_name}
Email: {email}
LinkedIn: {linkedin}
Years of experience: {years_experience}
Primary skills: {primary_skills}
Motivation: {motivation}

=== JOB ===
Title: {job_title}
Company: {company}
Key requirements / keywords: {keywords}
Description excerpt:
{description_excerpt}

=== INSTRUCTIONS ===
- Opening: Hook that references something specific about {company} or the role
- Middle: 2-3 concrete achievements that map to the role's needs (use numbers if possible)
- Close: Clear call to action, no "I look forward to hearing from you" clichés
- Tone: {tone}
- Sign off with candidate's name only (no contact info — it'll be in the email signature)
- Return ONLY the cover letter text, no subject line, no headers
"""


def generate_cover_letter(
    posting: JobPosting,
    match_result: MatchResult,
    profile: dict,
    output_dir: Path = Path("data/cover_letters"),
    dry_run: bool = False,
) -> Path | None:
    """
    Generate a cover letter for the job posting and save to output_dir.

    Returns:
        Path to the saved .txt cover letter, or None if dry_run.
    """
    personal = profile.get("personal", {})
    skills = profile.get("skills", {})
    outreach = profile.get("outreach", {})

    prompt = _PROMPT_TEMPLATE.format(
        full_name=personal.get("full_name", ""),
        email=personal.get("email", ""),
        linkedin=personal.get("linkedin_url", ""),
        years_experience=skills.get("years_experience", 0),
        primary_skills=", ".join(skills.get("primary", [])),
        motivation=profile.get("motivation", ""),
        job_title=posting.title,
        company=posting.company,
        keywords=", ".join(match_result.keywords),
        description_excerpt=posting.description[:2000],
        tone=outreach.get("cold_email_tone", "friendly"),
    )

    print(f"[cover_letter] Generating for {posting.company}")

    if dry_run:
        print(f"[cover_letter][DRY RUN] Would generate cover letter for {posting.company}")
        return None

    letter = claude_client.ask(prompt, system=_SYSTEM, max_tokens=2048)

    output_dir.mkdir(parents=True, exist_ok=True)
    company_slug = re.sub(r"[^\w]", "_", posting.company)
    full_name_slug = personal.get("full_name", "candidate").replace(" ", "_")
    out_path = output_dir / f"{full_name_slug}_{company_slug}_cover_letter.txt"
    out_path.write_text(letter, encoding="utf-8")

    print(f"[cover_letter] Saved: {out_path}")
    return out_path
