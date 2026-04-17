"""Tests for stage1_scorer — Claude subprocess fast-filter scoring."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.pipeline.stage1_scorer import Stage1Result, route_job, score_job
from src.scrapers.base import JobPosting
from src.tracking.db import init_db, is_discarded, get_job


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


@pytest.fixture
def posting():
    return JobPosting(
        title="ML Engineer",
        company="OpenAI",
        location="Remote",
        url="https://openai.com/jobs/1",
        description="Build large language models. Requires PyTorch experience.",
        source="himalayas",
    )


@pytest.fixture
def profile():
    return {
        "personal": {"full_name": "Jane Doe"},
        "target": {"roles": ["ML Engineer"], "remote_preference": "remote"},
        "skills": {"primary": ["PyTorch", "Python"], "years_experience": 4},
        "cover_letter_context": {"motivation": "Passionate about AI safety"},
    }


VALID_CLAUDE_RESPONSE = '{"score": 85, "reasoning": "Strong PyTorch match. Remote role fits preference."}'
LOW_SCORE_RESPONSE = '{"score": 45, "reasoning": "Requires 10 years experience. Over-qualified threshold."}'
HIGH_SCORE_RESPONSE = '{"score": 97, "reasoning": "Perfect match on all dimensions."}'


class TestScoreJob:
    def test_returns_stage1_result(self, posting, profile):
        with patch("src.pipeline.stage1_scorer.run_claude", return_value=VALID_CLAUDE_RESPONSE):
            result = score_job(posting, profile)

        assert isinstance(result, Stage1Result)
        assert result.score == 85
        assert isinstance(result.reasoning, str)
        assert len(result.reasoning) > 0

    def test_passes_job_description_in_prompt(self, posting, profile):
        with patch("src.pipeline.stage1_scorer.run_claude", return_value=VALID_CLAUDE_RESPONSE) as mock_run:
            score_job(posting, profile)

        prompt = mock_run.call_args[0][0]
        assert "PyTorch" in prompt or "large language models" in prompt

    def test_no_web_tools_passed(self, posting, profile):
        with patch("src.pipeline.stage1_scorer.run_claude", return_value=VALID_CLAUDE_RESPONSE) as mock_run:
            score_job(posting, profile)

        # tools kwarg should be None or not include WebSearch
        call_kwargs = mock_run.call_args[1] if mock_run.call_args[1] else {}
        tools = call_kwargs.get("tools") or (mock_run.call_args[0][1] if len(mock_run.call_args[0]) > 1 else None)
        if tools:
            assert "WebSearch" not in tools
            assert "WebFetch" not in tools

    def test_handles_malformed_json_gracefully(self, posting, profile):
        with patch("src.pipeline.stage1_scorer.run_claude", return_value="not valid json at all"):
            result = score_job(posting, profile)

        assert isinstance(result, Stage1Result)
        assert result.score == 0

    def test_handles_missing_score_field(self, posting, profile):
        with patch("src.pipeline.stage1_scorer.run_claude", return_value='{"reasoning": "no score"}'):
            result = score_job(posting, profile)

        assert result.score == 0

    def test_truncates_long_description(self, profile):
        long_posting = JobPosting(
            title="Dev", company="X", location="Remote",
            url="https://x.com/1",
            description="x" * 10000,
            source="test",
        )
        with patch("src.pipeline.stage1_scorer.run_claude", return_value=VALID_CLAUDE_RESPONSE) as mock_run:
            score_job(long_posting, profile)

        prompt = mock_run.call_args[0][0]
        assert len(prompt) < 15000


class TestRouteJob:
    def test_below_70_marks_discarded_and_does_not_insert_job(self, posting, db):
        result = Stage1Result(score=45, reasoning="poor fit")
        route_job(result, posting, db)

        from src.tracking.deduplication import compute_hash
        h = compute_hash(posting.title, posting.company)
        assert is_discarded(h, db)
        assert get_job(posting.url, db) is None

    def test_score_70_to_94_inserts_with_status_scored(self, posting, db):
        result = Stage1Result(score=82, reasoning="good fit")
        route_job(result, posting, db)

        job = get_job(posting.url, db)
        assert job is not None
        assert job["status"] == "scored"
        assert job["stage1_score"] == 82

    def test_score_95_plus_inserts_with_status_ready(self, posting, db):
        result = Stage1Result(score=97, reasoning="perfect fit")
        route_job(result, posting, db)

        job = get_job(posting.url, db)
        assert job is not None
        assert job["status"] == "ready"

    def test_score_exactly_70_is_scored_not_discarded(self, posting, db):
        result = Stage1Result(score=70, reasoning="borderline")
        route_job(result, posting, db)

        job = get_job(posting.url, db)
        assert job is not None
        assert job["status"] == "scored"

    def test_score_exactly_95_is_ready(self, posting, db):
        result = Stage1Result(score=95, reasoning="strong match")
        route_job(result, posting, db)

        job = get_job(posting.url, db)
        assert job["status"] == "ready"

    def test_discarded_job_not_inserted_into_jobs_table(self, posting, db):
        result = Stage1Result(score=60, reasoning="weak")
        route_job(result, posting, db)

        assert get_job(posting.url, db) is None

    def test_reasoning_stored_on_scored_job(self, posting, db):
        result = Stage1Result(score=80, reasoning="Strong ML skills match")
        route_job(result, posting, db)

        job = get_job(posting.url, db)
        assert job["stage1_reasoning"] == "Strong ML skills match"
