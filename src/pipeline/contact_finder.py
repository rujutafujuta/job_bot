"""Hiring manager contact finder — Claude WebSearch."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from src.utils.claude_runner import run_claude

_CONTACT_PROMPT = """\
Search LinkedIn and the company website to find a relevant contact at {company} — \
ideally a hiring manager, engineering manager, recruiter, or talent acquisition person.

Job URL for context: {job_url}

Return ONLY this exact format with no other text or explanation:
NAME: <full name, or "not found">
TITLE: <job title, or leave blank>
EMAIL: <email address, or leave blank>
LINKEDIN: <full linkedin.com/in/... URL, or leave blank>
"""


@dataclass
class Contact:
    name: str = ""
    email: str = ""
    linkedin_url: str = ""
    title: str = ""
    found: bool = False


def find_contact(company: str, job_url: str) -> Contact:
    """Find a hiring manager or recruiter at the company using Claude WebSearch.

    Falls back to a LinkedIn people-search URL if Claude cannot find anyone.
    """
    prompt = _CONTACT_PROMPT.format(company=company, job_url=job_url)
    try:
        raw = run_claude(prompt, tools=["WebSearch"], timeout=60)
        contact = _parse_response(raw)
        if contact.found:
            return contact
    except Exception as exc:
        print(f"[contact] Claude search failed for {company}: {exc}")

    print(f"[contact] No contact found for {company} — returning LinkedIn search URL")
    return Contact(linkedin_url=_linkedin_search_url(company), found=False)


def _parse_response(raw: str) -> Contact:
    """Parse Claude's structured NAME/TITLE/EMAIL/LINKEDIN response."""
    fields: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            fields[key.strip().upper()] = val.strip()

    name = fields.get("NAME", "").strip()
    if not name or name.lower() == "not found":
        return Contact()

    return Contact(
        name=name,
        title=fields.get("TITLE", ""),
        email=fields.get("EMAIL", ""),
        linkedin_url=fields.get("LINKEDIN", ""),
        found=True,
    )


def _linkedin_search_url(company: str) -> str:
    encoded = company.replace(" ", "%20")
    return (
        f"https://www.linkedin.com/search/results/people/"
        f"?keywords={encoded}%20recruiter%20OR%20engineer%20OR%20hiring"
        f"&origin=GLOBAL_SEARCH_HEADER"
    )
