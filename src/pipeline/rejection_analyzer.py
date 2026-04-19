"""Rejection analysis — Claude analyzes patterns across rejected/ghosted jobs."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from src.tracking.db import _DEFAULT_DB, get_jobs_by_statuses
from src.utils.claude_runner import run_claude

_REPORTS_DIR = Path("data/reports")

_PROMPT_TEMPLATE = """\
You are a career strategist analyzing a job seeker's rejection patterns to help them improve.

Below is a list of jobs where the candidate was rejected, ghosted, or withdrew.
Analyze the data and produce a structured report covering:

## 1. Volume & Stage Breakdown
How many rejections vs ghostings vs withdrawals. Which stage most rejections occur at \
(early/ATS screen vs human review vs interview vs final round — infer from available data).

## 2. Role & Company Patterns
Which role types, seniority levels, company sizes, or industries generate more rejections? \
Are there patterns in the companies that ghost vs reject?

## 3. Keyword Gap Analysis
Compare the job descriptions against the evaluation reports (if available). \
What skills or keywords appear frequently in rejected jobs that might be missing or \
underemphasized in the candidate's profile?

## 4. Application Timing
Are there patterns in how old postings were at time of application? \
Were applications made to postings already weeks old?

## 5. Actionable Recommendations
Top 3–5 specific, actionable changes the candidate can make to reduce rejections. \
Be direct. Prioritize by likely impact.

---

=== REJECTION / GHOSTING DATA ===
{jobs_data}
"""


def run_rejection_analysis(
    db_path: Path = _DEFAULT_DB,
    reports_dir: Path = _REPORTS_DIR,
) -> Path:
    """
    Analyze all rejected/ghosted jobs and produce a Markdown report.

    Returns:
        Path to the written report file.

    Raises:
        ValueError: If there are fewer than 3 rejected/ghosted jobs to analyze.
    """
    statuses = ["rejected", "ghosted", "withdrawn"]
    jobs = get_jobs_by_statuses(statuses, db_path)

    if len(jobs) < 3:
        raise ValueError(
            f"Not enough data for analysis — need at least 3 rejected/ghosted jobs, "
            f"found {len(jobs)}. Apply to more jobs first."
        )

    job_lines: list[str] = []
    for j in jobs:
        line = (
            f"- {j.get('company', '?')} / {j.get('title', '?')} "
            f"[status={j.get('status')}] "
            f"[stage1={j.get('stage1_score', '?')}] "
            f"[stage2={j.get('stage2_score', '?')}] "
            f"[applied={j.get('applied_date', '?')}] "
            f"[posted={j.get('date_posted', '?')}]"
        )
        report_path = j.get("evaluation_report_path", "")
        if report_path and Path(report_path).exists():
            excerpt = Path(report_path).read_text(encoding="utf-8")[:800]
            line += f"\n  Report excerpt: {excerpt[:300]}"
        job_lines.append(line)

    prompt = _PROMPT_TEMPLATE.format(jobs_data="\n".join(job_lines))
    report = run_claude(prompt, timeout=300)

    reports_dir.mkdir(parents=True, exist_ok=True)
    filename = f"rejection_analysis_{date.today().isoformat()}.md"
    out_path = reports_dir / filename
    out_path.write_text(report, encoding="utf-8")
    print(f"[rejection_analyzer] Report written to {out_path}")
    return out_path
