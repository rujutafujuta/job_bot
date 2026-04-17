"""Tests for pdf_generator.py — Playwright HTML-to-PDF."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.pipeline.pdf_generator import (
    markdown_to_html,
    generate_pdf,
)


SAMPLE_RESUME_MD = """\
# Jane Doe

jane@example.com | linkedin.com/in/janedoe | github.com/janedoe

## Summary
ML Engineer with 5 years of experience building production systems.

## Experience
**Senior ML Engineer — Acme Corp** (2021–2024)
- Reduced inference latency by 40%
- Led team of 8 engineers

## Skills
Python, PyTorch, distributed training
"""


class TestMarkdownToHtml:
    def test_wraps_in_html_document(self):
        html = markdown_to_html(SAMPLE_RESUME_MD)
        assert "<html" in html
        assert "</html>" in html

    def test_converts_headings(self):
        html = markdown_to_html("# Jane Doe")
        assert "<h1" in html

    def test_includes_sr_only_style(self):
        html = markdown_to_html(SAMPLE_RESUME_MD)
        assert "sr-only" in html

    def test_includes_one_page_css(self):
        html = markdown_to_html(SAMPLE_RESUME_MD)
        assert "max-height" in html or "@page" in html

    def test_name_appears_in_output(self):
        html = markdown_to_html(SAMPLE_RESUME_MD)
        assert "Jane Doe" in html


class TestGeneratePdf:
    def test_returns_path(self, tmp_path):
        resume_md = tmp_path / "resume.md"
        resume_md.write_text(SAMPLE_RESUME_MD, encoding="utf-8")
        output_path = tmp_path / "resume.pdf"

        mock_page = MagicMock()
        mock_browser = MagicMock()
        mock_browser.new_page.return_value = mock_page
        mock_playwright = MagicMock()
        mock_playwright.chromium.launch.return_value = mock_browser

        with patch("src.pipeline.pdf_generator.sync_playwright") as mock_pw_ctx:
            mock_pw_ctx.return_value.__enter__.return_value = mock_playwright
            result = generate_pdf(resume_md, output_path)

        assert result == output_path

    def test_calls_playwright_pdf(self, tmp_path):
        resume_md = tmp_path / "resume.md"
        resume_md.write_text(SAMPLE_RESUME_MD, encoding="utf-8")
        output_path = tmp_path / "resume.pdf"

        mock_page = MagicMock()
        mock_browser = MagicMock()
        mock_browser.new_page.return_value = mock_page
        mock_playwright = MagicMock()
        mock_playwright.chromium.launch.return_value = mock_browser

        with patch("src.pipeline.pdf_generator.sync_playwright") as mock_pw_ctx:
            mock_pw_ctx.return_value.__enter__.return_value = mock_playwright
            generate_pdf(resume_md, output_path)

        mock_page.pdf.assert_called_once()

    def test_raises_on_missing_input(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            generate_pdf(tmp_path / "missing.md", tmp_path / "out.pdf")
