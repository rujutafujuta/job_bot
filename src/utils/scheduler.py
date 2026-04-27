"""Windows Task Scheduler integration — daily scrape job with wake/catch-up flags."""

from __future__ import annotations

import sys
import tempfile
from html import escape
from pathlib import Path

_TASK_NAME = "JobBot Scrape"


def _build_task_xml(time: str, root: Path, py: str) -> str:
    """
    Build a Task Scheduler v1.2 XML definition for the daily scrape job.

    Sets the three flags Windows requires for a laptop-friendly schedule:
      - WakeToRun: wakes the computer from sleep at the scheduled time
      - StartWhenAvailable: runs missed schedules after boot/wake (catch-up)
      - DisallowStartIfOnBatteries=false: also runs on battery power
    """
    hh, mm = time.split(":")
    # The date portion of StartBoundary is irrelevant for daily triggers — the
    # trigger fires every day at the time-of-day component. Use a fixed past date.
    start_boundary = f"2026-01-01T{hh.zfill(2)}:{mm.zfill(2)}:00"
    args = (
        f'/c cd /d "{root}" &amp;&amp; "{py}" -m src.pipeline.orchestrator --phase scrape'
    )
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Job Bot — daily scrape and Stage 1 scoring</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{escape(start_boundary)}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>true</WakeToRun>
    <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>cmd.exe</Command>
      <Arguments>{args}</Arguments>
    </Exec>
  </Actions>
</Task>
"""


def build_schtasks_command(time: str = "03:00") -> str:
    """
    Return a schtasks command that registers the daily scrape job from an XML
    definition. The XML enables WakeToRun, StartWhenAvailable, and run-on-battery,
    so missed schedules (laptop closed/asleep) get caught up after boot or wake.

    The XML is written to a temp file (UTF-16 LE with BOM, as schtasks requires).
    """
    root = Path(__file__).resolve().parents[2]
    xml = _build_task_xml(time=time, root=root, py=sys.executable)

    # schtasks /XML insists on UTF-16 with BOM — utf-8 input fails silently with
    # "ERROR: The task XML contains a value which is incorrectly formatted".
    tmp = tempfile.NamedTemporaryFile(
        delete=False, suffix=".xml", prefix="jobbot_task_"
    )
    tmp.close()
    Path(tmp.name).write_text(xml, encoding="utf-16")

    return (
        f'schtasks /Create /TN "{_TASK_NAME}"'
        f' /XML "{tmp.name}"'
        f" /F"
    )
