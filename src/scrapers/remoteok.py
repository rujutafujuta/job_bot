"""RemoteOK scraper — simple public JSON API."""

from __future__ import annotations

from src.scrapers.base import BaseScraper, JobPosting

_API_URL = "https://remoteok.io/api"


def _query_matches(position: str, queries: list[str]) -> bool:
    pos_lower = position.lower()
    return any(
        any(word in pos_lower for word in q.lower().split() if len(word) > 3)
        for q in queries
    )


class RemoteOKScraper(BaseScraper):
    source_name = "remoteok"

    def scrape(self, queries: list[str]) -> list[JobPosting]:
        # RemoteOK requires a non-bot-looking User-Agent
        try:
            resp = self._get(
                _API_URL,
                headers={"Accept": "application/json"},
            )
            raw = resp.json()
        except Exception as e:
            print(f"[remoteok] Failed to fetch listings: {e}")
            return []

        results: list[JobPosting] = []
        # First item in the array is a metadata/legal notice dict — skip it
        for item in raw[1:]:
            if not isinstance(item, dict):
                continue
            position = item.get("position", "")
            if not _query_matches(position, queries):
                continue

            url = item.get("url", "") or f"https://remoteok.io/remote-jobs/{item.get('id', '')}"
            tags = item.get("tags", [])
            description = item.get("description", "")
            if not description:
                description = f"{position} at {item.get('company', '')}. Tags: {', '.join(tags)}."

            results.append(JobPosting(
                title=position,
                company=item.get("company", ""),
                location="Remote",
                url=url,
                description=description,
                source=self.source_name,
                date_posted=item.get("date", ""),
                salary_range=item.get("salary_min", "") and
                             f"${item.get('salary_min')}–${item.get('salary_max')}" or "",
            ))

            if len(results) >= self._max_jobs:
                break

        print(f"[remoteok] {len(results)} matching remote jobs found")
        return results
