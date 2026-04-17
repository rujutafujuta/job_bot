"""Tests for db.py — PRD v3.0 schema."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.tracking.db import (
    VALID_STATUSES,
    add_contact,
    count_by_status,
    get_all_jobs,
    get_job,
    get_jobs_by_status,
    init_db,
    insert_job,
    mark_discarded,
    update_job,
)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


class TestInitDb:
    def test_creates_jobs_table(self, db):
        with sqlite3.connect(str(db)) as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'"
            ).fetchone()
        assert row is not None

    def test_creates_discarded_hashes_table(self, db):
        with sqlite3.connect(str(db)) as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='discarded_hashes'"
            ).fetchone()
        assert row is not None

    def test_creates_contacts_table(self, db):
        with sqlite3.connect(str(db)) as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='contacts'"
            ).fetchone()
        assert row is not None

    def test_safe_to_call_twice(self, db):
        init_db(db)  # should not raise


class TestInsertJob:
    def test_inserts_minimal_record(self, db):
        insert_job({"url": "https://example.com/job/1", "title": "Engineer", "company": "Acme"}, db)
        job = get_job("https://example.com/job/1", db)
        assert job is not None
        assert job["title"] == "Engineer"
        assert job["company"] == "Acme"

    def test_default_status_is_new(self, db):
        insert_job({"url": "https://example.com/job/1", "title": "Dev", "company": "X"}, db)
        job = get_job("https://example.com/job/1", db)
        assert job["status"] == "new"

    def test_stores_stage1_score(self, db):
        insert_job({
            "url": "https://example.com/job/1",
            "title": "Dev", "company": "X",
            "stage1_score": 82,
            "stage1_reasoning": "Strong match on ML skills",
        }, db)
        job = get_job("https://example.com/job/1", db)
        assert job["stage1_score"] == 82
        assert job["stage1_reasoning"] == "Strong match on ML skills"

    def test_stores_dedup_hash(self, db):
        insert_job({
            "url": "https://example.com/job/1",
            "title": "Dev", "company": "X",
            "dedup_hash": "abc123",
        }, db)
        job = get_job("https://example.com/job/1", db)
        assert job["dedup_hash"] == "abc123"

    def test_rejects_invalid_status(self, db):
        with pytest.raises(ValueError, match="Invalid status"):
            insert_job({
                "url": "https://example.com/job/1",
                "title": "Dev", "company": "X",
                "status": "foobar",
            }, db)

    def test_upsert_on_duplicate_url(self, db):
        insert_job({"url": "https://example.com/job/1", "title": "Dev", "company": "X"}, db)
        insert_job({"url": "https://example.com/job/1", "title": "Updated Dev", "company": "X"}, db)
        job = get_job("https://example.com/job/1", db)
        assert job["title"] == "Updated Dev"

    def test_raises_without_url(self, db):
        with pytest.raises(ValueError, match="url"):
            insert_job({"title": "Dev", "company": "X"}, db)


class TestUpdateJob:
    def test_updates_status(self, db):
        insert_job({"url": "https://example.com/job/1", "title": "Dev", "company": "X"}, db)
        update_job("https://example.com/job/1", {"status": "scored"}, db)
        job = get_job("https://example.com/job/1", db)
        assert job["status"] == "scored"

    def test_raises_on_invalid_status(self, db):
        insert_job({"url": "https://example.com/job/1", "title": "Dev", "company": "X"}, db)
        with pytest.raises(ValueError):
            update_job("https://example.com/job/1", {"status": "bad"}, db)

    def test_returns_false_for_missing_url(self, db):
        result = update_job("https://example.com/missing", {"status": "scored"}, db)
        assert result is False


class TestMarkDiscarded:
    def test_inserts_into_discarded_hashes(self, db):
        mark_discarded("deadbeef", "Engineer", "Acme", "himalayas", db)
        with sqlite3.connect(str(db)) as conn:
            row = conn.execute(
                "SELECT * FROM discarded_hashes WHERE hash = ?", ("deadbeef",)
            ).fetchone()
        assert row is not None

    def test_upsert_does_not_error_on_duplicate(self, db):
        mark_discarded("deadbeef", "Engineer", "Acme", "himalayas", db)
        mark_discarded("deadbeef", "Engineer", "Acme", "himalayas", db)  # should not raise

    def test_stores_title_and_company(self, db):
        mark_discarded("aabbcc", "ML Engineer", "OpenAI", "remotive", db)
        with sqlite3.connect(str(db)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM discarded_hashes WHERE hash = ?", ("aabbcc",)
            ).fetchone()
        assert row["title"] == "ML Engineer"
        assert row["company"] == "OpenAI"
        assert row["source"] == "remotive"


class TestGetJobsByStatus:
    def test_returns_only_matching_status(self, db):
        insert_job({"url": "https://a.com/1", "title": "A", "company": "X", "status": "scored"}, db)
        insert_job({"url": "https://b.com/2", "title": "B", "company": "Y", "status": "new"}, db)
        results = get_jobs_by_status("scored", db)
        assert len(results) == 1
        assert results[0]["title"] == "A"

    def test_returns_empty_list_for_unknown_status(self, db):
        results = get_jobs_by_status("ready", db)
        assert results == []


class TestCountByStatus:
    def test_returns_correct_counts(self, db):
        insert_job({"url": "https://a.com/1", "title": "A", "company": "X", "status": "scored"}, db)
        insert_job({"url": "https://b.com/2", "title": "B", "company": "Y", "status": "scored"}, db)
        insert_job({"url": "https://c.com/3", "title": "C", "company": "Z", "status": "new"}, db)
        counts = count_by_status(db)
        assert counts["scored"] == 2
        assert counts["new"] == 1

    def test_returns_empty_dict_for_empty_db(self, db):
        assert count_by_status(db) == {}


class TestAddContact:
    def test_inserts_contact(self, db):
        add_contact("Alice Smith", "Acme", "Engineering Manager", "linkedin_export", db)
        with sqlite3.connect(str(db)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM contacts WHERE name = ?", ("Alice Smith",)
            ).fetchone()
        assert row is not None
        assert row["company"] == "Acme"
        assert row["source"] == "linkedin_export"

    def test_upsert_on_duplicate_name_company(self, db):
        add_contact("Alice Smith", "Acme", "IC", "linkedin_export", db)
        add_contact("Alice Smith", "Acme", "Manager", "manual", db)
        with sqlite3.connect(str(db)) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM contacts WHERE name = ? AND company = ?",
                ("Alice Smith", "Acme"),
            ).fetchone()[0]
        assert count == 1


class TestValidStatuses:
    def test_contains_all_14_statuses(self):
        expected = {
            "new", "scored", "ready", "applied", "skipped", "discarded",
            "phone_screen", "technical", "offer", "negotiating",
            "accepted", "withdrawn", "rejected", "ghosted",
        }
        assert VALID_STATUSES == expected
