"""Apify cloud actor adapter — generic wrapper for any Apify job scraper actor."""

from __future__ import annotations

import os
import time

import requests

from src.scrapers.base import BaseScraper, JobPosting

_RUN_SYNC_URL = (
    "https://api.apify.com/v2/acts/{actor_id}/run-sync-get-dataset-items"
)
_TIMEOUT = 300  # Apify sync runs can take up to 5 minutes


class ApifyAdapter(BaseScraper):
    source_name = "apify"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._token = os.environ.get("APIFY_TOKEN", "")
        self._actor_id = config.get("actor_id", "")
        self._actor_input: dict = config.get("actor_input", {})
        self._field_map: dict = config.get("field_map", {})

    def scrape(self, queries: list[str]) -> list[JobPosting]:
        if not self._token:
            print("[apify] APIFY_TOKEN not set — skipping")
            return []
        if not self._actor_id:
            print("[apify] actor_id not configured — skipping")
            return []

        results: list[JobPosting] = []
        seen_urls: set[str] = set()

        for role in queries:
            if len(results) >= self._max_jobs:
                break

            # Substitute {roles_first} placeholder in actor_input values
            actor_input = {
                k: v.replace("{roles_first}", role) if isinstance(v, str) else v
                for k, v in self._actor_input.items()
            }

            url = _RUN_SYNC_URL.format(actor_id=self._actor_id)
            try:
                time.sleep(self._delay)
                resp = requests.post(
                    url,
                    json=actor_input,
                    params={"token": self._token},
                    timeout=_TIMEOUT,
                )
                resp.raise_for_status()
                items = resp.json()
            except Exception as e:
                print(f"[apify] Error running actor for role '{role}': {e}")
                continue

            fm = self._field_map
            for item in items:
                job_url = item.get(fm.get("url", "url"), item.get("url", ""))
                if not job_url or job_url in seen_urls:
                    continue
                seen_urls.add(job_url)

                results.append(JobPosting(
                    title=item.get(fm.get("title", "title"), item.get("title", "")),
                    company=item.get(fm.get("company", "company"), item.get("company", "")),
                    location=item.get(fm.get("location", "location"), item.get("location", "")),
                    url=job_url,
                    description=item.get(fm.get("description", "description"), item.get("description", "")),
                    source=self.source_name,
                    date_posted=item.get(fm.get("date_posted", "date_posted"), item.get("datePosted", "")),
                    salary_range=item.get(fm.get("salary_range", "salary"), "") or "",
                ))

                if len(results) >= self._max_jobs:
                    break

        print(f"[apify] {len(results)} jobs found via actor {self._actor_id}")
        return results
