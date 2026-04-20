"""Cold outreach — Claude-generated draft saved to DB. User sends manually."""

from __future__ import annotations

from pathlib import Path

from src.scrapers.base import JobPosting
from src.pipeline.contact_finder import Contact
from src.tracking.db import (
    _DEFAULT_DB,
    count_outreach_for_company,
    get_job,
    save_outreach_draft,
)
from src.utils.claude_runner import run_claude

_DEFAULT_MAX_PER_COMPANY = 2
_PENDING_DIR = Path("data/pending_outreach")

_SYSTEM = (
    "You are an expert at writing cold emails that get responses. "
    "You write short, specific, non-generic outreach that feels human. "
    "No buzzwords. No filler. The email must feel like it was written specifically for this person."
)

_PROMPT_TEMPLATE = """
Write a cold outreach email from a job applicant to a contact at a company they just applied to.

=== SENDER ===
Name: {full_name}
Email: {email}
Background: {years_experience} years experience in {primary_skills}
LinkedIn: {linkedin}

=== RECIPIENT ===
Name: {contact_name}
Title: {contact_title}
Company: {company}

=== JOB ===
Role: {job_title}
Application link: {job_url}

=== INSTRUCTIONS ===
- Subject line first (prefix with "Subject: ")
- Then a blank line
- Then the email body
- 3-4 sentences max body
- Tone: {tone}
- Reference something specific about the company or role (not generic praise)
- End with a soft ask (e.g. "Happy to send my resume if useful")
- Sign off with name only — signature will be appended
- Do NOT mention "I applied" directly — frame it as reaching out, not chasing
"""


def send_cold_outreach(
    posting: JobPosting,
    contact: Contact,
    profile: dict,
    pdf_resume: Path,
    dry_run: bool = False,
    db_path: Path = _DEFAULT_DB,
) -> dict:
    """Generate a cold outreach draft and save it to the DB. Never sends automatically.

    Returns:
        Dict with keys: status (str), outreach_url (str)
        status values: "pending_user_input" | "skipped_cap"
    """
    max_per_company = profile.get("outreach", {}).get(
        "max_per_company", _DEFAULT_MAX_PER_COMPANY
    )
    current_count = count_outreach_for_company(posting.company, db_path=db_path)
    if current_count >= max_per_company:
        print(
            f"[outreach] Skipping {posting.company} — already have "
            f"{current_count}/{max_per_company} drafts for this company"
        )
        return {"status": "skipped_cap", "outreach_url": ""}

    personal = profile.get("personal", {})
    skills = profile.get("skills", {})
    outreach_cfg = profile.get("outreach", {})

    prompt = _PROMPT_TEMPLATE.format(
        full_name=personal.get("full_name", ""),
        email=personal.get("email", ""),
        years_experience=skills.get("years_experience", 0),
        primary_skills=", ".join(skills.get("primary", [])),
        linkedin=personal.get("linkedin_url", ""),
        contact_name=contact.name or "Hiring Team",
        contact_title=contact.title or "",
        company=posting.company,
        job_title=posting.title,
        job_url=posting.url,
        tone=outreach_cfg.get("cold_email_tone", "friendly"),
    )

    print(f"[outreach] Generating draft for {posting.company}")
    raw_email = run_claude(f"{_SYSTEM}\n\n{prompt}")

    subject, body = _parse_subject_body(raw_email)
    signature = outreach_cfg.get("email_signature", "")
    if signature:
        body = f"{body}\n\n{signature}"

    return _save_draft(posting, contact, subject, body, dry_run, db_path)


def _parse_subject_body(raw: str) -> tuple[str, str]:
    """Extract subject line and body from Claude's formatted response."""
    lines = raw.strip().splitlines()
    subject = ""
    body_lines = []
    past_subject = False

    for line in lines:
        if not past_subject and line.lower().startswith("subject:"):
            subject = line[len("subject:"):].strip()
            past_subject = True
        elif past_subject:
            body_lines.append(line)

    if not subject:
        subject = "Reaching out"
        body_lines = lines

    return subject, "\n".join(body_lines).strip()


def _save_draft(
    posting: JobPosting,
    contact: Contact,
    subject: str,
    body: str,
    dry_run: bool,
    db_path: Path = _DEFAULT_DB,
) -> dict:
    """Save outreach as a DB draft record."""
    if dry_run:
        print(f"[outreach][DRY RUN] Would save draft for {posting.company}")
        return {"status": "pending_user_input", "outreach_url": contact.linkedin_url or ""}

    job = get_job(posting.url, db_path=db_path)
    job_id = job["id"] if job else None

    msg_type = "linkedin" if not contact.email and contact.linkedin_url else "email"
    save_outreach_draft(
        job_id=job_id,
        msg_type=msg_type,
        to_name=contact.name or "",
        to_email=contact.email or "",
        to_linkedin=contact.linkedin_url or "",
        subject=subject,
        body=body,
        db_path=db_path,
    )
    print(f"[outreach] Draft saved for {posting.company}")
    return {"status": "pending_user_input", "outreach_url": contact.linkedin_url or ""}


def migrate_pending_outreach_files(
    pending_dir: Path = _PENDING_DIR,
    db_path: Path = _DEFAULT_DB,
) -> int:
    """One-time import: read legacy .txt files, insert as DB drafts, rename to .migrated."""
    if not pending_dir.exists():
        return 0

    count = 0
    for txt_file in pending_dir.glob("*.txt"):
        try:
            meta = _parse_draft_file(txt_file)
            save_outreach_draft(
                job_id=None,
                msg_type="email",
                to_name=meta.get("contact_name", ""),
                to_email=meta.get("to_email", ""),
                to_linkedin=meta.get("linkedin_url", ""),
                subject=meta.get("subject", ""),
                body=meta.get("body", ""),
                db_path=db_path,
            )
            txt_file.rename(txt_file.with_suffix(".migrated"))
            count += 1
            print(f"[outreach] Migrated {txt_file.name} → DB")
        except Exception as exc:
            print(f"[outreach] Migration failed for {txt_file.name}: {exc}")

    return count


def _parse_draft_file(path: Path) -> dict:
    """Parse a legacy pending_outreach .txt file into a structured dict."""
    lines = path.read_text(encoding="utf-8").splitlines()
    meta: dict = {}
    body_lines: list[str] = []
    past_sep = False
    for line in lines:
        if line == "---":
            past_sep = True
            continue
        if past_sep:
            body_lines.append(line)
        else:
            if line.startswith("TO:"):
                meta["to_email"] = line[3:].strip()
            elif line.startswith("LINKEDIN:"):
                meta["linkedin_url"] = line[9:].strip()
            elif line.startswith("CONTACT:"):
                meta["contact_name"] = line[8:].strip()
            elif line.startswith("SUBJECT:"):
                meta["subject"] = line[8:].strip()
    meta["body"] = "\n".join(body_lines).strip()
    return meta
