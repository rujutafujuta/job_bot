"""Tests for liveness.py — URL dead-link detection."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import requests

from src.pipeline.liveness import check_liveness, _is_dead
from src.tracking.db import init_db, insert_job, get_job


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


class TestIsDead:
    def test_404_is_dead(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        with patch("src.pipeline.liveness.requests.head", return_value=mock_resp):
            assert _is_dead("https://example.com/job/1") is True

    def test_410_is_dead(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 410
        with patch("src.pipeline.liveness.requests.head", return_value=mock_resp):
            assert _is_dead("https://example.com/job/1") is True

    def test_200_is_alive(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("src.pipeline.liveness.requests.head", return_value=mock_resp):
            assert _is_dead("https://example.com/job/1") is False

    def test_301_redirect_is_alive(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 301
        with patch("src.pipeline.liveness.requests.head", return_value=mock_resp):
            assert _is_dead("https://example.com/job/1") is False

    def test_connection_error_is_dead(self):
        with patch("src.pipeline.liveness.requests.head", side_effect=requests.RequestException("timeout")):
            assert _is_dead("https://example.com/job/1") is True


class TestCheckLiveness:
    def test_marks_dead_job_as_discarded(self, db):
        insert_job({"url": "https://example.com/job/1", "title": "Dev", "company": "X", "status": "scored"}, db)
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        with patch("src.pipeline.liveness.requests.head", return_value=mock_resp):
            result = check_liveness(db)
        job = get_job("https://example.com/job/1", db)
        assert job["status"] == "discarded"
        assert result["killed"] == 1

    def test_leaves_live_job_unchanged(self, db):
        insert_job({"url": "https://example.com/job/1", "title": "Dev", "company": "X", "status": "ready"}, db)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("src.pipeline.liveness.requests.head", return_value=mock_resp):
            result = check_liveness(db)
        job = get_job("https://example.com/job/1", db)
        assert job["status"] == "ready"
        assert result["killed"] == 0

    def test_skips_applied_jobs(self, db):
        insert_job({"url": "https://example.com/job/1", "title": "Dev", "company": "X", "status": "applied"}, db)
        with patch("src.pipeline.liveness.requests.head") as mock_head:
            check_liveness(db)
        mock_head.assert_not_called()

    def test_returns_checked_and_killed_counts(self, db):
        insert_job({"url": "https://a.com/1", "title": "A", "company": "X", "status": "scored"}, db)
        insert_job({"url": "https://b.com/2", "title": "B", "company": "Y", "status": "ready"}, db)

        def _mock_head(url, **_):
            r = MagicMock()
            r.status_code = 404 if "a.com" in url else 200
            return r

        with patch("src.pipeline.liveness.requests.head", side_effect=_mock_head):
            result = check_liveness(db)

        assert result["checked"] == 2
        assert result["killed"] == 1
