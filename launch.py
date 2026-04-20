"""
Job Bot Launcher
----------------
First run  → credential setup GUI → onboarding wizard → start server → open browser
Later runs → start server → open browser → show running window
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import messagebox

ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"
PROFILE_PATH = ROOT / "config" / "user_profile.yaml"
SERVER_URL = "http://localhost:8000"
PORT = 8000

# Use the venv Python; fall back to the interpreter running this script
_VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
PYTHON = str(_VENV_PY) if _VENV_PY.exists() else sys.executable


# ---------------------------------------------------------------------------
# Setup detection
# ---------------------------------------------------------------------------

def _env_value(key: str) -> str:
    """Read a key from .env without loading it into os.environ."""
    if not ENV_PATH.exists():
        return ""
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return ""


def _is_setup_complete() -> bool:
    token = _env_value("APIFY_TOKEN")
    if not token or "your_apify_token_here" in token:
        return False
    return PROFILE_PATH.exists()


def _write_env(apify_token: str, adzuna_app_id: str, adzuna_api_key: str) -> None:
    lines = [
        "# Apify — required for LinkedIn, Indeed, Glassdoor, ZipRecruiter scraping\n",
        f"APIFY_TOKEN={apify_token}\n",
        "\n",
        "# Adzuna — free job API, register at developer.adzuna.com\n",
        f"ADZUNA_APP_ID={adzuna_app_id}\n",
        f"ADZUNA_API_KEY={adzuna_api_key}\n",
    ]
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    ENV_PATH.write_text("".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Server management
# ---------------------------------------------------------------------------

def _server_ready(timeout: int = 45) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=1):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def _start_server() -> subprocess.Popen:
    return subprocess.Popen(
        [PYTHON, "-m", "uvicorn", "src.web.app:app",
         "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=str(ROOT),
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )


# ---------------------------------------------------------------------------
# Setup GUI (first run only)
# ---------------------------------------------------------------------------

class _SetupWindow:
    """Credential collection dialog shown on first run."""

    def __init__(self) -> None:
        self.completed = False
        self._apify = ""
        self._az_id = ""
        self._az_key = ""

        root = tk.Tk()
        root.title("Job Bot — First Time Setup")
        root.resizable(False, False)
        root.configure(bg="#1a1a2e")
        self._root = root

        self._build()
        root.mainloop()

    def _label(self, parent, text: str, **kw) -> tk.Label:
        return tk.Label(parent, text=text, bg="#1a1a2e", fg="#e0e0e0",
                        font=("Segoe UI", 10), **kw)

    def _build(self) -> None:
        pad = {"padx": 20, "pady": 6}

        tk.Label(self._root, text="Job Bot", bg="#1a1a2e", fg="#ffffff",
                 font=("Segoe UI", 18, "bold")).pack(pady=(24, 2))
        tk.Label(self._root, text="First-time setup — enter your API credentials",
                 bg="#1a1a2e", fg="#9ca3af", font=("Segoe UI", 10)).pack(pady=(0, 16))

        # --- Apify ---
        apify_frame = tk.Frame(self._root, bg="#16213e", bd=0, relief="flat",
                               highlightbackground="#334155", highlightthickness=1)
        apify_frame.pack(fill="x", **pad)

        tk.Label(apify_frame, text="Apify Token  (required)",
                 bg="#16213e", fg="#f8fafc", font=("Segoe UI", 10, "bold")).pack(
            anchor="w", padx=12, pady=(10, 0))
        tk.Label(apify_frame,
                 text="Covers LinkedIn, Indeed, Glassdoor, Google Jobs, ZipRecruiter.\n"
                      "Get it at: apify.com → Settings → API Tokens",
                 bg="#16213e", fg="#64748b", font=("Segoe UI", 9),
                 justify="left").pack(anchor="w", padx=12)
        self._apify_var = tk.StringVar()
        tk.Entry(apify_frame, textvariable=self._apify_var, width=52,
                 bg="#0f172a", fg="#e2e8f0", insertbackground="white",
                 relief="flat", font=("Consolas", 10)).pack(
            fill="x", padx=12, pady=(4, 12))

        # --- Adzuna ---
        az_frame = tk.Frame(self._root, bg="#16213e", bd=0, relief="flat",
                            highlightbackground="#334155", highlightthickness=1)
        az_frame.pack(fill="x", **pad)

        tk.Label(az_frame, text="Adzuna  (optional)",
                 bg="#16213e", fg="#f8fafc", font=("Segoe UI", 10, "bold")).pack(
            anchor="w", padx=12, pady=(10, 0))
        tk.Label(az_frame, text="Free tier: 250 req/day. Register at developer.adzuna.com",
                 bg="#16213e", fg="#64748b", font=("Segoe UI", 9)).pack(anchor="w", padx=12)

        row = tk.Frame(az_frame, bg="#16213e")
        row.pack(fill="x", padx=12, pady=(4, 12))
        tk.Label(row, text="App ID:", bg="#16213e", fg="#94a3b8",
                 font=("Segoe UI", 9)).pack(side="left")
        self._az_id_var = tk.StringVar()
        tk.Entry(row, textvariable=self._az_id_var, width=22,
                 bg="#0f172a", fg="#e2e8f0", insertbackground="white",
                 relief="flat", font=("Consolas", 10)).pack(side="left", padx=(4, 16))
        tk.Label(row, text="API Key:", bg="#16213e", fg="#94a3b8",
                 font=("Segoe UI", 9)).pack(side="left")
        self._az_key_var = tk.StringVar()
        tk.Entry(row, textvariable=self._az_key_var, width=22,
                 bg="#0f172a", fg="#e2e8f0", insertbackground="white",
                 relief="flat", font=("Consolas", 10)).pack(side="left", padx=(4, 0))

        # --- Buttons ---
        btn_frame = tk.Frame(self._root, bg="#1a1a2e")
        btn_frame.pack(fill="x", padx=20, pady=(12, 20))
        tk.Button(btn_frame, text="Continue →", command=self._on_continue,
                  bg="#2563eb", fg="white", activebackground="#1d4ed8",
                  font=("Segoe UI", 11, "bold"), relief="flat",
                  padx=20, pady=8, cursor="hand2").pack(side="right")
        tk.Button(btn_frame, text="Cancel", command=self._root.destroy,
                  bg="#374151", fg="#9ca3af", activebackground="#4b5563",
                  font=("Segoe UI", 10), relief="flat",
                  padx=12, pady=8, cursor="hand2").pack(side="right", padx=(0, 8))

    def _on_continue(self) -> None:
        apify = self._apify_var.get().strip()
        if not apify:
            messagebox.showerror("Required", "Apify token is required.", parent=self._root)
            return
        self._apify = apify
        self._az_id = self._az_id_var.get().strip()
        self._az_key = self._az_key_var.get().strip()
        self.completed = True
        self._root.destroy()


# ---------------------------------------------------------------------------
# Running window
# ---------------------------------------------------------------------------

class _RunningWindow:
    """Small status window shown while the server is running."""

    def __init__(self, server: subprocess.Popen) -> None:
        self._server = server
        root = tk.Tk()
        root.title("Job Bot")
        root.resizable(False, False)
        root.configure(bg="#1a1a2e")
        root.protocol("WM_DELETE_WINDOW", self._stop)
        self._root = root
        self._build()
        self._poll()
        root.mainloop()

    def _build(self) -> None:
        tk.Label(self._root, text="Job Bot is running",
                 bg="#1a1a2e", fg="#ffffff", font=("Segoe UI", 14, "bold")).pack(
            padx=32, pady=(24, 4))

        link = tk.Label(self._root, text=SERVER_URL, bg="#1a1a2e", fg="#60a5fa",
                        font=("Segoe UI", 10, "underline"), cursor="hand2")
        link.pack(padx=32, pady=(0, 4))
        link.bind("<Button-1>", lambda _: webbrowser.open(SERVER_URL))

        tk.Label(self._root, text="Close this window to stop the server.",
                 bg="#1a1a2e", fg="#64748b", font=("Segoe UI", 9)).pack(pady=(0, 12))

        btn_frame = tk.Frame(self._root, bg="#1a1a2e")
        btn_frame.pack(padx=32, pady=(0, 24))
        tk.Button(btn_frame, text="Open Dashboard", command=lambda: webbrowser.open(SERVER_URL),
                  bg="#2563eb", fg="white", activebackground="#1d4ed8",
                  font=("Segoe UI", 10, "bold"), relief="flat",
                  padx=14, pady=7, cursor="hand2").pack(side="left", padx=(0, 8))
        tk.Button(btn_frame, text="Stop", command=self._stop,
                  bg="#dc2626", fg="white", activebackground="#b91c1c",
                  font=("Segoe UI", 10), relief="flat",
                  padx=14, pady=7, cursor="hand2").pack(side="left")

    def _poll(self) -> None:
        """Check every 2s if the server process is still alive."""
        if self._server.poll() is not None:
            messagebox.showerror("Server stopped",
                                 "The Job Bot server has stopped unexpectedly.")
            self._root.destroy()
            return
        self._root.after(2000, self._poll)

    def _stop(self) -> None:
        self._server.terminate()
        self._root.destroy()


# ---------------------------------------------------------------------------
# Startup splash
# ---------------------------------------------------------------------------

def _show_starting_splash() -> tk.Tk:
    splash = tk.Tk()
    splash.title("Job Bot")
    splash.resizable(False, False)
    splash.configure(bg="#1a1a2e")
    tk.Label(splash, text="Starting Job Bot…", bg="#1a1a2e", fg="#e0e0e0",
             font=("Segoe UI", 13)).pack(padx=48, pady=32)
    splash.update()
    return splash


# ---------------------------------------------------------------------------
# Onboarding
# ---------------------------------------------------------------------------

def _run_onboarding() -> bool:
    """Run the profile setup wizard in a visible terminal. Returns True if completed."""
    messagebox.showinfo(
        "Profile Setup",
        "A terminal window will open for profile setup.\n\n"
        "Follow the prompts to enter your name, target salary, preferences, and roles.\n\n"
        "Job Bot will start automatically when you finish.",
    )
    proc = subprocess.Popen(
        ["cmd", "/k",
         f'"{PYTHON}" -m src.setup.onboarding && echo. && echo Setup complete — you can close this window. && pause'],
        cwd=str(ROOT),
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )
    proc.wait()
    return PROFILE_PATH.exists()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _launch() -> None:
    server = _start_server()
    splash = _show_starting_splash()

    if not _server_ready(timeout=45):
        splash.destroy()
        messagebox.showerror(
            "Startup failed",
            "Job Bot server did not start in time.\n\n"
            "Make sure all dependencies are installed:\n"
            f"  {PYTHON} -m pip install -r requirements.txt",
        )
        server.terminate()
        return

    splash.destroy()
    webbrowser.open(SERVER_URL)
    _RunningWindow(server)


def main() -> None:
    if not _is_setup_complete():
        setup = _SetupWindow()
        if not setup.completed:
            return  # user cancelled

        _write_env(setup._apify, setup._az_id, setup._az_key)

        if not PROFILE_PATH.exists():
            if not _run_onboarding():
                messagebox.showerror(
                    "Setup incomplete",
                    "Profile setup was not completed. Please run Job Bot again to finish.",
                )
                return

    _launch()


if __name__ == "__main__":
    main()
