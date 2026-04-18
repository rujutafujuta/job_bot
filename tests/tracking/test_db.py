"""Tests for db.py — PRD v3.0 schema."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.tracking.db import (
    VALID_STATUSES,
    add_contact,
    compute_followup_dates,
    count_by_status,
    get_all_jobs,
    get_applied_jobs,
    get_job,
    get_job_by_id,
    get_jobs_by_status,
    get_jobs_by_statuses,
    get_pending_outreach,
    get_priority_queue,
    get_followup_due,
    init_db,
    insert_job,
    mark_discarded,
    mark_ghosted_jobs,
    update_job,
    update_job_by_id,
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


class TestGetJobById:
    def test_returns_job_by_id(self, db):
        insert_job({"url": "https://a.com/1", "title": "Dev", "company": "X"}, db)
        job = get_job("https://a.com/1", db)
        result = get_job_by_id(job["id"], db)
        assert result is not None
        assert result["title"] == "Dev"

    def test_returns_none_for_missing_id(self, db):
        assert get_job_by_id(9999, db) is None


class TestUpdateJobById:
    def test_updates_status_by_id(self, db):
        insert_job({"url": "https://a.com/1", "title": "Dev", "company": "X"}, db)
        job = get_job("https://a.com/1", db)
        update_job_by_id(job["id"], {"status": "scored"}, db)
        assert get_job_by_id(job["id"], db)["status"] == "scored"

    def test_returns_false_for_missing_id(self, db):
        assert update_job_by_id(9999, {"status": "scored"}, db) is False

    def test_raises_on_invalid_status(self, db):
        insert_job({"url": "https://a.com/1", "title": "Dev", "company": "X"}, db)
        job = get_job("https://a.com/1", db)
        with pytest.raises(ValueError):
            update_job_by_id(job["id"], {"status": "invalid"}, db)

    def test_updates_multiple_fields(self, db):
        insert_job({"url": "https://a.com/1", "title": "Dev", "company": "X"}, db)
        job = get_job("https://a.com/1", db)
        update_job_by_id(job["id"], {"stage2_score": 92, "notes": "great fit"}, db)
        updated = get_job_by_id(job["id"], db)
        assert updated["stage2_score"] == 92
        assert updated["notes"] == "great fit"


class TestGetJobsByStatuses:
    def test_returns_jobs_matching_any_status(self, db):
        insert_job({"url": "https://a.com/1", "title": "A", "company": "X", "status": "scored"}, db)
        insert_job({"url": "https://b.com/2", "title": "B", "company": "Y", "status": "ready"}, db)
        insert_job({"url": "https://c.com/3", "title": "C", "company": "Z", "status": "new"}, db)
        results = get_jobs_by_statuses(["scored", "ready"], db)
        titles = {r["title"] for r in results}
        assert titles == {"A", "B"}

    def test_empty_list_returns_nothing(self, db):
        insert_job({"url": "https://a.com/1", "title": "A", "company": "X"}, db)
        assert get_jobs_by_statuses([], db) == []


class TestGetPriorityQueue:
    def test_returns_all_sorted_by_priority_score(self, db):
        insert_job({"url": "https://a.com/1", "title": "A", "company": "X", "status": "ready", "priority_score": 10}, db)
        insert_job({"url": "https://b.com/2", "title": "B", "company": "Y", "status": "ready", "priority_score": 50}, db)
        insert_job({"url": "https://c.com/3", "title": "C", "company": "Z", "status": "scored", "priority_score": 30}, db)
        results = get_priority_queue(db_path=db)
        assert results[0]["title"] == "B"
        assert results[1]["title"] == "C"
        assert results[2]["title"] == "A"

    def test_excludes_non_actionable_statuses(self, db):
        insert_job({"url": "https://a.com/1", "title": "A", "company": "X", "status": "applied", "priority_score": 99}, db)
        insert_job({"url": "https://b.com/2", "title": "B", "company": "Y", "status": "ready", "priority_score": 1}, db)
        results = get_priority_queue(db_path=db)
        assert all(r["status"] in ("scored", "ready") for r in results)


class TestGetFollowupDue:
    def test_returns_jobs_with_overdue_followup(self, db):
        insert_job({
            "url": "https://a.com/1", "title": "A", "company": "X",
            "status": "applied", "follow_up_1_date": "2020-01-01",
        }, db)
        results = get_followup_due(db)
        assert len(results) == 1

    def test_excludes_future_followup_dates(self, db):
        insert_job({
            "url": "https://a.com/1", "title": "A", "company": "X",
            "status": "applied", "follow_up_1_date": "2099-12-31",
        }, db)
        assert get_followup_due(db) == []

    def test_excludes_non_applied_jobs(self, db):
        insert_job({
            "url": "https://a.com/1", "title": "A", "company": "X",
            "status": "scored", "follow_up_1_date": "2020-01-01",
        }, db)
        assert get_followup_due(db) == []


class TestGetAppliedJobs:
    def test_returns_applied_and_pipeline_statuses(self, db):
        for status in ("applied", "phone_screen", "technical", "offer", "rejected", "ghosted"):
            insert_job({"url": f"https://a.com/{status}", "title": "A", "company": "X", "status": status}, db)
        insert_job({"url": "https://a.com/new", "title": "B", "company": "Y", "status": "new"}, db)
        results = get_applied_jobs(db)
        statuses = {r["status"] for r in results}
        assert "new" not in statuses
        assert "applied" in statuses
        assert "phone_screen" in statuses
        assert "ghosted" in statuses

    def test_excludes_pre_apply_statuses(self, db):
        for status in ("new", "scored", "ready", "skipped", "discarded"):
            insert_job({"url": f"https://a.com/{status}", "title": "A", "company": "X", "status": status}, db)
        assert get_applied_jobs(db) == []


class TestGetPendingOutreach:
    def test_returns_jobs_with_pending_outreach(self, db):
        insert_job({
            "url": "https://a.com/1", "title": "A", "company": "X",
            "outreach_status": "pending_user_input",
        }, db)
        insert_job({
            "url": "https://b.com/2", "title": "B", "company": "Y",
            "outreach_status": "sent",
        }, db)
        results = get_pending_outreach(db)
        assert len(results) == 1
        assert results[0]["company"] == "X"

    def test_returns_empty_when_none_pending(self, db):
        insert_job({"url": "https://a.com/1", "title": "A", "company": "X"}, db)
        assert get_pending_outreach(db) == []


class TestComputeFollowupDates:
    def test_returns_three_dates(self):
        f1, f2, ghosted = compute_followup_dates("2026-04-18")
        assert f1 == "2026-04-25"
        assert f2 == "2026-05-02"
        assert ghosted == "2026-05-18"

    def test_handles_month_boundary(self):
        f1, f2, ghosted = compute_followup_dates("2026-01-28")
        assert f1 == "2026-02-04"
        assert ghosted == "2026-02-27"


class TestMarkGhostedJobs:
    def test_marks_expired_applied_jobs_as_ghosted(self, db):
        insert_job({
            "url": "https://a.com/1", "title": "A", "company": "X",
            "status": "applied", "ghosted_date": "2020-01-01",
        }, db)
        count = mark_ghosted_jobs(db)
        assert count == 1
        job = get_job("https://a.com/1", db)
        assert job["status"] == "ghosted"

    def test_does_not_mark_future_ghosted_date(self, db):
        insert_job({
            "url": "https://a.com/1", "title": "A", "company": "X",
            "status": "applied", "ghosted_date": "2099-12-31",
        }, db)
        count = mark_ghosted_jobs(db)
        assert count == 0
        assert get_job("https://a.com/1", db)["status"] == "applied"

    def test_does_not_mark_non_applied_jobs(self, db):
        insert_job({
            "url": "https://a.com/1", "title": "A", "company": "X",
            "status": "phone_screen", "ghosted_date": "2020-01-01",
        }, db)
        mark_ghosted_jobs(db)
        assert get_job("https://a.com/1", db)["status"] == "phone_screen"

    def test_returns_zero_when_nothing_to_mark(self, db):
        assert mark_ghosted_jobs(db) == 0


class TestValidStatuses:
    def test_contains_all_14_statuses(self):
        expected = {
            "new", "scored", "ready", "applied", "skipped", "discarded",
            "phone_screen", "technical", "offer", "negotiating",
            "accepted", "withdrawn", "rejected", "ghosted",
        }
        assert VALID_STATUSES == expected
