"""Tests for Claude-based hiring manager contact finder."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.pipeline.contact_finder import (
    Contact,
    _linkedin_search_url,
    _parse_response,
    find_contact,
)


class TestParseResponse:
    def test_parses_all_fields(self):
        raw = (
            "NAME: Jane Smith\n"
            "TITLE: Engineering Manager\n"
            "EMAIL: jane@acme.com\n"
            "LINKEDIN: https://linkedin.com/in/janesmith\n"
        )
        contact = _parse_response(raw)
        assert contact.found is True
        assert contact.name == "Jane Smith"
        assert contact.title == "Engineering Manager"
        assert contact.email == "jane@acme.com"
        assert contact.linkedin_url == "https://linkedin.com/in/janesmith"

    def test_not_found_returns_empty_contact(self):
        raw = "NAME: not found\nTITLE:\nEMAIL:\nLINKEDIN:\n"
        contact = _parse_response(raw)
        assert contact.found is False

    def test_partial_fields_still_parse(self):
        raw = "NAME: Bob Jones\nTITLE: Recruiter\nEMAIL:\nLINKEDIN:\n"
        contact = _parse_response(raw)
        assert contact.found is True
        assert contact.name == "Bob Jones"
        assert contact.email == ""

    def test_case_insensitive_keys(self):
        raw = "Name: Alice\nTitle: HR\nEmail: a@b.com\nLinkedin: https://linkedin.com/in/alice"
        contact = _parse_response(raw)
        assert contact.found is True
        assert contact.name == "Alice"

    def test_empty_response_returns_not_found(self):
        assert _parse_response("").found is False

    def test_garbled_response_returns_not_found(self):
        assert _parse_response("Sorry, I could not find anyone.").found is False


class TestLinkedInSearchUrl:
    def test_returns_linkedin_url(self):
        url = _linkedin_search_url("Acme Corp")
        assert "linkedin.com" in url

    def test_encodes_company_name(self):
        url = _linkedin_search_url("Acme Corp")
        assert "Acme" in url


class TestFindContact:
    def test_returns_contact_when_claude_succeeds(self):
        raw = "NAME: Jane Smith\nTITLE: EM\nEMAIL: j@acme.com\nLINKEDIN: https://linkedin.com/in/j"
        with patch("src.pipeline.contact_finder.run_claude", return_value=raw):
            result = find_contact("Acme Corp", "https://acme.com/jobs/1")
        assert result.found is True
        assert result.name == "Jane Smith"

    def test_falls_back_to_linkedin_when_claude_returns_not_found(self):
        raw = "NAME: not found\nTITLE:\nEMAIL:\nLINKEDIN:\n"
        with patch("src.pipeline.contact_finder.run_claude", return_value=raw):
            result = find_contact("Acme Corp", "https://acme.com/jobs/1")
        assert result.found is False
        assert "linkedin.com" in result.linkedin_url

    def test_falls_back_to_linkedin_when_claude_raises(self):
        with patch("src.pipeline.contact_finder.run_claude", side_effect=RuntimeError("timeout")):
            result = find_contact("Acme Corp", "https://acme.com/jobs/1")
        assert result.found is False
        assert "linkedin.com" in result.linkedin_url

    def test_claude_called_with_web_search_tool(self):
        raw = "NAME: not found\nTITLE:\nEMAIL:\nLINKEDIN:\n"
        with patch("src.pipeline.contact_finder.run_claude", return_value=raw) as mock_claude:
            find_contact("Acme Corp", "https://acme.com/jobs/1")
        call_kwargs = mock_claude.call_args
        tools = call_kwargs[1].get("tools") or call_kwargs[0][1]
        assert "WebSearch" in tools
