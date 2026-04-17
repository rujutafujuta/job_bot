"""Base scraper interface with rate limiting."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import requests


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
            or "Mozilla/5.0 (compatible; job-bot/1.0; personal use)"
        )

    def _get(self, url: str, **kwargs) -> requests.Response:
        """Rate-limited GET with user-agent header."""
        if self._delay > 0:
            time.sleep(self._delay)
        headers = {"User-Agent": self._user_agent, **kwargs.pop("headers", {})}
        response = requests.get(url, headers=headers, timeout=15, **kwargs)
        response.raise_for_status()
        return response

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
