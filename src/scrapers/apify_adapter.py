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

            # Substitute {roles_first} placeholder in actor_input values (str or list of str)
            actor_input = {}
            for k, v in self._actor_input.items():
                if isinstance(v, str):
                    actor_input[k] = v.replace("{roles_first}", role)
                elif isinstance(v, list):
                    actor_input[k] = [
                        i.replace("{roles_first}", role) if isinstance(i, str) else i
                        for i in v
                    ]
                else:
                    actor_input[k] = v

            url = _RUN_SYNC_URL.format(actor_id=self._actor_id.replace("/", "~"))
            resp = None
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
                body = ""
                try:
                    body = resp.text[:300]
                except Exception:
                    pass
                print(f"[apify] Error running actor for role '{role}': {e}{' — ' + body if body else ''}")
                break  # same input will fail for all roles; stop early

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
