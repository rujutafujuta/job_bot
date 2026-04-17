"""Tests for priority_scorer.py — pure deterministic scoring."""

from __future__ import annotations

import pytest

from src.pipeline.priority_scorer import compute_priority


def _job(**kwargs) -> dict:
    """Minimal job dict with sensible defaults."""
    base = {
        "stage1_score": 80,
        "stage2_score": None,
        "deadline": "",
        "referral_contact": "",
        "date_posted": "",
        "date_found": "2026-04-17T00:00:00Z",
        "notes": "",
        "salary_min": None,
        "priority_score": 0,
    }
    base.update(kwargs)
    return base


class TestComputePriority:
    def test_returns_integer(self):
        assert isinstance(compute_priority(_job()), int)

    def test_zero_for_empty_job(self):
        score = compute_priority(_job(stage1_score=0))
        assert score >= 0

    def test_referral_adds_points(self):
        without = compute_priority(_job())
        with_ref = compute_priority(_job(referral_contact="Alice Smith, Engineering Manager"))
        assert with_ref > without

    def test_deadline_within_3_days_highest_boost(self):
        import datetime
        soon = (datetime.date.today() + datetime.timedelta(days=2)).isoformat()
        score = compute_priority(_job(deadline=soon))
        assert score >= 30

    def test_deadline_within_7_days_medium_boost(self):
        import datetime
        soon = (datetime.date.today() + datetime.timedelta(days=5)).isoformat()
        score = compute_priority(_job(deadline=soon))
        assert score >= 20

    def test_old_deadline_does_not_boost(self):
        score_with = compute_priority(_job(deadline="2020-01-01"))
        score_without = compute_priority(_job(deadline=""))
        assert score_with == score_without

    def test_stage2_score_contributes(self):
        low = compute_priority(_job(stage2_score=70))
        high = compute_priority(_job(stage2_score=99))
        assert high > low

    def test_stage1_score_contributes_when_no_stage2(self):
        low = compute_priority(_job(stage1_score=70, stage2_score=None))
        high = compute_priority(_job(stage1_score=99, stage2_score=None))
        assert high > low

    def test_fresh_posting_adds_points(self):
        import datetime
        fresh = (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
        stale = (datetime.date.today() - datetime.timedelta(days=35)).isoformat()
        score_fresh = compute_priority(_job(date_posted=fresh))
        score_stale = compute_priority(_job(date_posted=stale))
        assert score_fresh > score_stale

    def test_negative_health_signal_reduces_score(self):
        clean = compute_priority(_job())
        bad = compute_priority(_job(notes="layoffs"))
        assert bad < clean

    def test_positive_health_signal_boosts_score(self):
        clean = compute_priority(_job())
        good = compute_priority(_job(notes="funding"))
        assert good > clean

    def test_never_negative(self):
        score = compute_priority(_job(
            stage1_score=0,
            notes="layoffs",
            date_posted="2020-01-01",
        ))
        assert score >= 0
