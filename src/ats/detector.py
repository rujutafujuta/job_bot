"""ATS fingerprinting — detect which system a job posting uses."""

from __future__ import annotations

import re
from urllib.parse import urlparse

# Domain/URL patterns that identify each ATS
_ATS_PATTERNS: list[tuple[str, str]] = [
    ("greenhouse", r"boards\.greenhouse\.io|greenhouse\.io/jobs"),
    ("lever", r"jobs\.lever\.co"),
    ("workday", r"myworkdayjobs\.com|wd\d+\.myworkdayjobs\.com"),
    ("ashby", r"jobs\.ashbyhq\.com"),
    ("icims", r"careers\.icims\.com|\.icims\.com/jobs"),
    ("taleo", r"taleo\.net/careersection"),
    ("smartrecruiters", r"jobs\.smartrecruiters\.com"),
    ("linkedin", r"linkedin\.com/jobs"),
    ("indeed", r"indeed\.com/viewjob"),
    ("glassdoor", r"glassdoor\.com/job-listing"),
]


def detect_ats(url: str) -> str:
    """
    Detect the ATS used for a job posting from its URL.

    Returns:
        ATS name string (e.g. "greenhouse", "lever", "workday")
        or "unknown" if unrecognized.
    """
    for ats_name, pattern in _ATS_PATTERNS:
        if re.search(pattern, url, re.IGNORECASE):
            return ats_name
    return "unknown"


def is_supported(ats: str) -> bool:
    """Return True if we have automation support for this ATS."""
    return ats in ("greenhouse", "lever", "linkedin")
