"""Tests for resume_tailor.py — number protection + tailoring."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.pipeline.resume_tailor import (
    extract_numbers,
    validate_numbers,
    tailor_resume,
)


class TestExtractNumbers:
    def test_finds_integers(self):
        assert "42" in extract_numbers("Managed a team of 42 engineers")

    def test_finds_percentages(self):
        assert "98%" in extract_numbers("Achieved 98% accuracy")

    def test_finds_dollar_amounts(self):
        nums = extract_numbers("Saved $1.2M in operational costs")
        assert any("1" in n or "2" in n for n in nums)

    def test_finds_years(self):
        nums = extract_numbers("Graduated in 2021 with 3 years experience")
        assert "2021" in nums
        assert "3" in nums

    def test_returns_set(self):
        assert isinstance(extract_numbers("test 5 values"), set)

    def test_empty_string(self):
        assert extract_numbers("") == set()


class TestValidateNumbers:
    def test_returns_empty_when_all_numbers_present(self):
        cv = "Managed 42 engineers with 98% uptime, saved $1.2M"
        tailored = "Led team of 42 engineers. Achieved 98% uptime. $1.2M savings."
        assert validate_numbers(cv, tailored) == []

    def test_returns_dropped_numbers(self):
        cv = "5 years experience, 3 patents"
        tailored = "Several years experience"
        dropped = validate_numbers(cv, tailored)
        assert len(dropped) > 0

    def test_ignores_numbers_not_in_cv(self):
        cv = "3 years experience"
        tailored = "3 years experience with 99 projects"
        assert validate_numbers(cv, tailored) == []


MOCK_TAILORED_RESUME = """\
# Jane Doe — ML Engineer

## Summary
5 years of ML experience building production systems at scale.

## Experience
**Senior ML Engineer — Startup Co** (2021–2024)
- Led a team of 8 engineers delivering 98% model uptime
- Reduced inference latency by 40%

## Skills
Python, PyTorch, distributed training
"""


class TestTailorResume:
    @pytest.fixture
    def cv_path(self, tmp_path):
        cv = tmp_path / "cv.md"
        cv.write_text(
            "Jane Doe. 5 years ML experience. Led 8-person team. 98% uptime. "
            "Reduced latency by 40%. Graduated 2021.",
            encoding="utf-8",
        )
        return cv

    @pytest.fixture
    def evaluation_report(self):
        return """\
## Block E — Personalization Plan
1. Lead with PyTorch and distributed training
2. Emphasize 40% latency reduction
3. Reference production ML systems
4. Highlight team leadership (8 engineers)
5. Use "ML infrastructure" framing
"""

    def test_writes_tailored_resume_file(self, cv_path, evaluation_report, tmp_path):
        with patch("src.pipeline.resume_tailor.run_claude", return_value=MOCK_TAILORED_RESUME):
            path = tailor_resume(
                job={"company": "Acme", "title": "ML Engineer", "description": "..."},
                evaluation_report=evaluation_report,
                cv_path=cv_path,
                resumes_dir=tmp_path,
            )
        assert path.exists()
        assert path.suffix == ".md"

    def test_returns_path_to_written_file(self, cv_path, evaluation_report, tmp_path):
        with patch("src.pipeline.resume_tailor.run_claude", return_value=MOCK_TAILORED_RESUME):
            path = tailor_resume(
                job={"company": "Acme", "title": "ML Engineer", "description": "..."},
                evaluation_report=evaluation_report,
                cv_path=cv_path,
                resumes_dir=tmp_path,
            )
        assert path.read_text(encoding="utf-8") == MOCK_TAILORED_RESUME

    def test_passes_block_e_to_claude(self, cv_path, evaluation_report, tmp_path):
        with patch("src.pipeline.resume_tailor.run_claude", return_value=MOCK_TAILORED_RESUME) as mock:
            tailor_resume(
                job={"company": "Acme", "title": "ML Engineer", "description": "..."},
                evaluation_report=evaluation_report,
                cv_path=cv_path,
                resumes_dir=tmp_path,
            )
        prompt_used = mock.call_args[0][0]
        assert "Personalization Plan" in prompt_used

    def test_number_protection_passes_when_all_preserved(self, cv_path, evaluation_report, tmp_path):
        with patch("src.pipeline.resume_tailor.run_claude", return_value=MOCK_TAILORED_RESUME):
            path = tailor_resume(
                job={"company": "Acme", "title": "ML Engineer", "description": "..."},
                evaluation_report=evaluation_report,
                cv_path=cv_path,
                resumes_dir=tmp_path,
            )
        assert path.exists()

    def test_raises_on_missing_cv(self, evaluation_report, tmp_path):
        with pytest.raises(FileNotFoundError):
            tailor_resume(
                job={"company": "Acme", "title": "ML Engineer", "description": "..."},
                evaluation_report=evaluation_report,
                cv_path=tmp_path / "missing.md",
                resumes_dir=tmp_path,
            )
