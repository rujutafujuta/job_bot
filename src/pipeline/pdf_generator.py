"""
PDF generator — Markdown resume → HTML template → Playwright headless PDF.

Uses a single browser session for batch generation to avoid repeated launch overhead.
"""

from __future__ import annotations

from pathlib import Path

import mistune
from playwright.sync_api import sync_playwright

_TEMPLATE_PATH = Path(__file__).parent.parent / "web" / "templates" / "resume.html"

# escape=False preserves raw HTML in the Markdown (e.g. sr-only keyword spans).
_md_render = mistune.create_markdown(escape=False)


def markdown_to_html(md: str) -> str:
    """
    Convert resume Markdown to a full HTML document using the resume template.

    Uses mistune for robust Markdown parsing (handles nested formatting, edge cases).
    Raw HTML in the Markdown (e.g. <span class="sr-only">) passes through unchanged.
    """
    content = _md_render(md)
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
