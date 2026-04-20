"""Base scraper interface with rate limiting."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import requests

_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_MAX_RETRIES = 3


@dataclass
class JobPosting:
    title: str
    company: str
    location: str
    url: str
    description: str
    source: str
    date_posted: str = ""
    salary_range: str = ""
    remote: bool = False


class BaseScraper(ABC):
    source_name: str = ""

    _DEFAULT_DELAY = 2
    _DEFAULT_MAX_JOBS = 50

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self._delay = cfg.get("delay_seconds", self._DEFAULT_DELAY)
        self._max_jobs = cfg.get("max_jobs_per_run", self._DEFAULT_MAX_JOBS)
        self._user_agent = (
            cfg.get("user_agent")
            or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )

    def _get(self, url: str, **kwargs) -> requests.Response:
        """Rate-limited GET with user-agent header and exponential backoff on transient errors."""
        if self._delay > 0:
            time.sleep(self._delay)
        headers = {"User-Agent": self._user_agent, **kwargs.pop("headers", {})}
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            response = requests.get(url, headers=headers, timeout=15, **kwargs)
            try:
                response.raise_for_status()
                return response
            except requests.HTTPError as exc:
                status = response.status_code
                if status not in _RETRYABLE_STATUS_CODES or attempt == _MAX_RETRIES:
                    raise
                last_exc = exc
                time.sleep(2 ** attempt)
        raise last_exc  # type: ignore[misc]

    @abstractmethod
    def scrape(self, queries: list[str]) -> list[JobPosting]:
        """
        Scrape job postings for the given search queries.

        Args:
            queries: Search strings from target_roles.yaml, e.g.
                     ["machine learning engineer remote", "ML engineer deep learning"]

        Returns:
            List of JobPosting objects.
        """
        ...
