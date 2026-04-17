"""SimplifyJobs scraper — fetches New-Grad-Positions JSON from GitHub.

For each matching listing, we attempt to fetch the real job description by
detecting whether the application URL points to a Greenhouse or Lever board
and querying their public APIs directly. This gives Claude a real JD to score
and tailor against instead of a synthetic summary.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from src.scrapers.base import BaseScraper, JobPosting

_LISTINGS_URL = (
    "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions"
    "/dev/.github/scripts/listings.json"
)

# Greenhouse: boards.greenhouse.io/{token}/jobs/{job_id}
_GH_RE = re.compile(
    r"boards\.greenhouse\.io/(?:embed/job_app\?for=)?([^/?\s]+)"
    r"(?:/jobs/(\d+))?",
    re.IGNORECASE,
)
_GH_JOB_API = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{job_id}?questions=false"

# Lever: jobs.lever.co/{site}/{posting_id}
_LV_RE = re.compile(
    r"jobs\.lever\.co/([^/?\s]+)/([a-f0-9\-]{36})",
    re.IGNORECASE,
)
_LV_JOB_API = "https://api.lever.co/v0/postings/{site}/{posting_id}"


def _query_matches(title: str, queries: list[str]) -> bool:
    title_lower = title.lower()
    return any(
        any(word in title_lower for word in q.lower().split() if len(word) > 3)
        for q in queries
    )


def _strip_html(html: str) -> str:
    if not html:
        return ""
    return BeautifulSoup(html, "lxml").get_text(separator=" ", strip=True)


class SimplifyJobsScraper(BaseScraper):
    source_name = "simplify"

    def _fetch_greenhouse_description(self, url: str) -> str | None:
        """Try to get real JD text from a Greenhouse job URL."""
        m = _GH_RE.search(url)
        if not m:
            return None
        token, job_id = m.group(1), m.group(2)
        if not job_id:
            return None
        api_url = _GH_JOB_API.format(token=token, job_id=job_id)
        try:
            resp = self._get(api_url)
            data = resp.json()
            return _strip_html(data.get("content", "")) or None
        except Exception:
            return None

    def _fetch_lever_description(self, url: str) -> str | None:
        """Try to get real JD text from a Lever job URL."""
        m = _LV_RE.search(url)
        if not m:
            return None
        site, posting_id = m.group(1), m.group(2)
        api_url = _LV_JOB_API.format(site=site, posting_id=posting_id)
        try:
            resp = self._get(api_url)
            data = resp.json()
            plain = data.get("descriptionPlain", "") or ""
            additional = data.get("additionalPlainText", "") or ""
            combined = (plain + "\n" + additional).strip()
            return combined or None
        except Exception:
            return None

    def _fetch_real_description(self, url: str) -> str | None:
        """Attempt to fetch a real job description from a known ATS URL."""
        if not url:
            return None
        if "greenhouse.io" in url:
            return self._fetch_greenhouse_description(url)
        if "lever.co" in url:
            return self._fetch_lever_description(url)
        return None

    def scrape(self, queries: list[str]) -> list[JobPosting]:
        print("[simplify] Fetching New-Grad listings from GitHub...")
        try:
            resp = self._get(_LISTINGS_URL)
            listings = resp.json()
        except Exception as e:
            print(f"[simplify] Failed to fetch listings: {e}")
            return []

        results: list[JobPosting] = []
        for item in listings:
            if not item.get("active", True):
                continue
            title = item.get("title", "")
            if not _query_matches(title, queries):
                continue

            company = item.get("company_name", "")
            job_locations = item.get("locations", [])
            location_str = ", ".join(job_locations) if job_locations else "USA"
            url = item.get("url", "")
            sponsorship = item.get("sponsorship", "")
            date_posted = item.get("date_updated", "")

            # Try to get the real job description from the ATS
            real_desc = self._fetch_real_description(url)
            if real_desc:
                description = real_desc
            else:
                # Fallback synthetic description — still usable for matching
                description = (
                    f"{title} at {company}. "
                    f"Locations: {location_str}. "
                    f"Sponsorship: {sponsorship}."
                )

            results.append(JobPosting(
                title=title,
                company=company,
                location=location_str,
                url=url,
                description=description,
                source=self.source_name,
                date_posted=date_posted,
            ))

            if len(results) >= self._max_jobs:
                break

        real_count = sum(1 for r in results if "Sponsorship:" not in r.description)
        print(
            f"[simplify] {len(results)} matching new-grad roles found "
            f"({real_count} with real JD text)"
        )
        return results
