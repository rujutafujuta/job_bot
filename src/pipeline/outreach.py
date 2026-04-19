"""Cold outreach — Claude-generated email, sent via SMTP or saved as pending."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

from src.scrapers.base import JobPosting
from src.pipeline.contact_finder import Contact
from src.utils.claude_runner import run_claude
from src.utils.email_sender import send_email

_OUTREACH_LOG = Path("data/outreach_log.json")
_DEFAULT_MAX_PER_COMPANY = 2


def _load_outreach_log(log_path: Path = _OUTREACH_LOG) -> dict:
    if log_path.exists():
        try:
            return json.loads(log_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            print(f"[outreach] Warning: could not parse {log_path} — starting fresh log")
            return {}
    return {}


def _save_outreach_log(data: dict, log_path: Path = _OUTREACH_LOG) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = log_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, log_path)


def outreach_count_for_company(company: str, log_path: Path = _OUTREACH_LOG) -> int:
    """Return how many outreach emails have been sent or saved for this company."""
    key = company.lower().strip()
    return _load_outreach_log(log_path).get(key, 0)


def _record_outreach(company: str, log_path: Path = _OUTREACH_LOG) -> None:
    data = _load_outreach_log(log_path)
    key = company.lower().strip()
    data[key] = data.get(key, 0) + 1
    _save_outreach_log(data, log_path)

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

_PENDING_DIR = Path("data/pending_outreach")


def send_cold_outreach(
    posting: JobPosting,
    contact: Contact,
    profile: dict,
    pdf_resume: Path,
    dry_run: bool = False,
    outreach_log: Path = _OUTREACH_LOG,
) -> dict:
    """
    Generate and send a cold outreach email. Save to pending if email unavailable.

    Returns:
        Dict with keys: status (str), outreach_url (str)
        status values: "sent" | "pending_user_input" | "skipped_cap"
    """
    max_per_company = profile.get("outreach", {}).get(
        "max_per_company", _DEFAULT_MAX_PER_COMPANY
    )
    current_count = outreach_count_for_company(posting.company, outreach_log)
    if current_count >= max_per_company:
        print(
            f"[outreach] Skipping {posting.company} — already sent {current_count}/{max_per_company} "
            f"outreach messages to this company"
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

    print(f"[outreach] Generating email for {posting.company}")
    raw_email = run_claude(f"{_SYSTEM}\n\n{prompt}")

    subject, body = _parse_subject_body(raw_email)
    signature = outreach_cfg.get("email_signature", "")
    if signature:
        body = f"{body}\n\n{signature}"

    require_approval = profile.get("outreach", {}).get("require_approval", True)

    if require_approval:
        print(f"[outreach] require_approval=true — saving draft for {posting.company}")
        return _save_pending(posting, contact, subject, body, pdf_resume, dry_run, outreach_log)

    if not contact.email:
        return _save_pending(posting, contact, subject, body, pdf_resume, dry_run)

    print(f"[outreach] Sending to {contact.email} — {subject}")
    try:
        send_email(
            to=contact.email,
            subject=subject,
            body=body,
            attachments=[pdf_resume],
            dry_run=dry_run,
        )
        if not dry_run:
            _record_outreach(posting.company, outreach_log)
        return {"status": "sent", "outreach_url": contact.linkedin_url or ""}
    except Exception as e:
        print(f"[outreach] Failed to send email: {e} — saving as pending")
        return _save_pending(posting, contact, subject, body, pdf_resume, dry_run, outreach_log)


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


def _save_pending(
    posting: JobPosting,
    contact: Contact,
    subject: str,
    body: str,
    pdf_resume: Path,
    dry_run: bool,
    outreach_log: Path = _OUTREACH_LOG,
) -> dict:
    """Save outreach draft to pending_outreach/ for manual sending."""
    company_slug = re.sub(r"[^\w]", "_", posting.company)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{company_slug}_{timestamp}.txt"

    content = (
        f"TO: {contact.email or '(email not found — search LinkedIn below)'}\n"
        f"LINKEDIN: {contact.linkedin_url or ''}\n"
        f"CONTACT: {contact.name} — {contact.title}\n"
        f"SUBJECT: {subject}\n"
        f"RESUME: {pdf_resume}\n"
        f"---\n{body}"
    )

    if not dry_run:
        _PENDING_DIR.mkdir(parents=True, exist_ok=True)
        (_PENDING_DIR / filename).write_text(content, encoding="utf-8")
        _record_outreach(posting.company, outreach_log)
        print(f"[outreach] Saved pending outreach: {filename}")
    else:
        print(f"[outreach][DRY RUN] Would save pending outreach for {posting.company}")

    return {
        "status": "pending_user_input",
        "outreach_url": contact.linkedin_url or "",
    }
