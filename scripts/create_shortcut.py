"""Create a Job Bot desktop shortcut on Windows."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAUNCH_PY = ROOT / "launch.py"
PYTHONW = Path(sys.executable).with_name("pythonw.exe")

if not PYTHONW.exists():
    # Fallback: system Python (outside a venv)
    PYTHONW = Path(sys.executable).parent / "pythonw.exe"

if sys.platform != "win32":
    print("Desktop shortcut creation is only supported on Windows.")
    sys.exit(0)

import winreg  # noqa: E402 — Windows only


def _desktop_path() -> Path:
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
        ) as key:
            return Path(winreg.QueryValueEx(key, "Desktop")[0])
    except Exception:
        return Path.home() / "Desktop"


def create_shortcut() -> None:
    import pythoncom  # part of pywin32
    from win32com.shell import shell  # type: ignore

    desktop = _desktop_path()
    shortcut_path = desktop / "Job Bot.lnk"

    shell_link = pythoncom.CoCreateInstance(
        shell.CLSID_ShellLink,
        None,
        pythoncom.CLSCTX_INPROC_SERVER,
        shell.IID_IShellLink,
    )
    shell_link.SetPath(str(PYTHONW))
    shell_link.SetArguments(str(LAUNCH_PY))
    shell_link.SetWorkingDirectory(str(ROOT))
    shell_link.SetDescription("Job Bot — one-click launcher")

    persist = shell_link.QueryInterface(pythoncom.IID_IPersistFile)
    persist.Save(str(shortcut_path), True)
    print(f"Shortcut created: {shortcut_path}")


def _fallback_vbs() -> None:
    """If pywin32 isn't available, drop a .vbs launcher on the desktop instead."""
    desktop = _desktop_path()
    vbs_path = desktop / "Job Bot.vbs"
    vbs_path.write_text(
        f'Set WshShell = CreateObject("WScript.Shell")\n'
        f'WshShell.Run "{PYTHONW} {LAUNCH_PY}", 0\n'
        f"Set WshShell = Nothing\n",
        encoding="utf-8",
    )
    print(f"VBS launcher created: {vbs_path}")
    print("Double-click 'Job Bot.vbs' on your desktop to launch.")


if __name__ == "__main__":
    try:
        create_shortcut()
    except ImportError:
        print("pywin32 not found — creating a .vbs launcher instead.")
        _fallback_vbs()
    except Exception as exc:
        print(f"Could not create .lnk shortcut ({exc}) — creating .vbs launcher instead.")
        _fallback_vbs()
