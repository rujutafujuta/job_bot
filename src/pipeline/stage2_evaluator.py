"""
Stage 2 deep evaluator — 6-block Claude Code report with WebSearch.

Runs on jobs with stage1_score >= 95, or on-demand for any job.
Produces a 3,000–5,000 word Markdown report per job.
Runtime target: ~2–5 minutes per job (WebSearch adds latency).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from src.utils.claude_runner import ClaudeRunError, run_claude

_REPORTS_DIR = Path("data/reports")
_CV_PATH = Path("data/cv.md")

_STAGE2_TOOLS = ["WebSearch", "WebFetch"]

_PROMPT_TEMPLATE = """\
You are a senior career strategist and technical recruiter. Produce a deep evaluation report \
for the following job application. Use WebSearch and WebFetch to research live compensation data, \
company news, and posting signals. Be specific — cite what you find. Never fabricate data. \
If information is unavailable, state that explicitly rather than guessing.

The report must contain exactly these blocks in order:

## Block A — Role Summary
What the role actually is. Company overview (size, stage, funding if startup). Team context \
if detectable from JD language. Realistic day-to-day based on the JD. Posting date and freshness.

## Block B — CV Match + Company Health
Explicit skill-by-skill match against JD requirements. For each gap: a mitigation strategy \
("you don't have X, but Y is adjacent — frame it as Z"). Company health signals from recent \
news (funding, layoffs, leadership changes, growth trajectory). If candidate has a known contact \
at this company, flag it: "Referral signal: [name] is [title] here."

## Block C — Level Strategy
Is the seniority level realistic? Hidden mismatch between title and expectations? \
Should candidate negotiate for a higher level? \
Archetype: startup / growth-stage / big tech / consulting / enterprise / government — \
and what that means for application strategy.

## Block D — Comp Research
Search Glassdoor, Levels.fyi, and Blind for: base salary range, total comp range \
(equity + bonus if applicable), how this role compares to market for this level and location. \
If no data found, state: "No public compensation data found for this role/company."

## Block E — Personalization Plan
Top 5 specific changes to make when tailoring the resume for this job. \
Specific hooks for the cover letter (what to lead with, what story to tell, what to emphasize). \
Write these as numbered instructions, not as the actual tailored content.

## Block F — Interview Prep
Likely technical topics based on JD. Likely behavioral questions. Company-specific culture signals \
to reference. Red flags to probe during interviews. 1–2 questions candidate should ask.

After Block F, add a legitimacy assessment on its own line in exactly this format:
**Posting Legitimacy: [Verified|Uncertain|Likely Ghost Posting]**
Followed by 1–2 sentences explaining the signals.

---

=== CANDIDATE PROFILE ===
Name: {name}
Target roles: {target_roles}
Remote preference: {remote_preference}
Primary skills: {primary_skills}
Years of experience: {years_experience}
Career goals: {career_goals}

=== MASTER CV (excerpted) ===
{cv_excerpt}

=== JOB POSTING ===
Company: {company}
Title: {title}
Location: {location}
URL: {url}
Stage 1 score: {stage1_score}/100
Stage 1 reasoning: {stage1_reasoning}

Job Description:
{description}
"""

_LEGITIMACY_RE = re.compile(
    r"\*{0,2}Posting Legitimacy:\s*(Verified|Uncertain|Likely Ghost Posting)\*{0,2}",
    re.IGNORECASE,
)

_SCORE_RE = re.compile(r"stage\s*2\s*score[:\s]+(\d{1,3})", re.IGNORECASE)


@dataclass
class Stage2Result:
    score: int
    report_path: Path
    legitimacy: str
    error: str | None = None


def _parse_legitimacy(report: str) -> str:
    m = _LEGITIMACY_RE.search(report)
    if not m:
        return "uncertain"
    raw = m.group(1).lower()
    if "ghost" in raw:
        return "likely_ghost"
    if "verified" in raw:
        return "verified"
    return "uncertain"


def _parse_score(report: str, fallback: int) -> int:
    m = _SCORE_RE.search(report)
    if m:
        try:
            return max(0, min(100, int(m.group(1))))
        except ValueError:
            pass
    return fallback


def _slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")[:40]


def _build_report_path(company: str, title: str, reports_dir: Path) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{_slugify(company)}_{_slugify(title)}_{date.today().isoformat()}.md"
    return reports_dir / filename


def _cv_excerpt(cv_path: Path, max_chars: int = 6000) -> str:
    if not cv_path.exists():
        return "(cv.md not found)"
    return cv_path.read_text(encoding="utf-8")[:max_chars]


def evaluate_job(
    job: dict,
    cv_path: Path = _CV_PATH,
    profile: dict | None = None,
    reports_dir: Path = _REPORTS_DIR,
) -> Stage2Result:
    """
    Run Stage 2 deep evaluation for a single job.

    Calls Claude with WebSearch + WebFetch.
    Writes a .md report to reports_dir.
    Returns Stage2Result with score, path, and legitimacy signal.
    """
    profile = profile or {}
    personal = profile.get("personal", {})
    target = profile.get("target", {})
    skills = profile.get("skills", {})
    ctx = profile.get("cover_letter_context", {})

    prompt = _PROMPT_TEMPLATE.format(
        name=personal.get("full_name", "Candidate"),
        target_roles=", ".join(target.get("roles", [])),
        remote_preference=target.get("remote_preference", "any"),
        primary_skills=", ".join(skills.get("primary", [])),
        years_experience=skills.get("years_experience", 0),
        career_goals=ctx.get("career_goals", ""),
        cv_excerpt=_cv_excerpt(cv_path),
        company=job.get("company", ""),
        title=job.get("title", ""),
        location=job.get("location", ""),
        url=job.get("url", ""),
        stage1_score=job.get("stage1_score", 0),
        stage1_reasoning=job.get("stage1_reasoning", ""),
        description=(job.get("description", "") or "")[:5000],
    )

    report_path = _build_report_path(
        job.get("company", "unknown"),
        job.get("title", "unknown"),
        reports_dir,
    )

    try:
        report = run_claude(prompt, tools=_STAGE2_TOOLS, timeout=600)
    except ClaudeRunError as e:
        return Stage2Result(score=0, report_path=report_path, legitimacy="uncertain", error=str(e))

    report_path.write_text(report, encoding="utf-8")

    return Stage2Result(
        score=_parse_score(report, fallback=job.get("stage1_score", 0)),
        report_path=report_path,
        legitimacy=_parse_legitimacy(report),
    )
