"""
PDF generator — Markdown resume → HTML template → Playwright headless PDF.

Uses a single browser session for batch generation to avoid repeated launch overhead.
"""

from __future__ import annotations

import re
from pathlib import Path

from playwright.sync_api import sync_playwright

_TEMPLATE_PATH = Path(__file__).parent.parent / "web" / "templates" / "resume.html"

# Minimal Markdown → HTML conversion for resume content.
# For a resume this subset is sufficient: headings, bold, italic, lists, paragraphs.
_RULES = [
    (re.compile(r"^#{3}\s+(.+)$", re.MULTILINE), r"<h3>\1</h3>"),
    (re.compile(r"^#{2}\s+(.+)$", re.MULTILINE), r"<h2>\1</h2>"),
    (re.compile(r"^#\s+(.+)$", re.MULTILINE), r"<h1>\1</h1>"),
    (re.compile(r"\*\*(.+?)\*\*"), r"<strong>\1</strong>"),
    (re.compile(r"\*(.+?)\*"), r"<em>\1</em>"),
    (re.compile(r"^[-*]\s+(.+)$", re.MULTILINE), r"<li>\1</li>"),
    (re.compile(r"(<li>.*?</li>)", re.DOTALL), r"<ul>\1</ul>"),
    # Consecutive </ul><ul> blocks collapse into one list
    (re.compile(r"</ul>\s*<ul>"), ""),
    (re.compile(r"^(?!<[hul]).+$", re.MULTILINE), r"<p>\g<0></p>"),
    # Remove empty paragraphs
    (re.compile(r"<p>\s*</p>"), ""),
]


def markdown_to_html(md: str) -> str:
    """
    Convert resume Markdown to a full HTML document using the resume template.

    Inlines the template rather than requiring a file read at generation time.
    """
    content = md
    for pattern, replacement in _RULES:
        content = pattern.sub(replacement, content)

    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    return template.replace("{{ content }}", content)


def generate_pdf(
    resume_md_path: Path,
    output_path: Path,
) -> Path:
    """
    Render a Markdown resume to PDF via Playwright headless Chromium.

    Args:
        resume_md_path: Path to the tailored .md resume file.
        output_path: Destination .pdf path (created if parent dirs exist).

    Returns:
        output_path after the PDF has been written.

    Raises:
        FileNotFoundError: If resume_md_path does not exist.
    """
    if not resume_md_path.exists():
        raise FileNotFoundError(f"Resume not found: {resume_md_path}")

    md = resume_md_path.read_text(encoding="utf-8")
    html = markdown_to_html(md)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.set_content(html, wait_until="networkidle")
        page.pdf(
            path=str(output_path),
            format="Letter",
            print_background=True,
        )
        browser.close()

    return output_path


def generate_pdfs_batch(jobs: list[dict]) -> list[Path]:
    """
    Generate PDFs for a list of jobs in a single Playwright browser session.

    Each job dict must have 'tailored_resume_path' and 'url' keys.
    Returns list of generated PDF paths (skips jobs without a resume path).
    """
    results: list[Path] = []

    candidates = [
        j for j in jobs
        if j.get("tailored_resume_path") and Path(j["tailored_resume_path"]).exists()
    ]

    if not candidates:
        return results

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for job in candidates:
            md_path = Path(job["tailored_resume_path"])
            pdf_path = md_path.with_suffix(".pdf")
            try:
                md = md_path.read_text(encoding="utf-8")
                html = markdown_to_html(md)
                page = browser.new_page()
                page.set_content(html, wait_until="networkidle")
                page.pdf(path=str(pdf_path), format="Letter", print_background=True)
                page.close()
                results.append(pdf_path)
            except Exception as e:
                print(f"[pdf_generator] Failed for {job.get('company')}/{job.get('title')}: {e}")
        browser.close()

    return results
