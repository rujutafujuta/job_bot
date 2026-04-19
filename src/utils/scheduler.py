"""Windows Task Scheduler integration for recurring scrape jobs."""

from __future__ import annotations

import sys
from pathlib import Path


def build_schtasks_command(interval_hours: int) -> str:
    """Return a schtasks /Create command that runs the scrape phase every N hours."""
    root = Path(__file__).resolve().parents[2]
    py = sys.executable
    tr = f'cmd /c cd /d "{root}" && "{py}" -m src.pipeline.orchestrator --phase scrape'
    return (
        f"schtasks /Create /SC HOURLY /MO {interval_hours}"
        f' /TN "JobBot Scrape"'
        f' /TR "{tr}"'
        f" /F"
    )
