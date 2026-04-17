"""Cover letter generation via Claude Code CLI subprocess."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from src.utils.claude_runner import run_claude

_COVER_LETTERS_DIR = Path("data/cover_letters")

_PROMPT_TEMPLATE = """\
You are an expert career coach writing a cover letter for a job application.

Write a compelling, authentic cover letter for the candidate. Rules:
1. Use the Personalization Plan hooks — lead with the strongest specific angle.
2. Draw content ONLY from the tailored resume — no invented details.
3. Reference the candidate's career goals and motivations naturally.
4. Tone: confident and direct. No hollow phrases ("I am passionate about...").
5. Length: 3 short paragraphs. No longer. No headers.
6. Close with a specific, genuine statement — not a generic "I look forward to hearing from you."

=== PERSONALIZATION PLAN (hooks to use) ===
{personalization_plan}

=== JOB ===
Company: {company}
Title: {title}
Description (excerpted): {description}

=== CANDIDATE PROFILE ===
Name: {name}
Career goals: {career_goals}
Motivations: {motivations}
Strengths: {strengths}

=== TAILORED RESUME (reference only) ===
{tailored_resume}

Output ONLY the cover letter text. No subject line, no "Dear [hiring manager]" opener needed \
unless it fits naturally. No explanation.
"""


def _extract_block_e(evaluation_report: str) -> str:
    match = re.search(
        r"##\s*Block E.*?(?=##\s*Block F|$)",
        evaluation_report,
        re.DOTALL | re.IGNORECASE,
    )
    return match.group(0).strip() if match else evaluation_report


def _slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")[:40]


def generate_cover_letter(
    job: dict,
    evaluation_report: str,
    tailored_resume: str,
    profile: dict,
    cover_letters_dir: Path = _COVER_LETTERS_DIR,
) -> Path:
    """
    Generate a cover letter for the given job using Block E hooks and profile context.

    Returns path to the written .md file.
    """
    personal = profile.get("personal", {})
    ctx = profile.get("cover_letter_context", {})

    prompt = _PROMPT_TEMPLATE.format(
        personalization_plan=_extract_block_e(evaluation_report),
        company=job.get("company", ""),
        title=job.get("title", ""),
        description=(job.get("description", "") or "")[:1500],
        name=personal.get("full_name", "Candidate"),
        career_goals=ctx.get("career_goals", ""),
        motivations=ctx.get("motivations", ""),
        strengths=ctx.get("strengths", ""),
        tailored_resume=tailored_resume[:3000],
    )

    content = run_claude(prompt, timeout=120)

    cover_letters_dir.mkdir(parents=True, exist_ok=True)
    filename = (
        f"{_slugify(job.get('company', 'unknown'))}_"
        f"{_slugify(job.get('title', 'unknown'))}_"
        f"{date.today().isoformat()}.md"
    )
    out_path = cover_letters_dir / filename
    out_path.write_text(content, encoding="utf-8")
    return out_path
