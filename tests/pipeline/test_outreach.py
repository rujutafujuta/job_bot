"""Tests for cold outreach module."""

from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import patch

from src.pipeline.contact_finder import Contact
from src.pipeline.outreach import (
    _parse_subject_body,
    _save_draft,
    _parse_draft_file,
    migrate_pending_outreach_files,
    send_cold_outreach,
)
from src.scrapers.base import JobPosting
from src.tracking.db import init_db, list_outreach_messages


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


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


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


class TestSaveDraft:
    def test_saves_db_record(self, db):
        posting = _make_posting()
        contact = Contact(name="Alex", email="alex@acme.com", linkedin_url="")

        result = _save_draft(posting, contact, "Hello", "Body text", dry_run=False, db_path=db)

        assert result["status"] == "pending_user_input"
        msgs = list_outreach_messages(db_path=db)
        assert len(msgs) == 1
        assert msgs[0]["to_email"] == "alex@acme.com"
        assert msgs[0]["subject"] == "Hello"

    def test_dry_run_does_not_write_to_db(self, db):
        posting = _make_posting()
        contact = Contact()

        _save_draft(posting, contact, "Subject", "Body", dry_run=True, db_path=db)

        assert list_outreach_messages(db_path=db) == []

    def test_linkedin_type_when_no_email(self, db):
        posting = _make_posting()
        contact = Contact(name="Bob", email="", linkedin_url="https://linkedin.com/in/bob")

        _save_draft(posting, contact, "Hi", "Body", dry_run=False, db_path=db)

        msgs = list_outreach_messages(db_path=db)
        assert msgs[0]["type"] == "linkedin"


class TestSendColdOutreach:
    def test_skipped_when_cap_reached(self, db, tmp_path):
        from src.tracking.db import insert_job, save_outreach_draft
        insert_job(
            {"url": "https://acme.com/jobs/1", "title": "Eng", "company": "Acme Corp",
             "location": "Remote", "remote": True, "source": "t", "description": "d",
             "date_posted": "2026-01-01", "status": "ready"},
            db_path=db,
        )
        import sqlite3
        conn = sqlite3.connect(str(db))
        jid = conn.execute("SELECT id FROM jobs LIMIT 1").fetchone()[0]
        conn.close()
        for i in range(2):
            save_outreach_draft(
                job_id=jid, msg_type="email", to_name="P", to_email=f"p{i}@a.com",
                to_linkedin="", subject="Hi", body="B", db_path=db,
            )
        posting = _make_posting()
        contact = Contact(name="Alex", email="alex@acme.com", found=True)
        profile = _make_profile()

        result = send_cold_outreach(posting, contact, profile, Path("resume.pdf"), db_path=db)
        assert result["status"] == "skipped_cap"

    def test_require_approval_saves_draft(self, db):
        posting = _make_posting()
        contact = Contact(name="Alex", email="alex@acme.com", found=True)
        profile = _make_profile()

        with patch("src.pipeline.outreach.run_claude", return_value="Subject: Hi\n\nEmail body."):
            result = send_cold_outreach(posting, contact, profile, Path("resume.pdf"), db_path=db)

        assert result["status"] == "pending_user_input"

    def test_dry_run_does_not_write_db(self, db):
        posting = _make_posting()
        contact = Contact(name="Alex", email="alex@acme.com", found=True)
        profile = _make_profile()

        with patch("src.pipeline.outreach.run_claude", return_value="Subject: Hi\n\nBody."):
            send_cold_outreach(posting, contact, profile, Path("resume.pdf"), dry_run=True, db_path=db)

        assert list_outreach_messages(db_path=db) == []


class TestParseDraftFile:
    def test_parses_all_fields(self, tmp_path):
        txt = tmp_path / "draft.txt"
        txt.write_text(
            "TO: bob@acme.com\n"
            "LINKEDIN: https://linkedin.com/in/bob\n"
            "CONTACT: Bob Smith — Engineering Manager\n"
            "SUBJECT: Hello Bob\n"
            "RESUME: /data/resume.pdf\n"
            "---\n"
            "Hi Bob, reaching out.\nLet me know.",
            encoding="utf-8",
        )
        meta = _parse_draft_file(txt)
        assert meta["to_email"] == "bob@acme.com"
        assert meta["linkedin_url"] == "https://linkedin.com/in/bob"
        assert meta["subject"] == "Hello Bob"
        assert "Hi Bob" in meta["body"]

    def test_missing_fields_default_empty(self, tmp_path):
        txt = tmp_path / "draft.txt"
        txt.write_text("---\nJust a body.", encoding="utf-8")
        meta = _parse_draft_file(txt)
        assert meta.get("to_email", "") == ""
        assert "Just a body" in meta["body"]


class TestMigratePendingFiles:
    def test_migrates_txt_files(self, tmp_path, db):
        pending = tmp_path / "pending"
        pending.mkdir()
        (pending / "Acme_Corp_20260101.txt").write_text(
            "TO: a@b.com\nSUBJECT: Hi\n---\nBody", encoding="utf-8"
        )

        count = migrate_pending_outreach_files(pending_dir=pending, db_path=db)

        assert count == 1
        assert len(list_outreach_messages(db_path=db)) == 1
        assert not list(pending.glob("*.txt"))
        assert len(list(pending.glob("*.migrated"))) == 1

    def test_skips_already_migrated(self, tmp_path, db):
        pending = tmp_path / "pending"
        pending.mkdir()
        (pending / "old.migrated").write_text("done", encoding="utf-8")

        count = migrate_pending_outreach_files(pending_dir=pending, db_path=db)

        assert count == 0

    def test_empty_dir_returns_zero(self, tmp_path, db):
        pending = tmp_path / "empty"
        pending.mkdir()
        assert migrate_pending_outreach_files(pending_dir=pending, db_path=db) == 0

    def test_nonexistent_dir_returns_zero(self, tmp_path, db):
        assert migrate_pending_outreach_files(pending_dir=tmp_path / "nope", db_path=db) == 0
