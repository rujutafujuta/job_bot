"""Tests for role_detector — cv.md mtime check + Claude-generated target_roles.yaml."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from src.pipeline.role_detector import generate_roles, needs_regeneration


@pytest.fixture
def cv_file(tmp_path):
    cv = tmp_path / "cv.md"
    cv.write_text("# Jane Doe\nSoftware Engineer with 5 years ML experience.\n")
    return cv


@pytest.fixture
def roles_file(tmp_path):
    return tmp_path / "target_roles.yaml"


class TestNeedsRegeneration:
    def test_returns_true_when_roles_file_missing(self, cv_file, roles_file):
        assert needs_regeneration(cv_file, roles_file) is True

    def test_returns_true_when_cv_newer_than_roles(self, cv_file, roles_file):
        roles_file.write_text("generated_from: cv.md\n")
        # Make roles file older than cv
        old_time = cv_file.stat().st_mtime - 10
        import os
        os.utime(str(roles_file), (old_time, old_time))
        assert needs_regeneration(cv_file, roles_file) is True

    def test_returns_false_when_roles_newer_than_cv(self, cv_file, roles_file):
        roles_file.write_text("generated_from: cv.md\n")
        # Make roles file newer than cv
        new_time = cv_file.stat().st_mtime + 10
        import os
        os.utime(str(roles_file), (new_time, new_time))
        assert needs_regeneration(cv_file, roles_file) is False

    def test_returns_true_when_cv_missing(self, tmp_path, roles_file):
        cv = tmp_path / "nonexistent_cv.md"
        roles_file.write_text("generated_from: cv.md\n")
        assert needs_regeneration(cv, roles_file) is True


class TestGenerateRoles:
    CLAUDE_OUTPUT = """
generated_from: cv.md
generated_at: 2026-04-17
resume_based:
  - title: "Machine Learning Engineer"
    queries:
      - "machine learning engineer remote"
      - "ML engineer deep learning remote"
  - title: "Computer Vision Engineer"
    queries:
      - "computer vision engineer remote"
exploratory:
  - title: "AI Platform Engineer"
    queries:
      - "AI platform engineer remote"
"""

    def test_writes_yaml_to_roles_file(self, cv_file, roles_file):
        with patch("src.pipeline.role_detector.run_claude", return_value=self.CLAUDE_OUTPUT):
            generate_roles(cv_file, roles_file)

        assert roles_file.exists()
        data = yaml.safe_load(roles_file.read_text())
        assert "resume_based" in data
        assert "exploratory" in data

    def test_dry_run_does_not_write_file(self, cv_file, roles_file):
        with patch("src.pipeline.role_detector.run_claude", return_value=self.CLAUDE_OUTPUT):
            generate_roles(cv_file, roles_file, dry_run=True)

        assert not roles_file.exists()

    def test_returns_parsed_roles_dict(self, cv_file, roles_file):
        with patch("src.pipeline.role_detector.run_claude", return_value=self.CLAUDE_OUTPUT):
            result = generate_roles(cv_file, roles_file)

        assert isinstance(result, dict)
        assert len(result["resume_based"]) >= 1

    def test_raises_when_cv_missing(self, tmp_path, roles_file):
        cv = tmp_path / "missing.md"
        with pytest.raises(FileNotFoundError):
            generate_roles(cv, roles_file)

    def test_passes_cv_content_to_claude(self, cv_file, roles_file):
        with patch("src.pipeline.role_detector.run_claude", return_value=self.CLAUDE_OUTPUT) as mock_run:
            generate_roles(cv_file, roles_file)

        prompt = mock_run.call_args[0][0]
        assert "Jane Doe" in prompt or "cv.md" in prompt.lower() or "Software Engineer" in prompt

    def test_skips_claude_call_if_no_regeneration_needed(self, cv_file, roles_file):
        roles_file.write_text(self.CLAUDE_OUTPUT)
        import os
        new_time = cv_file.stat().st_mtime + 10
        os.utime(str(roles_file), (new_time, new_time))

        with patch("src.pipeline.role_detector.run_claude") as mock_run:
            result = generate_roles(cv_file, roles_file, force=False)

        mock_run.assert_not_called()
        assert result is not None
