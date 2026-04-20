"""Windows Task Scheduler integration — daily 3am scrape job."""

from __future__ import annotations

import sys
from pathlib import Path


def build_schtasks_command(time: str = "03:00") -> str:
    """Return a schtasks /Create command that runs the scrape phase daily at the given time (HH:MM)."""
    root = Path(__file__).resolve().parents[2]
    py = sys.executable
    tr = f'cmd /c cd /d "{root}" && "{py}" -m src.pipeline.orchestrator --phase scrape'
    return (
        f"schtasks /Create /SC DAILY /ST {time}"
        f' /TN "JobBot Scrape"'
        f' /TR "{tr}"'
        f" /F"
    )
