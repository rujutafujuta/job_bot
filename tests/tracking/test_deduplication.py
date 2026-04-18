"""Tests for deduplication module — title+company hash against SQLite tables."""

from __future__ import annotations

import pytest

from src.tracking.db import init_db, insert_job, mark_discarded
from src.tracking.deduplication import (
    compute_hash,
    is_duplicate,
    is_fuzzy_duplicate,
    normalize,
    record_seen,
)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


class TestNormalize:
    def test_lowercases_input(self):
        assert normalize("Software Engineer", "Google") == normalize("software engineer", "google")

    def test_strips_punctuation(self):
        assert normalize("Sr. Engineer!", "Co., Ltd.") == normalize("sr engineer", "co ltd")

    def test_collapses_whitespace(self):
        assert normalize("  Senior   Engineer  ", "Acme  Corp  ") == normalize("Senior Engineer", "Acme Corp")

    def test_produces_consistent_output(self):
        result = normalize("Machine Learning Engineer", "OpenAI")
        assert result == "machine learning engineer openai"

    def test_empty_strings(self):
        result = normalize("", "")
        assert isinstance(result, str)


class TestComputeHash:
    def test_returns_64_char_hex_string(self):
        h = compute_hash("Engineer", "Acme")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_same_input_same_hash(self):
        assert compute_hash("Engineer", "Acme") == compute_hash("Engineer", "Acme")

    def test_different_inputs_different_hashes(self):
        assert compute_hash("Engineer", "Acme") != compute_hash("Manager", "Acme")

    def test_case_insensitive(self):
        assert compute_hash("Engineer", "Acme") == compute_hash("ENGINEER", "ACME")

    def test_punctuation_insensitive(self):
        assert compute_hash("Sr. Engineer", "Acme, Inc.") == compute_hash("Sr Engineer", "Acme Inc")


class TestIsDuplicate:
    def test_returns_false_for_unseen_job(self, db):
        result = is_duplicate("New Role", "Unknown Corp", db)
        assert result is False

    def test_returns_true_if_in_discarded_hashes(self, db):
        h = compute_hash("ML Engineer", "Anthropic")
        mark_discarded(h, "ML Engineer", "Anthropic", "himalayas", db)
        assert is_duplicate("ML Engineer", "Anthropic", db) is True

    def test_returns_true_if_in_jobs_table(self, db):
        h = compute_hash("SWE", "Google")
        insert_job({
            "url": "https://google.com/jobs/1",
            "title": "SWE",
            "company": "Google",
            "dedup_hash": h,
        }, db)
        assert is_duplicate("SWE", "Google", db) is True

    def test_case_insensitive_match(self, db):
        h = compute_hash("swe", "google")
        mark_discarded(h, "swe", "google", "test", db)
        assert is_duplicate("SWE", "GOOGLE", db) is True


class TestIsFuzzyDuplicate:
    def test_returns_false_for_empty_db(self, db):
        assert is_fuzzy_duplicate("Software Engineer", "Google", db) is False

    def test_exact_match_returns_true(self, db):
        insert_job({"url": "https://g.com/1", "title": "Software Engineer", "company": "Google", "status": "scored"}, db)
        assert is_fuzzy_duplicate("Software Engineer", "Google", db) is True

    def test_minor_title_variation_returns_true(self, db):
        insert_job({"url": "https://g.com/1", "title": "Software Engineer", "company": "Google", "status": "scored"}, db)
        assert is_fuzzy_duplicate("Software Engineer II", "Google", db) is True

    def test_unrelated_job_returns_false(self, db):
        insert_job({"url": "https://g.com/1", "title": "Software Engineer", "company": "Google", "status": "scored"}, db)
        assert is_fuzzy_duplicate("Accountant", "BankCorp", db) is False

    def test_same_title_different_company_returns_false(self, db):
        insert_job({"url": "https://g.com/1", "title": "Software Engineer", "company": "Google", "status": "scored"}, db)
        assert is_fuzzy_duplicate("Software Engineer", "Microsoft", db) is False

    def test_checks_discarded_hashes_table(self, db):
        h = compute_hash("ML Engineer", "Anthropic")
        mark_discarded(h, "ML Engineer", "Anthropic", "test", db)
        assert is_fuzzy_duplicate("ML Engineer", "Anthropic", db) is True


class TestRecordSeen:
    def test_inserts_into_jobs_table_when_score_above_threshold(self, db):
        record_seen(
            title="Data Scientist",
            company="Meta",
            url="https://meta.com/jobs/1",
            source="remotive",
            status="scored",
            db_path=db,
        )
        from src.tracking.db import get_job
        job = get_job("https://meta.com/jobs/1", db)
        assert job is not None
        assert job["status"] == "scored"

    def test_hash_is_stored_on_job_record(self, db):
        record_seen(
            title="Data Scientist",
            company="Meta",
            url="https://meta.com/jobs/1",
            source="remotive",
            status="scored",
            db_path=db,
        )
        from src.tracking.db import get_job
        job = get_job("https://meta.com/jobs/1", db)
        expected_hash = compute_hash("Data Scientist", "Meta")
        assert job["dedup_hash"] == expected_hash
