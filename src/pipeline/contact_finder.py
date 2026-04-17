"""Hiring manager contact finder — Hunter.io API with LinkedIn URL fallback."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import requests


@dataclass
class Contact:
    name: str = ""
    email: str = ""
    linkedin_url: str = ""
    title: str = ""
    found: bool = False


def find_contact(company: str, job_url: str) -> Contact:
    """
    Find a hiring manager or relevant contact at the company.

    Tries Hunter.io first; falls back to a LinkedIn search URL.

    Args:
        company: Company name.
        job_url: Job posting URL (used to extract domain).

    Returns:
        Contact dataclass. contact.found = False if nothing found.
    """
    hunter_key = os.environ.get("HUNTER_IO_API_KEY")
    if hunter_key:
        contact = _hunter_lookup(company, job_url, hunter_key)
        if contact.found:
            return contact

    # Fallback: build LinkedIn people search URL
    linkedin_url = _linkedin_search_url(company)
    print(f"[contact] Hunter.io found nothing for {company} — returning LinkedIn search URL")
    return Contact(linkedin_url=linkedin_url, found=False)


def _extract_domain(job_url: str) -> str:
    """Extract root domain from a URL, stripping www."""
    try:
        parsed = urlparse(job_url)
        domain = parsed.netloc.lower()
        domain = re.sub(r"^www\.", "", domain)
        # Strip ATS subdomains (boards.greenhouse.io → company-specific domain unavailable)
        known_ats_domains = {
            "greenhouse.io", "lever.co", "myworkdayjobs.com", "icims.com",
            "taleo.net", "smartrecruiters.com", "ashbyhq.com",
        }
        if any(domain.endswith(d) for d in known_ats_domains):
            return ""
        return domain
    except Exception:
        return ""


def _hunter_lookup(company: str, job_url: str, api_key: str) -> Contact:
    domain = _extract_domain(job_url)
    if not domain:
        print(f"[contact] Cannot extract domain from {job_url}, skipping Hunter.io")
        return Contact()

    try:
        response = requests.get(
            "https://api.hunter.io/v2/domain-search",
            params={
                "domain": domain,
                "company": company,
                "type": "personal",
                "limit": 5,
                "api_key": api_key,
            },
            timeout=10,
        )
        response.raise_for_status()
        data = response.json().get("data", {})
        emails = data.get("emails", [])

        if not emails:
            return Contact()

        # Prefer engineering/recruiting/HR titles
        priority_keywords = ["engineer", "recruit", "talent", "hr", "people", "head", "manager"]
        best = None
        for email_entry in emails:
            title = (email_entry.get("position") or "").lower()
            if any(kw in title for kw in priority_keywords):
                best = email_entry
                break
        if best is None:
            best = emails[0]

        return Contact(
            name=f"{best.get('first_name', '')} {best.get('last_name', '')}".strip(),
            email=best.get("value", ""),
            title=best.get("position", ""),
            found=True,
        )
    except requests.RequestException as e:
        print(f"[contact] Hunter.io request failed for {company}: {e}")
        return Contact()


def _linkedin_search_url(company: str) -> str:
    company_encoded = company.replace(" ", "%20")
    return (
        f"https://www.linkedin.com/search/results/people/"
        f"?keywords={company_encoded}%20recruiter%20OR%20engineer%20OR%20hiring"
        f"&origin=GLOBAL_SEARCH_HEADER"
    )
