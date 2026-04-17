"""Resume tailoring — Claude modifies content fields only in a .tex copy, then compiles."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from src.scrapers.base import JobPosting
from src.pipeline.matcher import MatchResult
from src.utils import claude_client
from src.utils.latex_compiler import compile_tex, count_pdf_pages

_SYSTEM = (
    "You are an expert resume writer and LaTeX specialist. "
    "You modify resume content to match job postings WITHOUT touching any LaTeX commands, "
    "environments, formatting, or structure. "
    "You are scrupulously honest — you never invent, exaggerate, or imply experience "
    "the candidate does not have. Your edits reframe existing facts, not fabricate new ones."
)

_MAX_PAGE_RETRIES = 3

_SHORTEN_PROMPT_TEMPLATE = """
The resume below compiled to {pages} page(s) but MUST fit on exactly 1 page.

Shorten it by:
- Trimming bullet points (fewer words, same meaning)
- Removing the lowest-priority bullets as a last resort
- Never adding new content

STRICT RULES (unchanged from before):
1. Do NOT change any \\command, \\begin, \\end, %, or LaTeX syntax
2. Do NOT add or remove sections
3. Do NOT change dates, company names, job titles, or education
4. Do NOT fabricate experience — only rephrase existing facts
5. Return ONLY the complete modified .tex source, nothing else

=== RESUME SOURCE ===
{tex_source}
"""

_PROMPT_TEMPLATE = """
You will receive a LaTeX resume source. Modify ONLY the following content fields to better match the job posting:
- Professional summary / objective section text
- Skills bullet points (reorder to surface relevant skills; only list skills already present)
- Experience bullet points (reframe achievements using JD language where truthful)

STRICT RULES — violations will cause this resume to be rejected:
1. Do NOT change any \\command, \\begin, \\end, %, {{ }}, or LaTeX syntax of any kind
2. Do NOT add or remove sections, headers, or structural elements
3. Do NOT change dates, company names, job titles, school names, or degree names
4. Do NOT change any NUMBER — years of experience, percentages, GPA, headcounts, dollar amounts must stay exactly as written
5. Do NOT add any skill, technology, or tool that does not already appear somewhere in the resume
6. Do NOT fabricate, exaggerate, or imply experience the candidate does not have
7. Do NOT change the order of jobs or education entries
8. Return ONLY the complete modified .tex source, with no preamble, explanation, or markdown fences

=== JOB POSTING ===
Title: {job_title}
Company: {company}
Keywords to emphasize: {keywords}
Description excerpt:
{description_excerpt}

=== RESUME SOURCE ===
{tex_source}
"""


def tailor_resume(
    posting: JobPosting,
    match_result: MatchResult,
    profile: dict,
    output_dir: Path = Path("data/resumes"),
    dry_run: bool = False,
) -> tuple[Path, Path] | None:
    """
    Create a tailored .tex resume for the job posting and compile it to PDF.

    Args:
        posting: The job posting to tailor for.
        match_result: Claude's match analysis (provides keywords).
        profile: User profile dict.
        output_dir: Directory to write .tex and .pdf files.
        dry_run: If True, skip writing files and compilation.

    Returns:
        Tuple of (tex_path, pdf_path) or None if dry_run.
    """
    master_tex = Path(profile["resume"]["master_tex_path"])
    if not master_tex.exists():
        raise FileNotFoundError(f"Master resume not found: {master_tex}")

    tex_source = master_tex.read_text(encoding="utf-8")

    full_name = profile["personal"]["full_name"].replace(" ", "_")
    company_slug = re.sub(r"[^\w]", "_", posting.company)
    output_name = profile["resume"]["output_name_format"].format(
        full_name=full_name, company=company_slug
    )

    prompt = _PROMPT_TEMPLATE.format(
        job_title=posting.title,
        company=posting.company,
        keywords=", ".join(match_result.keywords),
        description_excerpt=posting.description[:2000],
        tex_source=tex_source,
    )

    print(f"[resume] Tailoring for {posting.company} ({posting.title})")

    if dry_run:
        print(f"[resume][DRY RUN] Would generate {output_name}.tex and compile to PDF")
        return None

    tailored_tex = claude_client.ask(prompt, system=_SYSTEM, max_tokens=8192)

    # Strip markdown fences if Claude added them despite instructions
    if tailored_tex.strip().startswith("```"):
        tailored_tex = re.sub(r"^```[^\n]*\n?", "", tailored_tex.strip())
        tailored_tex = re.sub(r"\n?```$", "", tailored_tex.strip())

    # Sanity check: ensure Claude didn't strip essential LaTeX
    if "\\documentclass" not in tailored_tex and "\\documentclass" in tex_source:
        print("[resume] Warning: Claude response missing \\documentclass — using original")
        tailored_tex = tex_source

    # Guard: verify no numbers from the original were altered
    original_numbers = set(re.findall(r"\b\d+(?:\.\d+)?\b", tex_source))
    tailored_numbers = set(re.findall(r"\b\d+(?:\.\d+)?\b", tailored_tex))
    removed_numbers = original_numbers - tailored_numbers
    if removed_numbers:
        print(
            f"[resume] Warning: {len(removed_numbers)} number(s) from original are missing "
            f"in tailored version: {', '.join(sorted(removed_numbers)[:5])} — review before sending"
        )

    output_dir.mkdir(parents=True, exist_ok=True)

    # Copy any .cls files from the master resume directory so tectonic can find them
    for cls_file in master_tex.parent.glob("*.cls"):
        shutil.copy2(cls_file, output_dir / cls_file.name)

    tex_path = output_dir / f"{output_name}.tex"
    tex_path.write_text(tailored_tex, encoding="utf-8")

    print(f"[resume] Compiling {tex_path.name}")
    pdf_path = compile_tex(tex_path, output_dir=output_dir)

    for attempt in range(1, _MAX_PAGE_RETRIES + 1):
        pages = count_pdf_pages(pdf_path)
        if pages == 1:
            break
        print(f"[resume] PDF is {pages} page(s) — shortening (attempt {attempt}/{_MAX_PAGE_RETRIES})")
        shorten_prompt = _SHORTEN_PROMPT_TEMPLATE.format(
            pages=pages,
            tex_source=tailored_tex,
        )
        tailored_tex = claude_client.ask(shorten_prompt, system=_SYSTEM, max_tokens=8192)
        if "\\documentclass" not in tailored_tex:
            print("[resume] Warning: shorten response missing \\documentclass — stopping early")
            break
        tex_path.write_text(tailored_tex, encoding="utf-8")
        pdf_path = compile_tex(tex_path, output_dir=output_dir)
    else:
        pages = count_pdf_pages(pdf_path)
        if pages > 1:
            print(f"[resume] Warning: resume still {pages} page(s) after {_MAX_PAGE_RETRIES} attempts")

    print(f"[resume] PDF ready: {pdf_path}")
    return tex_path, pdf_path
