"""Tests for cover_letter.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.pipeline.cover_letter import generate_cover_letter


MOCK_COVER_LETTER = """\
Dear Hiring Team,

I'm excited to apply for the ML Engineer role at Acme. My 5 years building production ML systems
align directly with your need for distributed training expertise.

At my previous role I reduced inference latency by 40% while maintaining 98% uptime across
8-person teams — the kind of scale Acme is targeting with its next product phase.

I'd welcome the chance to discuss how my background fits your team.

Best,
Jane Doe
"""


@pytest.fixture
def sample_job():
    return {
        "company": "Acme",
        "title": "ML Engineer",
        "description": "We need someone with PyTorch and distributed training experience.",
    }


@pytest.fixture
def sample_profile():
    return {
        "personal": {"full_name": "Jane Doe", "email": "jane@example.com"},
        "cover_letter_context": {
            "career_goals": "Build impactful ML systems",
            "motivations": "Solving hard technical problems",
            "strengths": "Distributed systems, fast iteration",
        },
    }


@pytest.fixture
def evaluation_report():
    return """\
## Block E — Personalization Plan
1. Lead with distributed training experience
2. Reference 40% latency reduction
3. Mention Acme's NLP product roadmap
4. Emphasize production ML at scale
5. Close with specific question about team structure
"""


@pytest.fixture
def tailored_resume():
    return "# Jane Doe\n\n## Experience\nSenior ML Engineer — 5 years\n"


class TestGenerateCoverLetter:
    def test_writes_cover_letter_file(self, sample_job, sample_profile, evaluation_report, tailored_resume, tmp_path):
        with patch("src.pipeline.cover_letter.run_claude", return_value=MOCK_COVER_LETTER):
            path = generate_cover_letter(
                job=sample_job,
                evaluation_report=evaluation_report,
                tailored_resume=tailored_resume,
                profile=sample_profile,
                cover_letters_dir=tmp_path,
            )
        assert path.exists()
        assert path.suffix == ".md"

    def test_file_contains_claude_output(self, sample_job, sample_profile, evaluation_report, tailored_resume, tmp_path):
        with patch("src.pipeline.cover_letter.run_claude", return_value=MOCK_COVER_LETTER):
            path = generate_cover_letter(
                job=sample_job,
                evaluation_report=evaluation_report,
                tailored_resume=tailored_resume,
                profile=sample_profile,
                cover_letters_dir=tmp_path,
            )
        assert "Acme" in path.read_text(encoding="utf-8")

    def test_prompt_includes_block_e_hooks(self, sample_job, sample_profile, evaluation_report, tailored_resume, tmp_path):
        with patch("src.pipeline.cover_letter.run_claude", return_value=MOCK_COVER_LETTER) as mock:
            generate_cover_letter(
                job=sample_job,
                evaluation_report=evaluation_report,
                tailored_resume=tailored_resume,
                profile=sample_profile,
                cover_letters_dir=tmp_path,
            )
        prompt = mock.call_args[0][0]
        assert "Personalization Plan" in prompt

    def test_prompt_includes_career_goals(self, sample_job, sample_profile, evaluation_report, tailored_resume, tmp_path):
        with patch("src.pipeline.cover_letter.run_claude", return_value=MOCK_COVER_LETTER) as mock:
            generate_cover_letter(
                job=sample_job,
                evaluation_report=evaluation_report,
                tailored_resume=tailored_resume,
                profile=sample_profile,
                cover_letters_dir=tmp_path,
            )
        prompt = mock.call_args[0][0]
        assert "impactful ML systems" in prompt

    def test_filename_contains_company_and_title(self, sample_job, sample_profile, evaluation_report, tailored_resume, tmp_path):
        with patch("src.pipeline.cover_letter.run_claude", return_value=MOCK_COVER_LETTER):
            path = generate_cover_letter(
                job=sample_job,
                evaluation_report=evaluation_report,
                tailored_resume=tailored_resume,
                profile=sample_profile,
                cover_letters_dir=tmp_path,
            )
        assert "acme" in path.name.lower()
        assert "ml" in path.name.lower()
