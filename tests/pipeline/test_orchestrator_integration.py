"""Integration tests for the orchestrator --phase scrape pipeline."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from src.scrapers.base import JobPosting
from src.tracking.db import count_by_status, init_db, is_discarded


@pytest.fixture
def tmp_env(tmp_path):
    """Set up a minimal filesystem environment for orchestrator tests."""
    # CV
    cv = tmp_path / "cv.md"
    cv.write_text("# Jane Doe\nML Engineer, 5 years PyTorch experience.")

    # Roles
    roles = tmp_path / "target_roles.yaml"
    roles.write_text(yaml.dump({
        "generated_from": "cv.md",
        "resume_based": [
            {"title": "ML Engineer", "queries": ["machine learning engineer remote"]}
        ],
        "exploratory": [],
    }))

    # Profile
    profile = tmp_path / "user_profile.yaml"
    profile.write_text(yaml.dump({
        "personal": {"full_name": "Jane Doe", "email": "jane@example.com", "phone": "555-0100"},
        "work_auth": {"type": "US Citizen"},
        "job_preferences": {"job_types": ["full-time"], "remote_preference": "remote only"},
        "skills": {"primary": ["PyTorch", "Python"], "years_experience": 5},
        "target": {"roles": ["ML Engineer"], "industries_excluded": []},
    }))

    # DB
    db = tmp_path / "tracking.db"
    init_db(db)

    return {"cv": cv, "roles": roles, "profile": profile, "db": db, "root": tmp_path}


@pytest.fixture
def sample_postings():
    return [
        JobPosting(
            title="ML Engineer", company="OpenAI",
            location="Remote", url="https://openai.com/jobs/1",
            description="Build LLMs with PyTorch.", source="himalayas",
        ),
        JobPosting(
            title="Data Analyst", company="CorpX",
            location="Office", url="https://corpx.com/jobs/1",
            description="Excel and SQL reporting.", source="remotive",
        ),
        JobPosting(
            title="Research Scientist", company="DeepMind",
            location="Remote", url="https://deepmind.com/jobs/1",
            description="Deep learning research.", source="jobicy",
        ),
    ]


class TestOrchestratorScrapePhase:
    def test_scrape_phase_populates_db(self, tmp_env, sample_postings):
        """High-score job lands in DB as scored or ready; low-score goes to discarded_hashes."""
        from src.pipeline.orchestrator import run_scrape_phase

        def fake_run_scrapers(**kwargs):
            return sample_postings

        def fake_score(posting, profile):
            from src.pipeline.stage1_scorer import Stage1Result
            scores = {
                "https://openai.com/jobs/1": Stage1Result(85, "Strong ML match"),
                "https://corpx.com/jobs/1": Stage1Result(30, "Not a fit"),
                "https://deepmind.com/jobs/1": Stage1Result(97, "Excellent fit"),
            }
            return scores.get(posting.url, Stage1Result(0, "unknown"))

        with (
            patch("src.pipeline.orchestrator.run_scrapers", side_effect=fake_run_scrapers),
            patch("src.pipeline.orchestrator.score_job", side_effect=fake_score),
        ):
            run_scrape_phase(
                roles_path=tmp_env["roles"],
                profile_path=tmp_env["profile"],
                db_path=tmp_env["db"],
                dry_run=False,
            )

        counts = count_by_status(tmp_env["db"])
        assert counts.get("scored", 0) == 1    # OpenAI (85)
        assert counts.get("ready", 0) == 1     # DeepMind (97)

    def test_low_score_job_goes_to_discarded_hashes(self, tmp_env, sample_postings):
        from src.pipeline.orchestrator import run_scrape_phase
        from src.tracking.deduplication import compute_hash

        def fake_run_scrapers(**kwargs):
            return sample_postings

        def fake_score(posting, profile):
            from src.pipeline.stage1_scorer import Stage1Result
            return Stage1Result(30, "Poor fit")  # all low

        with (
            patch("src.pipeline.orchestrator.run_scrapers", side_effect=fake_run_scrapers),
            patch("src.pipeline.orchestrator.score_job", side_effect=fake_score),
        ):
            run_scrape_phase(
                roles_path=tmp_env["roles"],
                profile_path=tmp_env["profile"],
                db_path=tmp_env["db"],
                dry_run=False,
            )

        h = compute_hash("ML Engineer", "OpenAI")
        assert is_discarded(h, tmp_env["db"])

    def test_dry_run_does_not_write_to_db(self, tmp_env, sample_postings):
        from src.pipeline.orchestrator import run_scrape_phase

        def fake_run_scrapers(**kwargs):
            return sample_postings

        def fake_score(posting, profile):
            from src.pipeline.stage1_scorer import Stage1Result
            return Stage1Result(85, "Good match")

        with (
            patch("src.pipeline.orchestrator.run_scrapers", side_effect=fake_run_scrapers),
            patch("src.pipeline.orchestrator.score_job", side_effect=fake_score),
        ):
            run_scrape_phase(
                roles_path=tmp_env["roles"],
                profile_path=tmp_env["profile"],
                db_path=tmp_env["db"],
                dry_run=True,
            )

        counts = count_by_status(tmp_env["db"])
        assert sum(counts.values()) == 0

    def test_duplicate_job_skipped_on_second_run(self, tmp_env):
        from src.pipeline.orchestrator import run_scrape_phase
        from src.tracking.deduplication import compute_hash
        from src.tracking.db import mark_discarded

        # Pre-mark OpenAI as discarded
        h = compute_hash("ML Engineer", "OpenAI")
        mark_discarded(h, "ML Engineer", "OpenAI", "test", tmp_env["db"])

        postings = [
            JobPosting(
                title="ML Engineer", company="OpenAI",
                location="Remote", url="https://openai.com/jobs/99",
                description="New posting same company/title.", source="test",
            )
        ]

        score_called = []

        def fake_run_scrapers(**kwargs):
            return postings

        def fake_score(posting, profile):
            score_called.append(posting.url)
            from src.pipeline.stage1_scorer import Stage1Result
            return Stage1Result(90, "match")

        with (
            patch("src.pipeline.orchestrator.run_scrapers", side_effect=fake_run_scrapers),
            patch("src.pipeline.orchestrator.score_job", side_effect=fake_score),
        ):
            run_scrape_phase(
                roles_path=tmp_env["roles"],
                profile_path=tmp_env["profile"],
                db_path=tmp_env["db"],
            )

        assert len(score_called) == 0
