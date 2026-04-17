"""Adzuna scraper — free API key, 250 requests/day."""

from __future__ import annotations

import os

from src.scrapers.base import BaseScraper, JobPosting

_API_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/1"
_DEFAULT_COUNTRY = "us"


class AdzunaScraper(BaseScraper):
    source_name = "adzuna"
    _DEFAULT_DELAY = 1

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        cfg = config or {}
        self._app_id = os.environ.get("ADZUNA_APP_ID", cfg.get("app_id", ""))
        self._api_key = os.environ.get("ADZUNA_API_KEY", cfg.get("api_key", ""))
        self._country = cfg.get("country", _DEFAULT_COUNTRY)

    def scrape(self, queries: list[str]) -> list[JobPosting]:
        if not self._app_id or not self._api_key:
            print("[adzuna] ADZUNA_APP_ID or ADZUNA_API_KEY not set — skipping")
            return []

        results: list[JobPosting] = []
        seen_urls: set[str] = set()

        for query in queries:
            if len(results) >= self._max_jobs:
                break

            params = {
                "app_id": self._app_id,
                "app_key": self._api_key,
                "what": query,
                "results_per_page": min(50, self._max_jobs - len(results)),
                "sort_by": "date",
                "content-type": "application/json",
            }

            try:
                resp = self._get(
                    _API_URL.format(country=self._country),
                    params=params,
                )
                data = resp.json()
            except Exception as e:
                print(f"[adzuna] Error fetching '{query}': {e}")
                continue

            for job in data.get("results", []):
                url = job.get("redirect_url", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)

                salary_min = job.get("salary_min")
                salary_max = job.get("salary_max")
                salary_str = ""
                if salary_min and salary_max:
                    salary_str = f"${int(salary_min):,}–${int(salary_max):,}"
                elif salary_min:
                    salary_str = f"${int(salary_min):,}+"

                results.append(JobPosting(
                    title=job.get("title", ""),
                    company=job.get("company", {}).get("display_name", ""),
                    location=job.get("location", {}).get("display_name", ""),
                    url=url,
                    description=job.get("description", ""),
                    source=self.source_name,
                    date_posted=job.get("created", ""),
                    salary_range=salary_str,
                ))

                if len(results) >= self._max_jobs:
                    break

        print(f"[adzuna] {len(results)} jobs found")
        return results
