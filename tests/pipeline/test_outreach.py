"""Tests for cold outreach module."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.pipeline.contact_finder import Contact
from src.pipeline.outreach import (
    outreach_count_for_company,
    _parse_subject_body,
    _save_pending,
    send_cold_outreach,
)
from src.scrapers.base import JobPosting


def _make_posting(**kwargs):
    defaults = dict(
        url="https://acme.com/jobs/1",
        title="Software Engineer",
        company="Acme Corp",
        location="Remote",
        remote=True,
        source="test",
        description="Build things.",
        date_posted="2026-04-18",
    )
    defaults.update(kwargs)
    return JobPosting(**defaults)


def _make_profile(**kwargs):
    profile = {
        "personal": {
            "full_name": "Jane Doe",
            "email": "jane@example.com",
            "linkedin_url": "https://linkedin.com/in/janedoe",
        },
        "skills": {"years_experience": 5, "primary": ["Python", "SQL"]},
        "outreach": {
            "max_per_company": 2,
            "cold_email_tone": "friendly",
            "require_approval": True,
        },
    }
    profile.update(kwargs)
    return profile


class TestOutreachCount:
    def test_zero_when_no_log(self, tmp_path):
        log = tmp_path / "log.json"
        assert outreach_count_for_company("Acme Corp", log) == 0

    def test_returns_count_from_log(self, tmp_path):
        log = tmp_path / "log.json"
        log.write_text(json.dumps({"acme corp": 2}))
        assert outreach_count_for_company("Acme Corp", log) == 2

    def test_case_insensitive(self, tmp_path):
        log = tmp_path / "log.json"
        log.write_text(json.dumps({"acme corp": 1}))
        assert outreach_count_for_company("ACME CORP", log) == 1


class TestParseSubjectBody:
    def test_parses_subject_and_body(self):
        raw = "Subject: Hello there\n\nThis is the email body.\nSecond line."
        subject, body = _parse_subject_body(raw)
        assert subject == "Hello there"
        assert "This is the email body." in body

    def test_no_subject_defaults(self):
        raw = "Just a plain message with no subject line."
        subject, body = _parse_subject_body(raw)
        assert subject == "Reaching out"
        assert "Just a plain message" in body

    def test_case_insensitive_subject(self):
        raw = "SUBJECT: Test Email\n\nBody text."
        subject, _ = _parse_subject_body(raw)
        assert subject == "Test Email"


class TestSavePending:
    def test_creates_draft_file(self, tmp_path):
        posting = _make_posting()
        contact = Contact(name="Alex", email="alex@acme.com", linkedin_url="https://linkedin.com/in/alex")
        log = tmp_path / "log.json"

        with patch("src.pipeline.outreach._PENDING_DIR", tmp_path / "pending"):
            result = _save_pending(posting, contact, "Subject", "Body text", Path("resume.pdf"), dry_run=False, outreach_log=log)

        assert result["status"] == "pending_user_input"
        drafts = list((tmp_path / "pending").glob("*.txt"))
        assert len(drafts) == 1
        content = drafts[0].read_text()
        assert "alex@acme.com" in content
        assert "Subject" in content

    def test_dry_run_does_not_create_file(self, tmp_path):
        posting = _make_posting()
        contact = Contact()
        log = tmp_path / "log.json"

        with patch("src.pipeline.outreach._PENDING_DIR", tmp_path / "pending"):
            _save_pending(posting, contact, "Subject", "Body", Path("resume.pdf"), dry_run=True, outreach_log=log)

        assert not (tmp_path / "pending").exists()


class TestSendColdOutreach:
    def test_skipped_when_cap_reached(self, tmp_path):
        log = tmp_path / "log.json"
        log.write_text(json.dumps({"acme corp": 2}))
        posting = _make_posting()
        contact = Contact(name="Alex", email="alex@acme.com", found=True)
        profile = _make_profile()

        result = send_cold_outreach(posting, contact, profile, Path("resume.pdf"), outreach_log=log)
        assert result["status"] == "skipped_cap"

    def test_require_approval_saves_pending(self, tmp_path):
        log = tmp_path / "log.json"
        posting = _make_posting()
        contact = Contact(name="Alex", email="alex@acme.com", found=True)
        profile = _make_profile()

        with patch("src.pipeline.outreach.run_claude", return_value="Subject: Hi\n\nEmail body."):
            with patch("src.pipeline.outreach._PENDING_DIR", tmp_path / "pending"):
                result = send_cold_outreach(posting, contact, profile, Path("resume.pdf"), outreach_log=log)

        assert result["status"] == "pending_user_input"

    def test_dry_run_does_not_write_files(self, tmp_path):
        log = tmp_path / "log.json"
        posting = _make_posting()
        contact = Contact(name="Alex", email="alex@acme.com", found=True)
        profile = _make_profile()

        with patch("src.pipeline.outreach.run_claude", return_value="Subject: Hi\n\nBody."):
            with patch("src.pipeline.outreach._PENDING_DIR", tmp_path / "pending"):
                send_cold_outreach(posting, contact, profile, Path("resume.pdf"), dry_run=True, outreach_log=log)

        assert not (tmp_path / "pending").exists()
