"""
Application automation — opens job URL in Chrome, auto-fills form fields,
prompts user for unknowns, and learns new answers for future runs.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from src.scrapers.base import JobPosting
from src.ats.detector import detect_ats, is_supported
from src.pipeline.form_learner import lookup_field, prompt_and_learn


def apply_to_job(
    posting: JobPosting,
    profile: dict,
    pdf_resume: Path,
    cover_letter: Path | None,
    dry_run: bool = False,
) -> dict:
    """
    Attempt to auto-apply to a job posting via Playwright.

    Opens the application in Chrome, fills all known fields, prompts for unknowns.

    Args:
        posting: The job posting to apply to.
        profile: User profile dict.
        pdf_resume: Path to the tailored PDF resume.
        cover_letter: Optional path to the generated cover letter.
        dry_run: If True, open browser but do not submit.

    Returns:
        Dict with keys: submitted (bool), application_link (str), notes (str)
    """
    # Import here so Playwright is only required when actually applying
    from playwright.sync_api import sync_playwright

    ats = detect_ats(posting.url)
    print(f"[apply] {posting.company} — ATS detected: {ats}")

    if not is_supported(ats):
        print(f"[apply] {posting.company} — ATS '{ats}' not automated, marking as pending user input")
        return {
            "submitted": False,
            "application_link": posting.url,
            "notes": f"Manual application required — ATS: {ats}",
        }

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=False)
        context = browser.new_context()
        page = context.new_page()

        try:
            print(f"[apply] Opening {posting.url}")
            page.goto(posting.url, wait_until="networkidle", timeout=30000)

            result = _fill_form(page, posting, profile, pdf_resume, cover_letter, dry_run)
        except Exception as e:
            print(f"[apply] Error during application for {posting.company}: {e}")
            result = {
                "submitted": False,
                "application_link": posting.url,
                "notes": f"Error: {e}",
            }
        finally:
            if dry_run:
                print("[apply][DRY RUN] Leaving browser open for inspection — press Enter to close")
                input()
            browser.close()

    return result


def _fill_form(page, posting, profile, pdf_resume, cover_letter, dry_run) -> dict:
    """Find and fill all visible form fields on the current page."""
    inputs = page.query_selector_all("input:visible, textarea:visible, select:visible")
    filled = 0
    prompted = 0

    for el in inputs:
        field_type = (el.get_attribute("type") or "text").lower()
        label = _get_label(page, el)

        if field_type == "file":
            # File upload — attach resume or cover letter
            if any(kw in label.lower() for kw in ("resume", "cv", "upload")):
                el.set_input_files(str(pdf_resume))
                filled += 1
            elif cover_letter and any(kw in label.lower() for kw in ("cover", "letter")):
                el.set_input_files(str(cover_letter))
                filled += 1
            continue

        if field_type in ("submit", "button", "image", "hidden", "checkbox", "radio"):
            continue

        value = lookup_field(label, profile)
        if value is None:
            value = prompt_and_learn(label, profile)
            prompted += 1

        value = _coerce_value(label, value, profile)

        try:
            if el.evaluate("el => el.tagName") == "SELECT":
                el.select_option(label=value)
            else:
                el.fill(str(value))
            filled += 1
            time.sleep(0.3)  # Human-like pacing
        except Exception as e:
            print(f"[apply] Could not fill '{label}': {e}")

    print(f"[apply] Filled {filled} fields, prompted user for {prompted}")

    if dry_run:
        print("[apply][DRY RUN] Would submit — skipping")
        return {
            "submitted": False,
            "application_link": page.url,
            "notes": "Dry run — form filled but not submitted",
        }

    # Click submit button
    submit_btn = page.query_selector("button[type=submit], input[type=submit]")
    if submit_btn:
        submit_btn.click()
        page.wait_for_timeout(3000)
        print(f"[apply] Submitted application for {posting.company}")
        return {"submitted": True, "application_link": page.url, "notes": ""}
    else:
        print(f"[apply] Could not find submit button for {posting.company}")
        return {
            "submitted": False,
            "application_link": page.url,
            "notes": "Submit button not found — manual submission required",
        }


def _get_label(page, el) -> str:
    """Derive a human-readable label for a form element."""
    # Try aria-label
    label = el.get_attribute("aria-label") or ""
    if label:
        return label

    # Try associated <label> element
    el_id = el.get_attribute("id")
    if el_id:
        label_el = page.query_selector(f"label[for='{el_id}']")
        if label_el:
            return label_el.inner_text().strip()

    # Try placeholder
    placeholder = el.get_attribute("placeholder") or ""
    if placeholder:
        return placeholder

    # Try name attribute
    return el.get_attribute("name") or "unknown field"


def _coerce_value(label: str, value: str, profile: dict) -> str:
    """Handle special cases like splitting full name into first/last."""
    label_lower = label.lower()
    full_name = profile.get("personal", {}).get("full_name", "")
    parts = full_name.split(" ", 1)

    if "first name" in label_lower or label_lower == "first":
        return parts[0] if parts else value
    if "last name" in label_lower or label_lower == "last":
        return parts[1] if len(parts) > 1 else value

    return value
