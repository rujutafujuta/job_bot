"""Tests for ATS fingerprinting."""

import pytest
from src.ats.detector import detect_ats, is_supported


@pytest.mark.parametrize("url,expected", [
    ("https://boards.greenhouse.io/acme/jobs/123", "greenhouse"),
    ("https://jobs.lever.co/acme/abc-123", "lever"),
    ("https://acme.wd1.myworkdayjobs.com/careers", "workday"),
    ("https://jobs.ashbyhq.com/acme/role", "ashby"),
    ("https://careers.icims.com/jobs/view?job=1", "icims"),
    ("https://acme.taleo.net/careersection/2/jobsearch.ftl", "taleo"),
    ("https://jobs.smartrecruiters.com/acme/role", "smartrecruiters"),
    ("https://www.linkedin.com/jobs/view/12345", "linkedin"),
    ("https://www.indeed.com/viewjob?jk=abc", "indeed"),
    ("https://www.glassdoor.com/job-listing/acme-123.htm", "glassdoor"),
    ("https://careers.somecompany.com/apply", "unknown"),
    ("", "unknown"),
])
def test_detect_ats(url, expected):
    assert detect_ats(url) == expected


def test_detect_ats_case_insensitive():
    assert detect_ats("https://BOARDS.GREENHOUSE.IO/acme/jobs/1") == "greenhouse"


@pytest.mark.parametrize("ats,expected", [
    ("greenhouse", True),
    ("lever", True),
    ("linkedin", True),
    ("workday", False),
    ("ashby", False),
    ("unknown", False),
    ("taleo", False),
])
def test_is_supported(ats, expected):
    assert is_supported(ats) == expected
