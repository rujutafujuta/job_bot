"""Tests for scraper_runs table and health functions in db.py."""

from __future__ import annotations

import pytest
from pathlib import Path

from src.tracking.db import (
    init_db,
    record_scraper_run,
    get_scraper_health,
    get_stale_scrapers,
)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


class TestRecordScraperRun:
    def test_inserts_row(self, db):
        record_scraper_run(
            source="himalayas",
            jobs_found=10,
            jobs_passed_stage1=5,
            error_message=None,
            duration_seconds=3.2,
            db_path=db,
        )
        health = get_scraper_health(db_path=db)
        assert any(r["source"] == "himalayas" for r in health)

    def test_records_error_message(self, db):
        record_scraper_run(
            source="apify",
            jobs_found=0,
            jobs_passed_stage1=0,
            error_message="Timeout",
            duration_seconds=60.0,
            db_path=db,
        )
        health = get_scraper_health(db_path=db)
        apify = next(r for r in health if r["source"] == "apify")
        assert apify["last_error"] == "Timeout"

    def test_multiple_runs_same_source(self, db):
        for i in range(3):
            record_scraper_run(
                source="remotive",
                jobs_found=i * 2,
                jobs_passed_stage1=i,
                error_message=None,
                duration_seconds=1.0,
                db_path=db,
            )
        health = get_scraper_health(db_path=db)
        remotive = next(r for r in health if r["source"] == "remotive")
        assert remotive["last_jobs_found"] == 4


class TestGetScraperHealth:
    def test_empty_returns_empty_list(self, db):
        assert get_scraper_health(db_path=db) == []

    def test_returns_one_row_per_source(self, db):
        for source in ("himalayas", "remotive", "apify"):
            record_scraper_run(
                source=source, jobs_found=5, jobs_passed_stage1=2,
                error_message=None, duration_seconds=1.0, db_path=db,
            )
        health = get_scraper_health(db_path=db)
        sources = {r["source"] for r in health}
        assert sources == {"himalayas", "remotive", "apify"}

    def test_row_has_required_fields(self, db):
        record_scraper_run(
            source="adzuna", jobs_found=3, jobs_passed_stage1=1,
            error_message=None, duration_seconds=2.5, db_path=db,
        )
        row = get_scraper_health(db_path=db)[0]
        for field in ("source", "last_run_date", "last_jobs_found", "consecutive_zero_days"):
            assert field in row

    def test_consecutive_zero_days_counted(self, db):
        for _ in range(3):
            record_scraper_run(
                source="jobicy", jobs_found=0, jobs_passed_stage1=0,
                error_message=None, duration_seconds=1.0, db_path=db,
            )
        health = get_scraper_health(db_path=db)
        jobicy = next(r for r in health if r["source"] == "jobicy")
        assert jobicy["consecutive_zero_days"] >= 3

    def test_nonzero_run_resets_zero_streak(self, db):
        for _ in range(2):
            record_scraper_run(
                source="simplify", jobs_found=0, jobs_passed_stage1=0,
                error_message=None, duration_seconds=1.0, db_path=db,
            )
        record_scraper_run(
            source="simplify", jobs_found=5, jobs_passed_stage1=2,
            error_message=None, duration_seconds=1.0, db_path=db,
        )
        health = get_scraper_health(db_path=db)
        simplify = next(r for r in health if r["source"] == "simplify")
        assert simplify["consecutive_zero_days"] == 0


class TestGetStaleScrapers:
    def test_empty_when_no_runs(self, db):
        assert get_stale_scrapers(threshold_days=3, db_path=db) == []

    def test_returns_stale_source(self, db):
        for _ in range(4):
            record_scraper_run(
                source="remoteok", jobs_found=0, jobs_passed_stage1=0,
                error_message=None, duration_seconds=1.0, db_path=db,
            )
        stale = get_stale_scrapers(threshold_days=3, db_path=db)
        assert "remoteok" in stale

    def test_healthy_source_not_stale(self, db):
        record_scraper_run(
            source="himalayas", jobs_found=10, jobs_passed_stage1=5,
            error_message=None, duration_seconds=1.0, db_path=db,
        )
        stale = get_stale_scrapers(threshold_days=3, db_path=db)
        assert "himalayas" not in stale

    def test_threshold_respected(self, db):
        for _ in range(2):
            record_scraper_run(
                source="adzuna", jobs_found=0, jobs_passed_stage1=0,
                error_message=None, duration_seconds=1.0, db_path=db,
            )
        assert get_stale_scrapers(threshold_days=3, db_path=db) == []
        assert "adzuna" in get_stale_scrapers(threshold_days=2, db_path=db)
