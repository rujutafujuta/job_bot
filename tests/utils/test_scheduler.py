"""Tests for Windows Task Scheduler integration."""

from __future__ import annotations

from src.utils.scheduler import build_schtasks_command


class TestBuildSchtasksCommand:
    def test_starts_with_schtasks_create(self):
        cmd = build_schtasks_command(6)
        assert cmd.startswith("schtasks /Create")

    def test_hourly_schedule_flag(self):
        cmd = build_schtasks_command(6)
        assert "/SC HOURLY" in cmd

    def test_interval_embedded(self):
        cmd = build_schtasks_command(6)
        assert "/MO 6" in cmd

    def test_different_interval(self):
        cmd = build_schtasks_command(12)
        assert "/MO 12" in cmd

    def test_task_name_present(self):
        cmd = build_schtasks_command(4)
        assert "JobBot" in cmd

    def test_invokes_scrape_phase(self):
        cmd = build_schtasks_command(4)
        assert "--phase scrape" in cmd

    def test_force_overwrite_flag(self):
        cmd = build_schtasks_command(1)
        assert "/F" in cmd

    def test_returns_string(self):
        cmd = build_schtasks_command(3)
        assert isinstance(cmd, str)
