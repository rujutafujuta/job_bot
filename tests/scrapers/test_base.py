"""Tests for BaseScraper — retry logic with exponential backoff."""

from __future__ import annotations

from unittest.mock import MagicMock, patch, call

import pytest
import requests

from src.scrapers.base import BaseScraper


class _ConcreteScaper(BaseScraper):
    source_name = "test"

    def scrape(self, queries):
        return []


@pytest.fixture
def scraper():
    return _ConcreteScaper(config={"delay_seconds": 0})


class TestRetryLogic:
    def test_succeeds_on_first_try(self, scraper):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        with patch("requests.get", return_value=mock_resp) as mock_get:
            scraper._get("https://example.com")
        assert mock_get.call_count == 1

    def test_retries_on_429(self, scraper):
        error_resp = MagicMock()
        error_resp.status_code = 429
        error_resp.raise_for_status.side_effect = requests.HTTPError(response=error_resp)
        ok_resp = MagicMock()
        ok_resp.raise_for_status = MagicMock()
        with patch("requests.get", side_effect=[error_resp, ok_resp]) as mock_get:
            with patch("time.sleep"):
                result = scraper._get("https://example.com")
        assert mock_get.call_count == 2
        assert result is ok_resp

    def test_retries_on_500(self, scraper):
        error_resp = MagicMock()
        error_resp.status_code = 500
        error_resp.raise_for_status.side_effect = requests.HTTPError(response=error_resp)
        ok_resp = MagicMock()
        ok_resp.raise_for_status = MagicMock()
        with patch("requests.get", side_effect=[error_resp, ok_resp]):
            with patch("time.sleep"):
                result = scraper._get("https://example.com")
        assert result is ok_resp

    def test_raises_after_max_retries(self, scraper):
        error_resp = MagicMock()
        error_resp.status_code = 503
        error_resp.raise_for_status.side_effect = requests.HTTPError(response=error_resp)
        with patch("requests.get", return_value=error_resp):
            with patch("time.sleep"):
                with pytest.raises(requests.HTTPError):
                    scraper._get("https://example.com")

    def test_non_retryable_status_raises_immediately(self, scraper):
        error_resp = MagicMock()
        error_resp.status_code = 404
        error_resp.raise_for_status.side_effect = requests.HTTPError(response=error_resp)
        with patch("requests.get", return_value=error_resp) as mock_get:
            with patch("time.sleep"):
                with pytest.raises(requests.HTTPError):
                    scraper._get("https://example.com")
        assert mock_get.call_count == 1

    def test_backoff_sleeps_increase(self, scraper):
        error_resp = MagicMock()
        error_resp.status_code = 429
        error_resp.raise_for_status.side_effect = requests.HTTPError(response=error_resp)
        sleep_calls = []
        with patch("requests.get", return_value=error_resp):
            with patch("time.sleep", side_effect=lambda s: sleep_calls.append(s)):
                with pytest.raises(requests.HTTPError):
                    scraper._get("https://example.com")
        assert len(sleep_calls) >= 2
        assert sleep_calls[1] > sleep_calls[0]
