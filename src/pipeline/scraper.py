"""Scraper aggregator — loads target_roles.yaml and fans out to all enabled scrapers."""

from __future__ import annotations

from pathlib import Path

import yaml

from src.scrapers.adzuna import AdzunaScraper
from src.scrapers.apify_adapter import ApifyAdapter
from src.scrapers.base import JobPosting
from src.scrapers.himalayas import HimalayanScraper
from src.scrapers.jobicy import JobicyScraper
from src.scrapers.remoteok import RemoteOKScraper
from src.scrapers.remotive import RemotiveScraper
from src.scrapers.simplify import SimplifyJobsScraper
from src.tracking.deduplication import is_duplicate

_DEFAULT_ROLES_PATH = Path("config/target_roles.yaml")

# All scraper classes in priority order.
# Apify is first because it covers high-quality boards (LinkedIn, Indeed, Glassdoor).
_ALL_SCRAPERS: list[type] = [
    ApifyAdapter,
    HimalayanScraper,
    RemotiveScraper,
    RemoteOKScraper,
    SimplifyJobsScraper,
    AdzunaScraper,
    JobicyScraper,
]


def _load_queries(roles_path: Path) -> list[str]:
    """
    Extract all search query strings from target_roles.yaml.

    Returns a flat deduplicated list of queries from both resume_based and
    exploratory sections.
    """
    if not roles_path.exists():
        return []

    data = yaml.safe_load(roles_path.read_text(encoding="utf-8")) or {}
    queries: list[str] = []
    seen: set[str] = set()

    for section in ("resume_based", "exploratory"):
        for role in data.get(section, []):
            for q in role.get("queries", []):
                if q and q not in seen:
                    queries.append(q)
                    seen.add(q)

    return queries


def run_scrapers(
    roles_path: Path = _DEFAULT_ROLES_PATH,
    scraper_overrides: dict | None = None,
    db_path: Path = Path("data/tracking.db"),
    dry_run: bool = False,
) -> list[JobPosting]:
    """
    Run all enabled scrapers and return jobs not yet seen in the database.

    Args:
        roles_path: Path to target_roles.yaml.
        scraper_overrides: Optional per-scraper config overrides (e.g. rate limits).
        db_path: SQLite database path for dedup checks.
        dry_run: If True, logs actions without writing to DB.

    Returns:
        List of new JobPosting objects not yet in the database.
    """
    queries = _load_queries(roles_path)
    if not queries:
        print(f"[scraper] No queries found in {roles_path} — run role_detector first")
        return []

    print(f"[scraper] {len(queries)} search queries loaded from {roles_path}")
    overrides = scraper_overrides or {}
    new_jobs: list[JobPosting] = []
    total_seen = 0

    for scraper_cls in _ALL_SCRAPERS:
        source = scraper_cls.source_name
        cfg = overrides.get(source, {})
        scraper = scraper_cls(config=cfg)

        print(f"[scraper] Running {source}...")
        try:
            postings = scraper.scrape(queries)
        except Exception as e:
            print(f"[scraper] {source}: error — {e}")
            continue

        for posting in postings:
            if not posting.url or not posting.title or not posting.company:
                continue
            if is_duplicate(posting.title, posting.company, db_path):
                total_seen += 1
                continue
            new_jobs.append(posting)

        print(f"[scraper] {source}: {len(postings)} fetched, running total {len(new_jobs)} new")

    print(f"[scraper] Done — {len(new_jobs)} new jobs, {total_seen} already seen")
    return new_jobs
