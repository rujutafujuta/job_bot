"""Tests for rejection_analyzer.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.pipeline.rejection_analyzer import run_rejection_analysis
from src.tracking.db import init_db, insert_job


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


def _job(url, status="rejected", **kwargs) -> dict:
    base = {
        "url": url,
        "title": "Engineer",
        "company": "Acme",
        "status": status,
        "dedup_hash": url,
        "stage1_score": 75,
        "stage2_score": 70,
        "applied_date": "2026-03-01",
        "date_posted": "2026-02-20",
    }
    base.update(kwargs)
    return base


class TestRunRejectionAnalysis:
    def test_raises_when_fewer_than_3_jobs(self, db, tmp_path):
        insert_job(_job("https://a.com/1"), db)
        insert_job(_job("https://a.com/2"), db)
        with pytest.raises(ValueError, match="at least 3"):
            run_rejection_analysis(db, tmp_path / "reports")

    def test_raises_on_empty_db(self, db, tmp_path):
        with pytest.raises(ValueError, match="at least 3"):
            run_rejection_analysis(db, tmp_path / "reports")

    def test_returns_path_on_enough_jobs(self, db, tmp_path):
        for i in range(3):
            insert_job(_job(f"https://a.com/{i}"), db)
        with patch("src.pipeline.rejection_analyzer.run_claude", return_value="# Report\nAnalysis here."):
            result = run_rejection_analysis(db, tmp_path / "reports")
        assert isinstance(result, Path)

    def test_report_file_written_to_disk(self, db, tmp_path):
        reports_dir = tmp_path / "reports"
        for i in range(3):
            insert_job(_job(f"https://a.com/{i}"), db)
        with patch("src.pipeline.rejection_analyzer.run_claude", return_value="## Analysis"):
            result = run_rejection_analysis(db, reports_dir)
        assert result.exists()
        assert result.stat().st_size > 0

    def test_report_filename_contains_date(self, db, tmp_path):
        reports_dir = tmp_path / "reports"
        for i in range(3):
            insert_job(_job(f"https://a.com/{i}"), db)
        with patch("src.pipeline.rejection_analyzer.run_claude", return_value="## Analysis"):
            result = run_rejection_analysis(db, reports_dir)
        import re
        assert re.search(r"\d{4}-\d{2}-\d{2}", result.name)

    def test_report_contains_claude_output(self, db, tmp_path):
        reports_dir = tmp_path / "reports"
        for i in range(3):
            insert_job(_job(f"https://a.com/{i}"), db)
        expected = "## Actionable Recommendations\nImprove your resume."
        with patch("src.pipeline.rejection_analyzer.run_claude", return_value=expected):
            result = run_rejection_analysis(db, reports_dir)
        assert result.read_text(encoding="utf-8") == expected

    def test_includes_ghosted_jobs(self, db, tmp_path):
        insert_job(_job("https://a.com/1", status="rejected"), db)
        insert_job(_job("https://a.com/2", status="ghosted"), db)
        insert_job(_job("https://a.com/3", status="withdrawn"), db)
        with patch("src.pipeline.rejection_analyzer.run_claude", return_value="ok") as mock_claude:
            run_rejection_analysis(db, tmp_path / "reports")
        prompt_arg = mock_claude.call_args[0][0]
        assert "ghosted" in prompt_arg
        assert "withdrawn" in prompt_arg

    def test_reports_dir_created_if_missing(self, db, tmp_path):
        reports_dir = tmp_path / "new" / "nested" / "reports"
        for i in range(3):
            insert_job(_job(f"https://a.com/{i}"), db)
        with patch("src.pipeline.rejection_analyzer.run_claude", return_value="done"):
            run_rejection_analysis(db, reports_dir)
        assert reports_dir.exists()

    def test_exactly_3_jobs_is_enough(self, db, tmp_path):
        for i in range(3):
            insert_job(_job(f"https://a.com/{i}"), db)
        with patch("src.pipeline.rejection_analyzer.run_claude", return_value="report"):
            result = run_rejection_analysis(db, tmp_path / "reports")
        assert result.exists()

    def test_report_excerpt_included_when_file_exists(self, db, tmp_path):
        reports_dir = tmp_path / "reports"
        report_file = tmp_path / "eval_report.md"
        report_file.write_text("EXPERT EVAL: Strong candidate but missing Kubernetes.", encoding="utf-8")
        for i in range(3):
            extra = {"evaluation_report_path": str(report_file)} if i == 0 else {}
            insert_job(_job(f"https://a.com/{i}", **extra), db)
        with patch("src.pipeline.rejection_analyzer.run_claude", return_value="analysis") as mock_claude:
            run_rejection_analysis(db, reports_dir)
        prompt_arg = mock_claude.call_args[0][0]
        assert "EXPERT EVAL" in prompt_arg
