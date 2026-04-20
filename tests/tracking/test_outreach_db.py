"""Tests for outreach_messages table in db.py."""

from __future__ import annotations

import pytest
from pathlib import Path

from src.tracking.db import (
    init_db,
    insert_job,
    save_outreach_draft,
    list_outreach_messages,
    update_outreach_status,
    count_outreach_for_company,
)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


def _job_id(db, url="https://example.com/job/1", company="Acme"):
    insert_job(
        {
            "url": url,
            "title": "Engineer",
            "company": company,
            "location": "Remote",
            "remote": True,
            "source": "test",
            "description": "desc",
            "date_posted": "2026-01-01",
            "status": "ready",
        },
        db_path=db,
    )
    import sqlite3
    conn = sqlite3.connect(str(db))
    row = conn.execute("SELECT id FROM jobs WHERE url=?", (url,)).fetchone()
    conn.close()
    return row[0]


class TestSaveOutreachDraft:
    def test_returns_integer_id(self, db):
        jid = _job_id(db)
        mid = save_outreach_draft(
            job_id=jid,
            msg_type="email",
            to_name="Bob Smith",
            to_email="bob@acme.com",
            to_linkedin="",
            subject="Hello",
            body="Hi Bob",
            db_path=db,
        )
        assert isinstance(mid, int)
        assert mid > 0

    def test_record_has_draft_status(self, db):
        jid = _job_id(db)
        mid = save_outreach_draft(
            job_id=jid,
            msg_type="email",
            to_name="Bob",
            to_email="bob@acme.com",
            to_linkedin="",
            subject="Hi",
            body="Body",
            db_path=db,
        )
        msgs = list_outreach_messages(db_path=db)
        assert any(m["id"] == mid and m["status"] == "draft" for m in msgs)

    def test_linkedin_type_stored(self, db):
        jid = _job_id(db)
        save_outreach_draft(
            job_id=jid,
            msg_type="linkedin",
            to_name="Alice",
            to_email="",
            to_linkedin="https://linkedin.com/in/alice",
            subject="Connection",
            body="Hi Alice",
            db_path=db,
        )
        msgs = list_outreach_messages(db_path=db)
        assert any(m["type"] == "linkedin" for m in msgs)


class TestListOutreachMessages:
    def test_empty_initially(self, db):
        assert list_outreach_messages(db_path=db) == []

    def test_returns_all_records(self, db):
        jid = _job_id(db)
        for i in range(3):
            save_outreach_draft(
                job_id=jid,
                msg_type="email",
                to_name=f"Person {i}",
                to_email=f"p{i}@acme.com",
                to_linkedin="",
                subject=f"Subject {i}",
                body=f"Body {i}",
                db_path=db,
            )
        assert len(list_outreach_messages(db_path=db)) == 3

    def test_records_contain_expected_fields(self, db):
        jid = _job_id(db)
        save_outreach_draft(
            job_id=jid,
            msg_type="email",
            to_name="Bob",
            to_email="bob@acme.com",
            to_linkedin="",
            subject="Hello",
            body="Body",
            db_path=db,
        )
        msg = list_outreach_messages(db_path=db)[0]
        for field in ("id", "job_id", "type", "to_name", "to_email", "subject", "body", "status", "created_at"):
            assert field in msg


class TestUpdateOutreachStatus:
    def test_draft_to_sent(self, db):
        jid = _job_id(db)
        mid = save_outreach_draft(
            job_id=jid,
            msg_type="email",
            to_name="Bob",
            to_email="bob@acme.com",
            to_linkedin="",
            subject="Hi",
            body="Body",
            db_path=db,
        )
        result = update_outreach_status(mid, "sent", db_path=db)
        assert result is True
        msgs = list_outreach_messages(db_path=db)
        assert any(m["id"] == mid and m["status"] == "sent" for m in msgs)

    def test_sent_to_replied(self, db):
        jid = _job_id(db)
        mid = save_outreach_draft(
            job_id=jid,
            msg_type="email",
            to_name="Alice",
            to_email="alice@acme.com",
            to_linkedin="",
            subject="Hi",
            body="Body",
            db_path=db,
        )
        update_outreach_status(mid, "sent", db_path=db)
        update_outreach_status(mid, "replied", db_path=db)
        msgs = list_outreach_messages(db_path=db)
        assert any(m["id"] == mid and m["status"] == "replied" for m in msgs)

    def test_missing_id_returns_false(self, db):
        result = update_outreach_status(9999, "sent", db_path=db)
        assert result is False


class TestCountOutreachForCompany:
    def test_zero_when_none(self, db):
        assert count_outreach_for_company("Acme", db_path=db) == 0

    def test_counts_drafts(self, db):
        jid = _job_id(db, company="Acme")
        for i in range(2):
            save_outreach_draft(
                job_id=jid,
                msg_type="email",
                to_name=f"P{i}",
                to_email=f"p{i}@acme.com",
                to_linkedin="",
                subject="Hi",
                body="Body",
                db_path=db,
            )
        assert count_outreach_for_company("Acme", db_path=db) == 2

    def test_does_not_count_other_company(self, db):
        jid1 = _job_id(db, url="https://acme.com/1", company="Acme")
        jid2 = _job_id(db, url="https://beta.com/1", company="Beta")
        save_outreach_draft(
            job_id=jid1, msg_type="email", to_name="A", to_email="a@acme.com",
            to_linkedin="", subject="Hi", body="B", db_path=db,
        )
        save_outreach_draft(
            job_id=jid2, msg_type="email", to_name="B", to_email="b@beta.com",
            to_linkedin="", subject="Hi", body="B", db_path=db,
        )
        assert count_outreach_for_company("Acme", db_path=db) == 1
        assert count_outreach_for_company("Beta", db_path=db) == 1
