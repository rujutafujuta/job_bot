"""
Resume tailor — cv.md → tailored Markdown resume per job.

Uses Block E (personalization plan) from the Stage 2 evaluation report.
Enforces number protection: no numeric value from cv.md may be dropped.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from src.utils.claude_runner import run_claude

_RESUMES_DIR = Path("data/resumes")
_CV_PATH = Path("data/cv.md")

_NUMBER_RE = re.compile(
    r"""
    \$[\d,]+(?:\.\d+)?[MKBmkb]?   # dollar amounts: $1.2M, $500K, $50,000
    | \d+(?:\.\d+)?%               # percentages: 98%, 3.5%
    | \b\d{4}\b                    # 4-digit years: 2021, 2024
    | \b\d+(?:\.\d+)?\b            # plain numbers: 42, 3, 1.5
    """,
    re.VERBOSE,
)

_KEYWORD_STOPWORDS = frozenset({
    "and", "the", "for", "are", "with", "you", "will", "our", "have", "this",
    "that", "from", "they", "your", "work", "role", "team", "able", "their",
    "been", "about", "more", "also", "we", "or", "an", "in", "to", "of", "a",
    "is", "at", "on", "be", "as", "by", "it", "its", "can", "not", "but",
    "join", "we're", "you'll", "we'll", "who", "what", "how",
})

_KEYWORD_RE = re.compile(r"\b[a-zA-Z][\w+#.\-]{2,}\b")


def _extract_ats_keywords(description: str, top_n: int = 10) -> list[str]:
    """Extract top-N technical/skill keywords from a job description by frequency."""
    words = _KEYWORD_RE.findall(description.lower())
    counts: dict[str, int] = {}
    for w in words:
        if w not in _KEYWORD_STOPWORDS and not w.isdigit():
            counts[w] = counts.get(w, 0) + 1
    sorted_words = sorted(counts, key=lambda w: -counts[w])
    return sorted_words[:top_n]


_PROMPT_TEMPLATE = """\
You are a professional resume writer. Tailor the candidate's master CV for this specific job.

Rules (strictly enforced):
1. Select the most relevant content from the master CV — do not invent anything new.
2. You may rephrase, reorder, and omit sections — but NEVER change any number. \
Years of experience, percentages, GPA, team sizes, dollar amounts, dates — freeze them exactly.
3. Apply the Personalization Plan below — these are your top priorities.
4. The result must be a clean Markdown resume that fits one printed page when rendered.
5. Use past-tense action verbs. No personal pronouns.

=== PERSONALIZATION PLAN (from evaluation report) ===
{personalization_plan}

=== JOB POSTING ===
Company: {company}
Title: {title}
Description (excerpted):
{description}

=== MASTER CV ===
{cv_content}

Output ONLY the tailored resume in Markdown. No preamble, no explanation.
"""


def extract_numbers(text: str) -> set[str]:
    """Return all numeric tokens found in text (raw strings, not parsed values)."""
    return set(_NUMBER_RE.findall(text))


def validate_numbers(original_cv: str, tailored: str) -> list[str]:
    """
    Return a list of numeric tokens present in original_cv but missing from tailored.

    An empty list means all numbers were preserved.
    """
    original_nums = extract_numbers(original_cv)
    tailored_nums = extract_numbers(tailored)
    return sorted(original_nums - tailored_nums)


def _extract_block_e(evaluation_report: str) -> str:
    """Pull Block E text from the evaluation report. Returns full report if not found."""
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


def tailor_resume(
    job: dict,
    evaluation_report: str,
    cv_path: Path = _CV_PATH,
    resumes_dir: Path = _RESUMES_DIR,
) -> Path:
    """
    Tailor the master CV for a specific job using the Block E personalization plan.

    Writes tailored Markdown to resumes_dir.
    Raises FileNotFoundError if cv_path does not exist.
    Returns the path to the written file.
    """
    if not cv_path.exists():
        raise FileNotFoundError(f"Master CV not found: {cv_path}")

    cv_content = cv_path.read_text(encoding="utf-8")
    personalization_plan = _extract_block_e(evaluation_report)

    prompt = _PROMPT_TEMPLATE.format(
        personalization_plan=personalization_plan,
        company=job.get("company", ""),
        title=job.get("title", ""),
        description=(job.get("description", "") or "")[:3000],
        cv_content=cv_content,
    )

    tailored = run_claude(prompt, timeout=180)

    dropped = validate_numbers(cv_content, tailored)
    if dropped:
        raise ValueError(
            f"[resume_tailor] Number protection violation — these values were "
            f"dropped from the tailored resume and must be preserved: {dropped}"
        )

    # sr-only ATS keyword injection
    description = (job.get("description", "") or "")
    if description:
        keywords = _extract_ats_keywords(description)
        if keywords:
            kw_html = " ".join(
                f'<span class="sr-only">{kw}</span>' for kw in keywords
            )
            tailored = tailored + f"\n\n{kw_html}"

    resumes_dir.mkdir(parents=True, exist_ok=True)
    filename = (
        f"{_slugify(job.get('company', 'unknown'))}_"
        f"{_slugify(job.get('title', 'unknown'))}_"
        f"{date.today().isoformat()}.md"
    )
    out_path = resumes_dir / filename
    out_path.write_text(tailored, encoding="utf-8")
    return out_path
