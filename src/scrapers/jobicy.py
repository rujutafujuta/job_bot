"""Jobicy scraper — no auth required, remote-focused JSON feed."""

from __future__ import annotations

from src.scrapers.base import BaseScraper, JobPosting

_API_URL = "https://jobicy.com/api/v2/remote-jobs"


def _query_matches(title: str, tag: str, queries: list[str]) -> bool:
    combined = f"{title} {tag}".lower()
    return any(
        any(word in combined for word in q.lower().split() if len(word) > 3)
        for q in queries
    )


class JobicyScraper(BaseScraper):
    source_name = "jobicy"
    _DEFAULT_DELAY = 1

    def scrape(self, queries: list[str]) -> list[JobPosting]:
        params = {"count": 50}
        try:
            resp = self._get(_API_URL, params=params)
            data = resp.json()
        except Exception as e:
            print(f"[jobicy] Failed to fetch listings: {e}")
            return []

        results: list[JobPosting] = []
        for job in data.get("jobs", []):
            title = job.get("jobTitle", "")
            tag = job.get("jobTag", "")
            if not _query_matches(title, tag, queries):
                continue

            url = job.get("url", "")
            if not url:
                continue

            results.append(JobPosting(
                title=title,
                company=job.get("companyName", ""),
                location=job.get("jobGeo", "Remote"),
                url=url,
                description=job.get("jobDescription", "") or f"{title} at {job.get('companyName', '')}",
                source=self.source_name,
                date_posted=job.get("pubDate", ""),
                salary_range=job.get("annualSalaryMin", "") and
                             f"${job.get('annualSalaryMin')}–${job.get('annualSalaryMax')}" or "",
                remote=True,
            ))

            if len(results) >= self._max_jobs:
                break

        print(f"[jobicy] {len(results)} matching remote jobs found")
        return results
