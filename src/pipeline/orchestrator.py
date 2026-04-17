"""
Pipeline orchestrator — wires all Slice 1 phases together.

Usage:
    python -m src.pipeline.orchestrator --phase scrape
    python -m src.pipeline.orchestrator --phase scrape --dry-run
    python -m src.pipeline.orchestrator --phase prepare --job-id 42
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from src.pipeline.role_detector import generate_roles, needs_regeneration
from src.pipeline.scraper import run_scrapers
from src.pipeline.stage1_scorer import Stage1Result, route_job, score_job
from src.tracking.db import count_by_status, init_db
from src.tracking.deduplication import is_duplicate
from src.utils.config_loader import load_env, load_profile, validate_env

_DEFAULT_DB = Path("data/tracking.db")
_DEFAULT_PROFILE = Path("config/user_profile.yaml")
_DEFAULT_ROLES = Path("config/target_roles.yaml")
_DEFAULT_CV = Path("data/cv.md")


def run_scrape_phase(
    roles_path: Path = _DEFAULT_ROLES,
    profile_path: Path = _DEFAULT_PROFILE,
    cv_path: Path = _DEFAULT_CV,
    db_path: Path = _DEFAULT_DB,
    dry_run: bool = False,
) -> dict:
    """
    Full automated scrape phase:
      1. Regenerate target_roles.yaml if cv.md changed
      2. Scrape all sources
      3. Deduplicate against DB
      4. Stage 1 score each new job
      5. Route by score: <70 → discard, 70-94 → scored, 95+ → ready

    Returns summary dict with counts.
    """
    if not dry_run:
        init_db(db_path)

    # Step 1 — role detection
    if needs_regeneration(cv_path, roles_path):
        if cv_path.exists():
            print("[orchestrator] cv.md changed — regenerating target_roles.yaml")
            if not dry_run:
                generate_roles(cv_path, roles_path, dry_run=False, force=True)
            else:
                print("[orchestrator] (dry-run) would regenerate target_roles.yaml")
        else:
            print(f"[orchestrator] Warning: {cv_path} not found — skipping role regeneration")

    # Step 2 — scrape
    print("\n[orchestrator] Phase 1: Scraping")
    postings = run_scrapers(
        roles_path=roles_path,
        db_path=db_path,
        dry_run=dry_run,
    )
    print(f"[orchestrator] {len(postings)} new postings to evaluate")

    if not postings:
        _print_summary(0, 0, 0, 0, dry_run)
        return {"scored": 0, "ready": 0, "discarded": 0, "skipped_duplicate": 0}

    # Step 3/4/5 — dedup + score + route
    profile = load_profile(profile_path)
    print("\n[orchestrator] Phase 2: Scoring")

    n_scored = n_ready = n_discarded = n_dup = 0

    for posting in postings:
        # Scraper already deduped against DB, but double-check here for safety
        if is_duplicate(posting.title, posting.company, db_path):
            n_dup += 1
            continue

        result: Stage1Result = score_job(posting, profile)
        print(
            f"[orchestrator] {posting.company} / {posting.title}: "
            f"score={result.score} — {result.reasoning[:60]}"
        )

        if dry_run:
            if result.score >= 95:
                n_ready += 1
            elif result.score >= 70:
                n_scored += 1
            else:
                n_discarded += 1
            continue

        action = route_job(result, posting, db_path)
        if action == "ready":
            n_ready += 1
        elif action == "scored":
            n_scored += 1
        else:
            n_discarded += 1

    _print_summary(n_scored, n_ready, n_discarded, n_dup, dry_run)
    return {
        "scored": n_scored,
        "ready": n_ready,
        "discarded": n_discarded,
        "skipped_duplicate": n_dup,
    }


def run_prepare_phase(job_id: int, db_path: Path = _DEFAULT_DB) -> None:
    """Stub for Slice 2 — on-demand Stage 2 evaluation for a single job."""
    print(f"[orchestrator] prepare phase for job {job_id} — implemented in Slice 2")


def _print_summary(
    scored: int, ready: int, discarded: int, skipped: int, dry_run: bool
) -> None:
    label = "(DRY RUN) " if dry_run else ""
    print(f"\n{'='*60}")
    print(f"  Pipeline {label}complete — {date.today()}")
    print(f"  Ready (95+):      {ready}")
    print(f"  Scored (70-94):   {scored}")
    print(f"  Discarded (<70):  {discarded}")
    print(f"  Already seen:     {skipped}")
    print(f"{'='*60}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Job Bot Pipeline")
    parser.add_argument(
        "--phase",
        choices=["scrape", "prepare"],
        default="scrape",
        help="Pipeline phase to run",
    )
    parser.add_argument("--job-id", type=int, help="Job ID (required for --phase prepare)")
    parser.add_argument("--dry-run", action="store_true", help="Run without writing to DB")
    parser.add_argument("--db", default=str(_DEFAULT_DB), help="Path to SQLite database")
    parser.add_argument("--profile", default=str(_DEFAULT_PROFILE), help="Path to user_profile.yaml")
    parser.add_argument("--roles", default=str(_DEFAULT_ROLES), help="Path to target_roles.yaml")
    parser.add_argument("--cv", default=str(_DEFAULT_CV), help="Path to cv.md")
    args = parser.parse_args()

    load_env()
    validate_env()

    if args.phase == "scrape":
        run_scrape_phase(
            roles_path=Path(args.roles),
            profile_path=Path(args.profile),
            cv_path=Path(args.cv),
            db_path=Path(args.db),
            dry_run=args.dry_run,
        )
    elif args.phase == "prepare":
        if not args.job_id:
            parser.error("--job-id required for --phase prepare")
        run_prepare_phase(job_id=args.job_id, db_path=Path(args.db))
    else:
        parser.error(f"Unknown phase: {args.phase}")


if __name__ == "__main__":
    main()
