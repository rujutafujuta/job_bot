"""Tests for Playwright form-fill applicator."""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from src.pipeline.applicator import _get_label, _coerce_value, apply_to_job
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


_PROFILE = {
    "personal": {"full_name": "Jane Doe", "email": "jane@example.com"},
}


class TestGetLabel:
    def test_aria_label(self):
        el = MagicMock()
        el.get_attribute.side_effect = lambda attr: "Email Address" if attr == "aria-label" else None
        page = MagicMock()
        assert _get_label(page, el) == "Email Address"

    def test_associated_label_element(self):
        el = MagicMock()
        el.get_attribute.side_effect = lambda attr: None if attr == "aria-label" else ("email-input" if attr == "id" else None)
        label_el = MagicMock()
        label_el.inner_text.return_value = "  Email  "
        page = MagicMock()
        page.query_selector.return_value = label_el
        assert _get_label(page, el) == "Email"

    def test_placeholder_fallback(self):
        el = MagicMock()
        el.get_attribute.side_effect = lambda attr: (
            None if attr == "aria-label" else
            None if attr == "id" else
            "Enter your email" if attr == "placeholder" else
            None
        )
        page = MagicMock()
        page.query_selector.return_value = None
        assert _get_label(page, el) == "Enter your email"

    def test_name_attribute_last_resort(self):
        el = MagicMock()
        el.get_attribute.side_effect = lambda attr: (
            None if attr in ("aria-label", "id", "placeholder") else
            "email_field" if attr == "name" else None
        )
        page = MagicMock()
        page.query_selector.return_value = None
        assert _get_label(page, el) == "email_field"

    def test_unknown_field_fallback(self):
        el = MagicMock()
        el.get_attribute.return_value = None
        page = MagicMock()
        page.query_selector.return_value = None
        assert _get_label(page, el) == "unknown field"


class TestCoerceValue:
    def test_first_name_split(self):
        assert _coerce_value("First Name", "Jane Doe", _PROFILE) == "Jane"

    def test_last_name_split(self):
        assert _coerce_value("Last Name", "Jane Doe", _PROFILE) == "Doe"

    def test_first_alias(self):
        assert _coerce_value("first", "Jane Doe", _PROFILE) == "Jane"

    def test_last_alias(self):
        assert _coerce_value("last", "Jane Doe", _PROFILE) == "Doe"

    def test_other_field_unchanged(self):
        assert _coerce_value("Email", "jane@example.com", _PROFILE) == "jane@example.com"

    def test_single_name_no_crash(self):
        profile = {"personal": {"full_name": "Cher"}}
        result = _coerce_value("Last Name", "Cher", profile)
        assert result == "Cher"


class TestApplyToJob:
    def test_unsupported_ats_returns_manual_flag(self):
        posting = _make_posting(url="https://careers.somecompany.com/apply/role/123")
        result = apply_to_job(posting, _PROFILE, Path("resume.pdf"), None, dry_run=True)

        assert result["submitted"] is False
        assert "Manual" in result["notes"] or "manual" in result["notes"].lower()
        assert result["application_link"] == posting.url

    def test_workday_unsupported(self):
        posting = _make_posting(url="https://acme.wd1.myworkdayjobs.com/careers/job/123")
        result = apply_to_job(posting, _PROFILE, Path("resume.pdf"), None, dry_run=True)

        assert result["submitted"] is False
        assert "workday" in result["notes"].lower() or "manual" in result["notes"].lower()
