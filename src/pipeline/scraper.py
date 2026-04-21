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
from src.tracking.db import record_scraper_run
from src.tracking.deduplication import is_duplicate
from src.utils.config_loader import load_settings

_DEFAULT_ROLES_PATH = Path("config/target_roles.yaml")

# Non-Apify scrapers in priority order.
_FREE_SCRAPERS: list[type] = [
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
    target_locations: list[str] | None = None,
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
    settings = load_settings()
    scraper_toggles: dict = settings.get("scrapers", {})
    new_jobs: list[JobPosting] = []
    total_seen = 0

    # Build the full list of scrapers: one ApifyAdapter per configured actor, then free scrapers.
    apify_actors: list[dict] = settings.get("apify_actors", [])
    scraper_instances: list = []

    if scraper_toggles.get("apify", True) and apify_actors:
        for actor_cfg in apify_actors:
            scraper_instances.append(ApifyAdapter(config=actor_cfg))
    elif scraper_toggles.get("apify", True) and not apify_actors:
        # Still instantiate once so the "not configured" warning prints
        scraper_instances.append(ApifyAdapter(config={}))

    for scraper_cls in _FREE_SCRAPERS:
        source = scraper_cls.source_name
        if not scraper_toggles.get(source, True):
            print(f"[scraper] {source}: disabled in settings — skipping")
            continue
        cfg = overrides.get(source, {})
        scraper_instances.append(scraper_cls(config=cfg))

    for scraper in scraper_instances:
        source = scraper.source_name

        print(f"[scraper] Running {source}...")
        import time
        _t0 = time.monotonic()
        _error: str | None = None
        try:
            if source == "adzuna" and target_locations is not None:
                postings = scraper.scrape(queries, target_locations=target_locations)
            else:
                postings = scraper.scrape(queries)
        except Exception as e:
            print(f"[scraper] {source}: error — {e}")
            _error = str(e)
            postings = []

        source_new = 0
        for posting in postings:
            if not posting.url or not posting.title or not posting.company:
                continue
            if is_duplicate(posting.title, posting.company, db_path):
                total_seen += 1
                continue
            new_jobs.append(posting)
            source_new += 1

        _duration = time.monotonic() - _t0
        if not dry_run:
            try:
                record_scraper_run(
                    source=source,
                    jobs_found=len(postings),
                    jobs_passed_stage1=source_new,
                    error_message=_error,
                    duration_seconds=round(_duration, 2),
                    db_path=db_path,
                )
            except Exception as rec_exc:
                print(f"[scraper] Warning: could not record health for {source}: {rec_exc}")

        print(f"[scraper] {source}: {len(postings)} fetched, running total {len(new_jobs)} new")

    print(f"[scraper] Done — {len(new_jobs)} new jobs, {total_seen} already seen")
    return new_jobs
