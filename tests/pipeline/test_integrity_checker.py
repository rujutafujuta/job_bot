"""Tests for integrity_checker.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.pipeline.integrity_checker import get_latest_integrity_result, run_integrity_check
from src.tracking.db import init_db, insert_job


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


def _job(url="https://example.com/1", **kwargs) -> dict:
    base = {
        "url": url,
        "title": "Engineer",
        "company": "Acme",
        "status": "scored",
        "dedup_hash": url,
    }
    base.update(kwargs)
    return base


class TestRunIntegrityCheck:
    def test_passes_on_empty_db(self, db, tmp_path):
        result = run_integrity_check(db)
        assert result["passed"] is True
        assert result["failures"] == []

    def test_passes_on_clean_data(self, db):
        insert_job(_job(url="https://a.com/1", dedup_hash="abc", status="scored"), db)
        insert_job(_job(url="https://a.com/2", dedup_hash="def", status="ready"), db)
        result = run_integrity_check(db)
        assert result["passed"] is True

    def test_fails_on_duplicate_active_hash(self, db):
        insert_job(_job(url="https://a.com/1", dedup_hash="same", status="scored"), db)
        insert_job(_job(url="https://a.com/2", dedup_hash="same", status="ready"), db)
        result = run_integrity_check(db)
        assert result["passed"] is False
        assert any("Duplicate active dedup_hash" in f for f in result["failures"])

    def test_warns_on_ready_job_missing_report(self, db):
        insert_job(_job(
            url="https://a.com/1",
            dedup_hash="h1",
            status="ready",
            evaluation_report_path="",
            tailored_resume_path="",
        ), db)
        result = run_integrity_check(db)
        assert any("missing evaluation report" in w for w in result["warnings"])

    def test_warns_on_applied_job_missing_followup(self, db):
        insert_job(_job(
            url="https://a.com/1",
            dedup_hash="h1",
            status="applied",
            applied_date="2026-04-01",
            follow_up_1_date="",
        ), db)
        result = run_integrity_check(db)
        assert any("missing follow-up dates" in w for w in result["warnings"])

    def test_no_warning_on_applied_with_followup(self, db):
        insert_job(_job(
            url="https://a.com/1",
            dedup_hash="h1",
            status="applied",
            applied_date="2026-04-01",
            follow_up_1_date="2026-04-08",
        ), db)
        result = run_integrity_check(db)
        assert not any("missing follow-up" in w for w in result["warnings"])

    def test_log_written_to_disk(self, db, tmp_path, monkeypatch):
        log_dir = tmp_path / "logs"
        monkeypatch.setattr("src.pipeline.integrity_checker._LOGS_DIR", log_dir)
        result = run_integrity_check(db)
        assert result["log_path"].exists()

    def test_result_has_required_keys(self, db):
        result = run_integrity_check(db)
        assert "passed" in result
        assert "failures" in result
        assert "warnings" in result
        assert "log_path" in result


class TestGetLatestIntegrityResult:
    def test_returns_none_when_no_logs(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.pipeline.integrity_checker._LOGS_DIR", tmp_path / "nologs")
        assert get_latest_integrity_result() is None

    def test_returns_summary_after_check(self, db, tmp_path, monkeypatch):
        log_dir = tmp_path / "logs"
        monkeypatch.setattr("src.pipeline.integrity_checker._LOGS_DIR", log_dir)
        run_integrity_check(db)
        result = get_latest_integrity_result()
        assert result is not None
        assert "passed" in result
        assert "failure_count" in result
        assert "warning_count" in result

    def test_passed_true_on_clean_db(self, db, tmp_path, monkeypatch):
        log_dir = tmp_path / "logs"
        monkeypatch.setattr("src.pipeline.integrity_checker._LOGS_DIR", log_dir)
        run_integrity_check(db)
        result = get_latest_integrity_result()
        assert result["passed"] is True
        assert result["failure_count"] == 0
