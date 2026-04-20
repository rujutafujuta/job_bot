"""Tests for Windows Task Scheduler integration."""

from __future__ import annotations

from src.utils.scheduler import build_schtasks_command


class TestBuildSchtasksCommand:
    def test_starts_with_schtasks_create(self):
        cmd = build_schtasks_command()
        assert cmd.startswith("schtasks /Create")

    def test_daily_schedule_flag(self):
        cmd = build_schtasks_command()
        assert "/SC DAILY" in cmd

    def test_runs_at_3am(self):
        cmd = build_schtasks_command()
        assert "/ST 03:00" in cmd

    def test_task_name_present(self):
        cmd = build_schtasks_command()
        assert "JobBot" in cmd

    def test_invokes_scrape_phase(self):
        cmd = build_schtasks_command()
        assert "--phase scrape" in cmd

    def test_force_overwrite_flag(self):
        cmd = build_schtasks_command()
        assert "/F" in cmd

    def test_returns_string(self):
        assert isinstance(build_schtasks_command(), str)
