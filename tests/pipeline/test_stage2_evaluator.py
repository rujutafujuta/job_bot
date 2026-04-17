"""Tests for stage2_evaluator.py — mocks claude_runner."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.pipeline.stage2_evaluator import (
    Stage2Result,
    _parse_legitimacy,
    _build_report_path,
    evaluate_job,
)


@pytest.fixture
def sample_job():
    return {
        "id": 1,
        "url": "https://example.com/jobs/1",
        "title": "ML Engineer",
        "company": "Acme",
        "location": "Remote",
        "description": "We are looking for an ML engineer with Python and PyTorch experience.",
        "stage1_score": 97,
        "stage1_reasoning": "Strong ML match",
    }


@pytest.fixture
def sample_profile():
    return {
        "personal": {"full_name": "Jane Doe"},
        "target": {"roles": ["ML Engineer"], "remote_preference": "remote"},
        "skills": {"primary": ["Python", "PyTorch"], "years_experience": 3},
        "cover_letter_context": {"career_goals": "Build impactful ML systems"},
    }


MOCK_REPORT = """\
## Block A — Role Summary
Acme is a well-funded Series B startup. The role is a core ML position.

## Block B — CV Match + Company Health
Strong match. Candidate has Python and PyTorch. No major gaps.

## Block C — Level Strategy
L4 equivalent. Candidate can present as senior IC.

## Block D — Comp Research
Market rate: $150k–$190k base. Acme pays at market.

## Block E — Personalization Plan
1. Lead with PyTorch experience
2. Highlight distributed training work
3. Reference Acme's recent NLP blog post
4. Emphasize remote collaboration track record
5. Use "production ML systems" framing

## Block F — Interview Prep
Expect system design (ML infra), coding (Python), and culture fit rounds.

**Posting Legitimacy: Verified**
Fresh posting, active company, specific JD language.
"""


class TestParseLegitimacy:
    def test_detects_verified(self):
        assert _parse_legitimacy("**Posting Legitimacy: Verified**\nFresh posting.") == "verified"

    def test_detects_ghost(self):
        assert _parse_legitimacy("Posting Legitimacy: Likely Ghost Posting") == "likely_ghost"

    def test_detects_uncertain(self):
        assert _parse_legitimacy("Posting Legitimacy: Uncertain") == "uncertain"

    def test_defaults_to_uncertain(self):
        assert _parse_legitimacy("No legitimacy signal here.") == "uncertain"


class TestBuildReportPath:
    def test_creates_safe_filename(self, tmp_path):
        path = _build_report_path("Acme Corp", "ML Engineer", tmp_path)
        assert path.parent == tmp_path
        assert "acme" in path.name.lower()
        assert "ml" in path.name.lower()
        assert path.suffix == ".md"

    def test_strips_special_chars(self, tmp_path):
        path = _build_report_path("Acme & Co.", "Sr. ML/AI Engineer", tmp_path)
        assert "/" not in path.name
        assert "&" not in path.name


class TestEvaluateJob:
    def test_returns_stage2_result(self, sample_job, sample_profile, tmp_path):
        with patch("src.pipeline.stage2_evaluator.run_claude", return_value=MOCK_REPORT):
            result = evaluate_job(
                job=sample_job,
                cv_path=tmp_path / "cv.md",
                profile=sample_profile,
                reports_dir=tmp_path,
            )
        assert isinstance(result, Stage2Result)

    def test_writes_report_file(self, sample_job, sample_profile, tmp_path):
        with patch("src.pipeline.stage2_evaluator.run_claude", return_value=MOCK_REPORT):
            result = evaluate_job(
                job=sample_job,
                cv_path=tmp_path / "cv.md",
                profile=sample_profile,
                reports_dir=tmp_path,
            )
        assert result.report_path.exists()
        assert "Block A" in result.report_path.read_text()

    def test_parses_legitimacy_from_report(self, sample_job, sample_profile, tmp_path):
        with patch("src.pipeline.stage2_evaluator.run_claude", return_value=MOCK_REPORT):
            result = evaluate_job(
                job=sample_job,
                cv_path=tmp_path / "cv.md",
                profile=sample_profile,
                reports_dir=tmp_path,
            )
        assert result.legitimacy == "verified"

    def test_score_defaults_to_stage1_on_parse_failure(self, sample_job, sample_profile, tmp_path):
        with patch("src.pipeline.stage2_evaluator.run_claude", return_value="No score here."):
            result = evaluate_job(
                job=sample_job,
                cv_path=tmp_path / "cv.md",
                profile=sample_profile,
                reports_dir=tmp_path,
            )
        assert result.score == sample_job["stage1_score"]

    def test_calls_claude_with_websearch_tools(self, sample_job, sample_profile, tmp_path):
        with patch("src.pipeline.stage2_evaluator.run_claude", return_value=MOCK_REPORT) as mock_run:
            evaluate_job(
                job=sample_job,
                cv_path=tmp_path / "cv.md",
                profile=sample_profile,
                reports_dir=tmp_path,
            )
        called_tools = mock_run.call_args[1].get("tools") or mock_run.call_args[0][1]
        assert "WebSearch" in called_tools

    def test_handles_claude_error_gracefully(self, sample_job, sample_profile, tmp_path):
        from src.utils.claude_runner import ClaudeRunError
        with patch("src.pipeline.stage2_evaluator.run_claude", side_effect=ClaudeRunError("timeout")):
            result = evaluate_job(
                job=sample_job,
                cv_path=tmp_path / "cv.md",
                profile=sample_profile,
                reports_dir=tmp_path,
            )
        assert result.score == 0
        assert result.error is not None
