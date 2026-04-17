"""Himalayas scraper — free structured REST API, no auth required."""

from __future__ import annotations

from src.scrapers.base import BaseScraper, JobPosting

_BASE_URL = "https://himalayas.app/jobs/api"


class HimalayanScraper(BaseScraper):
    source_name = "himalayas"

    def scrape(self, queries: list[str]) -> list[JobPosting]:
        results: list[JobPosting] = []
        seen_urls: set[str] = set()

        for role in queries:
            if len(results) >= self._max_jobs:
                break
            params = {"q": role, "limit": 50}
            try:
                resp = self._get(_BASE_URL, params=params)
                data = resp.json()
            except Exception as e:
                print(f"[himalayas] Error fetching role '{role}': {e}")
                continue

            for job in data.get("jobs", []):
                url = job.get("applicationLink") or job.get("url", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)

                company_obj = job.get("company") or {}
                company = company_obj.get("name", "") if isinstance(company_obj, dict) else str(company_obj)
                title = job.get("title", "")
                description = job.get("description", "") or f"{title} at {company}"
                location = job.get("location", "Remote")
                date_posted = job.get("createdAt", "")
                salary = job.get("salaryRange", "") or ""

                results.append(JobPosting(
                    title=title,
                    company=company,
                    location=location,
                    url=url,
                    description=description,
                    source=self.source_name,
                    date_posted=str(date_posted),
                    salary_range=str(salary) if salary else "",
                ))

                if len(results) >= self._max_jobs:
                    break

        print(f"[himalayas] {len(results)} jobs found")
        return results
