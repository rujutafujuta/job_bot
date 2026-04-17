"""Remotive scraper — free public API for remote jobs."""

from __future__ import annotations

from src.scrapers.base import BaseScraper, JobPosting

_API_URL = "https://remotive.com/api/remote-jobs"


class RemotiveScraper(BaseScraper):
    source_name = "remotive"

    def scrape(self, queries: list[str]) -> list[JobPosting]:
        results: list[JobPosting] = []
        seen_urls: set[str] = set()

        for role in queries:
            if len(results) >= self._max_jobs:
                break
            params = {"search": role, "limit": 20}
            try:
                resp = self._get(_API_URL, params=params)
                data = resp.json()
            except Exception as e:
                print(f"[remotive] Error fetching role '{role}': {e}")
                continue

            for job in data.get("jobs", []):
                url = job.get("url", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)

                results.append(JobPosting(
                    title=job.get("title", ""),
                    company=job.get("company_name", ""),
                    location="Remote",
                    url=url,
                    description=job.get("description", "") or job.get("title", ""),
                    source=self.source_name,
                    date_posted=job.get("publication_date", ""),
                    salary_range=job.get("salary", "") or "",
                ))

                if len(results) >= self._max_jobs:
                    break

        print(f"[remotive] {len(results)} remote jobs found")
        return results
