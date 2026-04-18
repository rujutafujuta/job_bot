"""Tests for hiring manager contact finder."""

import pytest
from unittest.mock import patch, MagicMock
from src.pipeline.contact_finder import (
    find_contact,
    _extract_domain,
    _hunter_lookup,
    _linkedin_search_url,
    Contact,
)


class TestExtractDomain:
    def test_standard_domain(self):
        assert _extract_domain("https://acme.com/jobs/123") == "acme.com"

    def test_strips_www(self):
        assert _extract_domain("https://www.acme.com/jobs") == "acme.com"

    def test_known_ats_domain_returns_empty(self):
        assert _extract_domain("https://boards.greenhouse.io/acme/jobs/1") == ""

    def test_lever_ats_returns_empty(self):
        assert _extract_domain("https://jobs.lever.co/acme/role") == ""

    def test_workday_returns_empty(self):
        assert _extract_domain("https://acme.wd1.myworkdayjobs.com/jobs") == ""

    def test_invalid_url_returns_empty(self):
        assert _extract_domain("not-a-url") == ""

    def test_empty_url_returns_empty(self):
        assert _extract_domain("") == ""


class TestHunterLookup:
    def test_returns_contact_on_success(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": {
                "emails": [
                    {
                        "value": "hiring@acme.com",
                        "first_name": "Alex",
                        "last_name": "Smith",
                        "position": "Engineering Manager",
                    }
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()

        with patch("requests.get", return_value=mock_response):
            result = _hunter_lookup("Acme Corp", "https://acme.com/jobs/1", "fake-key")

        assert result.found is True
        assert result.email == "hiring@acme.com"
        assert result.name == "Alex Smith"
        assert result.title == "Engineering Manager"

    def test_prefers_engineering_title(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": {
                "emails": [
                    {"value": "cfo@acme.com", "first_name": "Bob", "last_name": "Jones", "position": "CFO"},
                    {"value": "eng@acme.com", "first_name": "Sam", "last_name": "Lee", "position": "Engineering Manager"},
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()

        with patch("requests.get", return_value=mock_response):
            result = _hunter_lookup("Acme Corp", "https://acme.com/jobs/1", "fake-key")

        assert result.email == "eng@acme.com"

    def test_returns_empty_contact_on_no_emails(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": {"emails": []}}
        mock_response.raise_for_status = MagicMock()

        with patch("requests.get", return_value=mock_response):
            result = _hunter_lookup("Acme Corp", "https://acme.com/jobs/1", "fake-key")

        assert result.found is False

    def test_returns_empty_on_ats_domain(self):
        result = _hunter_lookup("Acme", "https://boards.greenhouse.io/acme/jobs/1", "fake-key")
        assert result.found is False

    def test_request_exception_returns_empty(self):
        import requests
        with patch("requests.get", side_effect=requests.RequestException("timeout")):
            result = _hunter_lookup("Acme Corp", "https://acme.com/jobs/1", "fake-key")
        assert result.found is False


class TestLinkedInSearchUrl:
    def test_returns_linkedin_url(self):
        url = _linkedin_search_url("Acme Corp")
        assert "linkedin.com" in url
        assert "Acme" in url or "Acme%20Corp" in url


class TestFindContact:
    def test_falls_back_to_linkedin_when_no_hunter_key(self):
        with patch.dict("os.environ", {}, clear=True):
            result = find_contact("Acme Corp", "https://acme.com/jobs/1")

        assert result.found is False
        assert "linkedin.com" in result.linkedin_url

    def test_uses_hunter_when_key_present(self):
        mock_contact = Contact(name="A B", email="a@b.com", found=True)
        with patch("src.pipeline.contact_finder._hunter_lookup", return_value=mock_contact):
            with patch.dict("os.environ", {"HUNTER_IO_API_KEY": "key"}):
                result = find_contact("Acme", "https://acme.com/jobs/1")

        assert result.found is True
        assert result.email == "a@b.com"

    def test_falls_back_to_linkedin_when_hunter_finds_nothing(self):
        empty = Contact()
        with patch("src.pipeline.contact_finder._hunter_lookup", return_value=empty):
            with patch.dict("os.environ", {"HUNTER_IO_API_KEY": "key"}):
                result = find_contact("Acme", "https://acme.com/jobs/1")

        assert result.found is False
        assert "linkedin.com" in result.linkedin_url
