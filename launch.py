"""
Job Bot Launcher
----------------
First run  → credential setup GUI → onboarding wizard → start server → open browser
Later runs → start server → open browser → show running window
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from src.utils.scheduler import build_schtasks_command

ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"
PROFILE_PATH = ROOT / "config" / "user_profile.yaml"
SERVER_URL = "http://localhost:8000"
PORT = 8000

# Use the venv Python; fall back to the interpreter running this script
_VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
PYTHON = str(_VENV_PY) if _VENV_PY.exists() else sys.executable


# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------

def _check_python_version() -> bool:
    """Require Python 3.11+."""
    return sys.version_info >= (3, 11)


def _check_claude_cli() -> bool:
    """Return True if the `claude` CLI is on PATH."""
    return shutil.which("claude") is not None


def _ensure_playwright() -> bool:
    """Install playwright package + chromium into the venv if missing. Returns False on failure."""
    try:
        import importlib
        importlib.import_module("playwright")
    except ImportError:
        print("[prereq] Installing playwright…")
        result = subprocess.run(
            [PYTHON, "-m", "pip", "install", "playwright"],
            capture_output=True,
        )
        if result.returncode != 0:
            return False

    # Check whether the chromium browser binary exists by running `playwright install chromium`
    result = subprocess.run(
        [PYTHON, "-m", "playwright", "install", "chromium"],
        capture_output=True,
    )
    return result.returncode == 0


def _run_prereq_checks() -> bool:
    """
    Run all prerequisite checks before startup.
    Returns True if it's safe to continue, False if a blocking problem was found.
    """
    if not _check_python_version():
        messagebox.showerror(
            "Python version too old",
            f"Job Bot requires Python 3.11 or later.\n\n"
            f"You are running Python {sys.version.split()[0]}.\n\n"
            "Download the latest Python from python.org and re-run the launcher.",
        )
        return False

    if not _check_claude_cli():
        messagebox.showerror(
            "Claude Code not found",
            "Job Bot requires the Claude Code CLI to be installed and on your PATH.\n\n"
            "To fix:\n"
            "  1. Install Claude Code: https://claude.ai/code\n"
            "  2. Sign in and authenticate\n"
            "  3. Relaunch Job Bot\n\n"
            "All AI features (scoring, evaluation, outreach drafts) run through the\n"
            "`claude` CLI — no Anthropic API key needed.",
        )
        return False

    # Playwright is silent — install in background, warn if it fails
    if not _ensure_playwright():
        messagebox.showwarning(
            "Playwright setup failed",
            "Could not install or set up Playwright's Chromium browser.\n\n"
            "The Apply Co-Pilot feature won't work until you run:\n"
            "  playwright install chromium\n\n"
            "Everything else (scraping, scoring, outreach) will work normally.",
        )
        # Non-blocking — let startup continue

    return True


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
# Scheduler dialog
# ---------------------------------------------------------------------------

class _SchedulerDialog:
    """Ask the user whether to enable daily automatic scraping and at what time."""

    def __init__(self) -> None:
        self.enabled = False
        self.time = "03:00"

        root = tk.Tk()
        root.title("Job Bot — Daily Scraping")
        root.resizable(False, False)
        root.configure(bg="#1a1a2e")
        self._root = root
        self._build()
        root.mainloop()

    def _build(self) -> None:
        pad = {"padx": 24, "pady": 6}

        tk.Label(self._root, text="Automatic Daily Scraping",
                 bg="#1a1a2e", fg="#ffffff", font=("Segoe UI", 14, "bold")).pack(pady=(24, 4))
        tk.Label(self._root,
                 text="Job Bot can scrape for new jobs automatically every night\n"
                      "while you sleep, so your dashboard is ready each morning.",
                 bg="#1a1a2e", fg="#9ca3af", font=("Segoe UI", 10),
                 justify="center").pack(pady=(0, 16))

        frame = tk.Frame(self._root, bg="#16213e", highlightbackground="#334155",
                         highlightthickness=1)
        frame.pack(fill="x", **pad)

        tk.Label(frame, text="Run daily scrape at:",
                 bg="#16213e", fg="#f8fafc", font=("Segoe UI", 10, "bold")).pack(
            anchor="w", padx=12, pady=(12, 4))

        time_row = tk.Frame(frame, bg="#16213e")
        time_row.pack(anchor="w", padx=12, pady=(0, 12))

        self._hour_var = tk.StringVar(value="03")
        self._min_var = tk.StringVar(value="00")

        tk.Spinbox(time_row, from_=0, to=23, width=3, format="%02.0f",
                   textvariable=self._hour_var,
                   bg="#0f172a", fg="#e2e8f0", buttonbackground="#334155",
                   relief="flat", font=("Consolas", 12)).pack(side="left")
        tk.Label(time_row, text=":", bg="#16213e", fg="#e2e8f0",
                 font=("Consolas", 12, "bold")).pack(side="left", padx=2)
        tk.Spinbox(time_row, from_=0, to=59, width=3, format="%02.0f",
                   textvariable=self._min_var,
                   bg="#0f172a", fg="#e2e8f0", buttonbackground="#334155",
                   relief="flat", font=("Consolas", 12)).pack(side="left")
        tk.Label(time_row, text="(24-hour, e.g. 03:00 = 3am)",
                 bg="#16213e", fg="#64748b", font=("Segoe UI", 9)).pack(side="left", padx=(10, 0))

        btn_frame = tk.Frame(self._root, bg="#1a1a2e")
        btn_frame.pack(fill="x", padx=24, pady=(12, 24))
        tk.Button(btn_frame, text="Yes, schedule it →", command=self._on_yes,
                  bg="#2563eb", fg="white", activebackground="#1d4ed8",
                  font=("Segoe UI", 11, "bold"), relief="flat",
                  padx=20, pady=8, cursor="hand2").pack(side="right")
        tk.Button(btn_frame, text="Skip for now", command=self._root.destroy,
                  bg="#374151", fg="#9ca3af", activebackground="#4b5563",
                  font=("Segoe UI", 10), relief="flat",
                  padx=12, pady=8, cursor="hand2").pack(side="right", padx=(0, 8))

    def _on_yes(self) -> None:
        hour = self._hour_var.get().zfill(2)
        minute = self._min_var.get().zfill(2)
        self.time = f"{hour}:{minute}"
        self.enabled = True
        self._root.destroy()


def _setup_scheduler(time: str) -> None:
    """Register the Windows Task Scheduler job and show success/failure feedback."""
    cmd = build_schtasks_command(time)
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode == 0:
        messagebox.showinfo(
            "Scheduler set up",
            f"Job Bot will scrape automatically every day at {time}.\n\n"
            "To remove it later:\n  schtasks /Delete /TN \"JobBot Scrape\" /F",
        )
    else:
        messagebox.showwarning(
            "Scheduler setup failed",
            f"Could not register the scheduled task.\n\n{result.stderr.strip()}\n\n"
            "You can set it up manually later:\n"
            "  python -m src.pipeline.orchestrator --schedule",
        )


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
# Profile Wizard (Tkinter, Page 2 of setup)
# ---------------------------------------------------------------------------

import yaml as _yaml


def _load_yaml_profile(path: Path) -> dict:
    if path.exists():
        with path.open(encoding="utf-8") as f:
            return _yaml.safe_load(f) or {}
    return {}


def _save_yaml_profile(data: dict, path: Path) -> None:
    from ruamel.yaml import YAML as _RYAML
    path.parent.mkdir(parents=True, exist_ok=True)
    ryaml = _RYAML()
    ryaml.preserve_quotes = True
    tmp = path.with_suffix(".yaml.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        ryaml.dump(data, f)
    tmp.replace(path)


class _ProfileWizardWindow:
    """
    Tkinter profile wizard — Page 2 of first-time setup.
    Shown after credential entry. Outputs the canonical user_profile.yaml schema.
    """

    _BG = "#1a1a2e"
    _CARD = "#16213e"
    _BORDER = "#334155"
    _FG = "#e0e0e0"
    _FG_DIM = "#64748b"
    _FG_HEAD = "#f8fafc"
    _INPUT_BG = "#0f172a"
    _INPUT_FG = "#e2e8f0"
    _BLUE = "#2563eb"

    def __init__(self) -> None:
        self.completed = False

        root = tk.Tk()
        root.title("Job Bot — Profile Setup")
        root.configure(bg=self._BG)
        root.minsize(680, 500)
        self._root = root

        self._vars: dict[str, tk.Variable] = {}
        self._build()
        root.mainloop()

    # ── layout helpers ────────────────────────────────────────────────────

    def _lbl(self, parent, text: str, size=10, bold=False, dim=False) -> tk.Label:
        weight = "bold" if bold else "normal"
        color = self._FG_DIM if dim else (self._FG_HEAD if bold else self._FG)
        return tk.Label(parent, text=text, bg=parent["bg"],
                        fg=color, font=("Segoe UI", size, weight))

    def _entry(self, parent, var: tk.StringVar, width=40) -> tk.Entry:
        return tk.Entry(parent, textvariable=var, width=width,
                        bg=self._INPUT_BG, fg=self._INPUT_FG,
                        insertbackground="white", relief="flat",
                        font=("Segoe UI", 10))

    def _card(self, parent, title: str) -> tk.Frame:
        frame = tk.Frame(parent, bg=self._CARD,
                         highlightbackground=self._BORDER, highlightthickness=1)
        frame.pack(fill="x", padx=16, pady=6)
        tk.Label(frame, text=title, bg=self._CARD, fg=self._FG_HEAD,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=12, pady=(10, 4))
        return frame

    def _field_row(self, parent, label: str, var: tk.StringVar, width=36) -> None:
        row = tk.Frame(parent, bg=parent["bg"])
        row.pack(fill="x", padx=12, pady=3)
        tk.Label(row, text=label, bg=parent["bg"], fg=self._FG,
                 font=("Segoe UI", 9), width=26, anchor="w").pack(side="left")
        self._entry(row, var, width=width).pack(side="left", fill="x", expand=True, padx=(4, 0))

    def _sv(self, name: str, default: str = "") -> tk.StringVar:
        v = tk.StringVar(value=default)
        self._vars[name] = v
        return v

    def _bv(self, name: str, default: bool = False) -> tk.BooleanVar:
        v = tk.BooleanVar(value=default)
        self._vars[name] = v
        return v

    # ── build UI ─────────────────────────────────────────────────────────

    def _build(self) -> None:
        ex = _load_yaml_profile(PROFILE_PATH)

        # --- outer scroll container ---
        outer = tk.Frame(self._root, bg=self._BG)
        outer.pack(fill="both", expand=True)

        canvas = tk.Canvas(outer, bg=self._BG, highlightthickness=0)
        scroll = tk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(canvas, bg=self._BG)
        canvas_window = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_resize(event):
            canvas.itemconfig(canvas_window, width=event.width)

        inner.bind("<Configure>", _on_configure)
        canvas.bind("<Configure>", _on_canvas_resize)

        # mouse-wheel scroll
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # --- header ---
        tk.Label(inner, text="Job Bot", bg=self._BG, fg="#ffffff",
                 font=("Segoe UI", 18, "bold")).pack(pady=(20, 2))
        tk.Label(inner, text="Profile Setup — tell us about yourself",
                 bg=self._BG, fg=self._FG_DIM, font=("Segoe UI", 10)).pack(pady=(0, 4))
        tk.Label(inner,
                 text="All fields are optional. Press Skip to fill in later via Dashboard → Settings.",
                 bg=self._BG, fg="#f59e0b", font=("Segoe UI", 9)).pack(pady=(0, 12))

        # --- sections ---
        self._build_personal(inner, ex)
        self._build_visa(inner, ex)
        self._build_job_prefs(inner, ex)
        self._build_locations(inner, ex)
        self._build_roles(inner, ex)
        self._build_skills(inner, ex)
        self._build_cover_letter(inner, ex)
        self._build_exclusions_network(inner, ex)
        self._build_cv_upload(inner, ex)

        # --- buttons ---
        btn_frame = tk.Frame(inner, bg=self._BG)
        btn_frame.pack(fill="x", padx=16, pady=(12, 24))
        tk.Button(btn_frame, text="Save & Continue →", command=self._on_save,
                  bg=self._BLUE, fg="white", activebackground="#1d4ed8",
                  font=("Segoe UI", 11, "bold"), relief="flat",
                  padx=20, pady=8, cursor="hand2").pack(side="right")
        tk.Button(btn_frame, text="Skip for now", command=self._on_skip,
                  bg="#374151", fg="#9ca3af", activebackground="#4b5563",
                  font=("Segoe UI", 10), relief="flat",
                  padx=12, pady=8, cursor="hand2").pack(side="right", padx=(0, 8))

    # ── section builders ─────────────────────────────────────────────────

    def _build_personal(self, parent: tk.Frame, ex: dict) -> None:
        p = ex.get("personal", {})
        card = self._card(parent, "1. Personal Information")
        self._field_row(card, "Full name", self._sv("p_full_name", p.get("full_name", "")))
        self._field_row(card, "Email", self._sv("p_email", p.get("email", "")))
        self._field_row(card, "Phone", self._sv("p_phone", p.get("phone", "")))
        self._field_row(card, "City", self._sv("p_city", p.get("city", "")))
        self._field_row(card, "State / Province", self._sv("p_state", p.get("state", "")))
        self._field_row(card, "Country", self._sv("p_country", p.get("country", "US")))
        self._field_row(card, "LinkedIn URL", self._sv("p_linkedin", p.get("linkedin_url", "")))
        self._field_row(card, "GitHub URL (optional)", self._sv("p_github", p.get("github_url", "")))
        self._field_row(card, "Portfolio URL (optional)", self._sv("p_portfolio", p.get("portfolio_url", "")))
        tk.Frame(card, bg=self._CARD, height=8).pack()

    def _build_visa(self, parent: tk.Frame, ex: dict) -> None:
        v = ex.get("visa", {})
        card = self._card(parent, "2. Work Authorization")

        # Existing values support both old (status: str) and new (statuses: list) schemas
        existing_statuses: list[str] = list(v.get("statuses") or [])
        if not existing_statuses and v.get("status"):
            existing_statuses = [v["status"]]

        status_options = ["US Citizen", "Green Card", "H1B", "OPT", "CPT", "TN", "Other"]

        tk.Label(card, text="Authorization (check all that apply):",
                 bg=self._CARD, fg=self._FG, font=("Segoe UI", 9)).pack(
                 anchor="w", padx=12, pady=(4, 0))
        cb_frame = tk.Frame(card, bg=self._CARD)
        cb_frame.pack(anchor="w", padx=12, pady=2)
        for opt in status_options:
            bvar = self._bv(f"visa_st_{opt}", opt in existing_statuses)
            tk.Checkbutton(cb_frame, text=opt, variable=bvar,
                           bg=self._CARD, fg=self._FG, selectcolor=self._INPUT_BG,
                           activebackground=self._CARD, font=("Segoe UI", 9)).pack(side="left", padx=4)

        sponsor_row = tk.Frame(card, bg=self._CARD)
        sponsor_row.pack(fill="x", padx=12, pady=(6, 0))
        tk.Checkbutton(sponsor_row, text="I will need visa sponsorship in the future",
                       variable=self._bv("visa_needs_sponsorship",
                                         bool(v.get("requires_sponsorship", False))),
                       bg=self._CARD, fg=self._FG, selectcolor=self._INPUT_BG,
                       activebackground=self._CARD, font=("Segoe UI", 9)).pack(anchor="w")

        expiry_row = tk.Frame(card, bg=self._CARD)
        expiry_row.pack(fill="x", padx=12, pady=(4, 8))
        tk.Label(expiry_row, text="Expiry date (YYYY-MM-DD, OPT/CPT/H1B/TN only):",
                 bg=self._CARD, fg=self._FG, font=("Segoe UI", 9)).pack(side="left")
        self._entry(expiry_row, self._sv("visa_expiry", v.get("work_auth_expiry", "")), width=18).pack(
            side="left", padx=(6, 0))

    def _build_job_prefs(self, parent: tk.Frame, ex: dict) -> None:
        t = ex.get("target", {})
        emp = ex.get("employment", {})
        card = self._card(parent, "3. Job Preferences")

        # job_type checkboxes
        tk.Label(card, text="Job type:", bg=self._CARD, fg=self._FG,
                 font=("Segoe UI", 9)).pack(anchor="w", padx=12, pady=(4, 0))
        jt_row = tk.Frame(card, bg=self._CARD)
        jt_row.pack(anchor="w", padx=12, pady=2)
        existing_jt = t.get("job_type", ["full-time"])
        for jt in ["full-time", "part-time", "contract", "internship"]:
            v = self._bv(f"jt_{jt}", jt in existing_jt)
            tk.Checkbutton(jt_row, text=jt, variable=v, bg=self._CARD, fg=self._FG,
                           selectcolor=self._INPUT_BG, activebackground=self._CARD,
                           font=("Segoe UI", 9)).pack(side="left", padx=4)

        # remote_preference checkboxes
        tk.Label(card, text="Remote preference (check all that apply):", bg=self._CARD, fg=self._FG,
                 font=("Segoe UI", 9)).pack(anchor="w", padx=12, pady=(8, 0))
        rp_row = tk.Frame(card, bg=self._CARD)
        rp_row.pack(anchor="w", padx=12, pady=2)
        existing_rp = t.get("remote_preference", "")
        for rp in ["remote", "hybrid", "onsite"]:
            checked = (existing_rp in (rp, "any") or rp in str(existing_rp))
            v = self._bv(f"rp_{rp}", checked)
            tk.Checkbutton(rp_row, text=rp, variable=v, bg=self._CARD, fg=self._FG,
                           selectcolor=self._INPUT_BG, activebackground=self._CARD,
                           font=("Segoe UI", 9)).pack(side="left", padx=4)

        # willing_to_relocate
        rel_row = tk.Frame(card, bg=self._CARD)
        rel_row.pack(fill="x", padx=12, pady=4)
        tk.Label(rel_row, text="Willing to relocate?", bg=self._CARD, fg=self._FG,
                 font=("Segoe UI", 9)).pack(side="left")
        self._relocate = self._bv("relocate", t.get("willing_to_relocate", False))
        for lbl, val in [("Yes", True), ("No", False)]:
            tk.Radiobutton(rel_row, text=lbl, variable=self._relocate, value=val,
                           bg=self._CARD, fg=self._FG, selectcolor=self._INPUT_BG,
                           activebackground=self._CARD, font=("Segoe UI", 9)).pack(side="left", padx=6)

        # company_size checkboxes
        tk.Label(card, text="Company size:", bg=self._CARD, fg=self._FG,
                 font=("Segoe UI", 9)).pack(anchor="w", padx=12, pady=(8, 0))
        cs_row = tk.Frame(card, bg=self._CARD)
        cs_row.pack(anchor="w", padx=12, pady=2)
        existing_cs = t.get("company_size", ["any"])
        for cs in ["startup", "mid-size", "enterprise"]:
            checked = "any" in existing_cs or cs in existing_cs or cs.replace("-", "") in existing_cs
            v = self._bv(f"cs_{cs}", checked)
            tk.Checkbutton(cs_row, text=cs, variable=v, bg=self._CARD, fg=self._FG,
                           selectcolor=self._INPUT_BG, activebackground=self._CARD,
                           font=("Segoe UI", 9)).pack(side="left", padx=4)

        # salary + employment
        self._field_row(card, "Min salary (USD/year)", self._sv("salary_min", str(t.get("salary_min", "") or "")))
        self._field_row(card, "Notice period (days)", self._sv("notice_days", str(emp.get("notice_period_days", "0"))))
        self._field_row(card, "Earliest start date", self._sv("earliest_start", emp.get("earliest_start_date", "immediately")))
        tk.Frame(card, bg=self._CARD, height=8).pack()

    def _build_locations(self, parent: tk.Frame, ex: dict) -> None:
        t = ex.get("target", {})
        card = self._card(parent, "4. Target Locations")

        tk.Label(card, text="Leave empty or check 'Anywhere' to search nationally.",
                 bg=self._CARD, fg=self._FG_DIM, font=("Segoe UI", 9)).pack(anchor="w", padx=12)

        self._anywhere = self._bv("anywhere", len(t.get("locations", [])) == 0)

        cb = tk.Checkbutton(card, text="Anywhere in country (national search)",
                            variable=self._anywhere,
                            command=self._toggle_locations,
                            bg=self._CARD, fg=self._FG, selectcolor=self._INPUT_BG,
                            activebackground=self._CARD, font=("Segoe UI", 9))
        cb.pack(anchor="w", padx=12, pady=4)

        locs_frame = tk.Frame(card, bg=self._CARD)
        locs_frame.pack(fill="x", padx=12, pady=(0, 8))
        tk.Label(locs_frame, text="Locations (one per line):",
                 bg=self._CARD, fg=self._FG, font=("Segoe UI", 9)).pack(anchor="w")
        self._locations_text = tk.Text(locs_frame, height=4, width=50,
                                       bg=self._INPUT_BG, fg=self._INPUT_FG,
                                       insertbackground="white", relief="flat",
                                       font=("Segoe UI", 9))
        self._locations_text.pack(fill="x", pady=2)
        existing_locs = t.get("locations", [])
        if existing_locs:
            self._locations_text.insert("1.0", "\n".join(existing_locs))
        self._locs_frame = locs_frame
        self._toggle_locations()

    def _toggle_locations(self) -> None:
        state = "disabled" if self._anywhere.get() else "normal"
        self._locations_text.configure(state=state)

    def _build_roles(self, parent: tk.Frame, ex: dict) -> None:
        t = ex.get("target", {})
        card = self._card(parent, "5. Target Roles")

        tk.Label(card, text="Job titles you're targeting (one per line):",
                 bg=self._CARD, fg=self._FG, font=("Segoe UI", 9)).pack(anchor="w", padx=12)
        self._roles_text = tk.Text(card, height=4, width=50,
                                   bg=self._INPUT_BG, fg=self._INPUT_FG,
                                   insertbackground="white", relief="flat",
                                   font=("Segoe UI", 9))
        self._roles_text.pack(fill="x", padx=12, pady=4)
        existing_roles = t.get("roles", [])
        if existing_roles:
            self._roles_text.insert("1.0", "\n".join(existing_roles))

        tk.Label(card, text="Seniority levels:", bg=self._CARD, fg=self._FG,
                 font=("Segoe UI", 9)).pack(anchor="w", padx=12, pady=(8, 0))
        sen_row = tk.Frame(card, bg=self._CARD)
        sen_row.pack(anchor="w", padx=12, pady=(2, 8))
        existing_sen = t.get("seniority", [])
        for s in ["junior", "mid", "senior", "staff", "principal"]:
            v = self._bv(f"sen_{s}", s in existing_sen)
            tk.Checkbutton(sen_row, text=s, variable=v, bg=self._CARD, fg=self._FG,
                           selectcolor=self._INPUT_BG, activebackground=self._CARD,
                           font=("Segoe UI", 9)).pack(side="left", padx=4)

    def _build_skills(self, parent: tk.Frame, ex: dict) -> None:
        s = ex.get("skills", {})
        edu = s.get("education", {})
        card = self._card(parent, "6. Education & Experience")
        self._field_row(card, "Years of experience", self._sv("years_exp", str(s.get("years_experience", "") or "")))
        self._field_row(card, "Degree + field", self._sv("edu_degree", edu.get("degree", "")))
        self._field_row(card, "University", self._sv("edu_school", edu.get("school", "")))
        self._field_row(card, "Graduation year", self._sv("edu_grad_year", str(edu.get("graduation_year", "") or "")))
        tk.Frame(card, bg=self._CARD, height=8).pack()

    def _build_cover_letter(self, parent: tk.Frame, ex: dict) -> None:
        c = ex.get("cover_letter_context", {})
        card = self._card(parent, "7. Cover Letter Context")
        tk.Label(card, text="These help Claude write personalized cover letters.",
                 bg=self._CARD, fg=self._FG_DIM, font=("Segoe UI", 9)).pack(anchor="w", padx=12)

        questions = [
            ("cl_goals",         "Career goals (next 2–3 years)"),
            ("cl_motivation",    "What motivates you most?"),
            ("cl_environment",   "Ideal work environment"),
            ("cl_strengths",     "Strongest professional strengths"),
            ("cl_impact",        "Impact you want in your next role"),
            ("cl_context",       "Background context (gaps, career switches)"),
            ("cl_industries",    "Industries / problem spaces that excite you"),
            ("cl_always_convey", "Things to always convey (or never mention)"),
        ]
        cl_keys = {
            "cl_goals": "goals", "cl_motivation": "motivation",
            "cl_environment": "environment", "cl_strengths": "strengths",
            "cl_impact": "impact", "cl_context": "context",
            "cl_industries": "industries", "cl_always_convey": "always_convey",
        }
        self._cl_texts: dict[str, tk.Text] = {}
        for var_key, label in questions:
            f = tk.Frame(card, bg=self._CARD)
            f.pack(fill="x", padx=12, pady=3)
            tk.Label(f, text=label, bg=self._CARD, fg=self._FG,
                     font=("Segoe UI", 9)).pack(anchor="w")
            txt = tk.Text(f, height=2, width=60,
                          bg=self._INPUT_BG, fg=self._INPUT_FG,
                          insertbackground="white", relief="flat",
                          font=("Segoe UI", 9), wrap="word")
            txt.pack(fill="x", pady=2)
            profile_key = cl_keys[var_key]
            existing_val = c.get(profile_key, "")
            if existing_val:
                txt.insert("1.0", existing_val)
            self._cl_texts[var_key] = txt
        tk.Frame(card, bg=self._CARD, height=8).pack()

    def _build_exclusions_network(self, parent: tk.Frame, ex: dict) -> None:
        t = ex.get("target", {})
        n = ex.get("network", {})
        card = self._card(parent, "8. Exclusions & Network")

        self._field_row(card, "Industries to avoid (comma-separated)",
                        self._sv("industries_excl", ", ".join(t.get("industries_excluded", []))))
        self._field_row(card, "Companies to never apply to (comma-separated)",
                        self._sv("companies_excl", ", ".join(t.get("companies_excluded", []))))

        csv_row = tk.Frame(card, bg=self._CARD)
        csv_row.pack(fill="x", padx=12, pady=4)
        tk.Label(csv_row, text="LinkedIn connections CSV:", bg=self._CARD, fg=self._FG,
                 font=("Segoe UI", 9)).pack(side="left")
        self._csv_var = self._sv("linkedin_csv", n.get("linkedin_csv_path", ""))
        self._entry(csv_row, self._csv_var, width=28).pack(side="left", padx=(6, 4))
        tk.Button(csv_row, text="Browse", command=self._browse_csv,
                  bg="#374151", fg=self._FG, relief="flat",
                  font=("Segoe UI", 9), padx=8, cursor="hand2").pack(side="left")
        tk.Frame(card, bg=self._CARD, height=8).pack()

    def _build_cv_upload(self, parent: tk.Frame, ex: dict) -> None:
        card = self._card(parent, "9. CV / Resume Upload")
        tk.Label(card, text="Upload your CV as a Markdown (.md) file.",
                 bg=self._CARD, fg=self._FG, font=("Segoe UI", 9)).pack(anchor="w", padx=12, pady=(4, 0))

        cv_path = ROOT / "data" / "cv.md"
        status_text = f"Current: {cv_path} (exists)" if cv_path.exists() else "No CV uploaded yet."
        self._cv_status_lbl = tk.Label(card, text=status_text, bg=self._CARD,
                                       fg=self._FG_DIM, font=("Segoe UI", 9))
        self._cv_status_lbl.pack(anchor="w", padx=12)

        cv_row = tk.Frame(card, bg=self._CARD)
        cv_row.pack(fill="x", padx=12, pady=4)
        self._cv_var = self._sv("cv_path", "")
        self._entry(cv_row, self._cv_var, width=32).pack(side="left", padx=(0, 4))
        tk.Button(cv_row, text="Browse", command=self._browse_cv,
                  bg="#374151", fg=self._FG, relief="flat",
                  font=("Segoe UI", 9), padx=8, cursor="hand2").pack(side="left")

        tk.Label(card, text="Skip for now — you can upload later via Dashboard → Settings.",
                 bg=self._CARD, fg=self._FG_DIM, font=("Segoe UI", 8)).pack(anchor="w", padx=12, pady=(0, 8))

    # ── file pickers ──────────────────────────────────────────────────────

    def _browse_csv(self) -> None:
        path = filedialog.askopenfilename(
            title="Select LinkedIn Connections CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if path:
            self._csv_var.set(path)

    def _browse_cv(self) -> None:
        path = filedialog.askopenfilename(
            title="Select CV / Resume (.md file)",
            filetypes=[("Markdown files", "*.md"), ("All files", "*.*")],
        )
        if path:
            self._cv_var.set(path)

    # ── save / skip ───────────────────────────────────────────────────────

    def _on_skip(self) -> None:
        self.completed = True
        self._root.destroy()

    def _on_save(self) -> None:
        profile = self._collect()
        _save_yaml_profile(profile, PROFILE_PATH)

        # Copy CV if one was selected
        cv_src = self._cv_var.get().strip()
        if cv_src:
            import shutil as _shutil
            cv_dst = ROOT / "data" / "cv.md"
            cv_dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                _shutil.copy2(cv_src, cv_dst)
            except Exception as exc:
                messagebox.showwarning("CV Copy Failed",
                                       f"Could not copy CV: {exc}\n\nYou can copy it manually to data/cv.md")

        self.completed = True
        self._root.destroy()

    def _collect(self) -> dict:
        g = self._vars  # shorthand

        def sv(k: str) -> str:
            v = g.get(k)
            return v.get().strip() if v else ""

        def bv(k: str) -> bool:
            v = g.get(k)
            return bool(v.get()) if v else False

        def checked_list(prefix: str, options: list[str]) -> list[str]:
            return [o for o in options if bv(f"{prefix}{o}")]

        # --- visa ---
        status_options = ["US Citizen", "Green Card", "H1B", "OPT", "CPT", "TN", "Other"]
        visa_statuses = [opt for opt in status_options if bv(f"visa_st_{opt}")]
        needs_sponsorship = bv("visa_needs_sponsorship")
        visa = {
            "statuses": visa_statuses,
            # Keep "status" as a comma-joined summary for tools/forms expecting a single string
            "status": ", ".join(visa_statuses) if visa_statuses else "",
            "requires_sponsorship": needs_sponsorship,
            "authorized_to_work": True,
            "work_auth_expiry": sv("visa_expiry"),
        }

        # --- job types ---
        job_type = checked_list("jt_", ["full-time", "part-time", "contract", "internship"])

        # --- remote preference ---
        rp_checked = [rp for rp in ["remote", "hybrid", "onsite"] if bv(f"rp_{rp}")]
        if len(rp_checked) == 3:
            remote_preference = "any"
        elif len(rp_checked) == 1:
            remote_preference = rp_checked[0]
        else:
            remote_preference = rp_checked if rp_checked else "any"

        # --- locations ---
        if bv("anywhere"):
            locations: list[str] = []
        else:
            raw_locs = self._locations_text.get("1.0", "end").strip()
            locations = [l.strip() for l in raw_locs.splitlines() if l.strip()]

        # --- roles ---
        raw_roles = self._roles_text.get("1.0", "end").strip()
        roles = [r.strip() for r in raw_roles.splitlines() if r.strip()]

        # --- seniority ---
        seniority = checked_list("sen_", ["junior", "mid", "senior", "staff", "principal"])

        # --- company size ---
        cs_raw = checked_list("cs_", ["startup", "mid-size", "enterprise"])
        company_size = cs_raw if cs_raw else ["any"]

        # --- salary ---
        sal_raw = sv("salary_min")
        salary_min = int(sal_raw) if sal_raw.isdigit() else (int(sal_raw) if sal_raw.lstrip("-").isdigit() else 0)

        # --- employment ---
        nd_raw = sv("notice_days")
        notice_days = int(nd_raw) if nd_raw.isdigit() else 0

        # --- exclusions ---
        def _csv_list(key: str) -> list[str]:
            return [x.strip() for x in sv(key).split(",") if x.strip()]

        # --- cover letter ---
        cl_keys = {
            "cl_goals": "goals", "cl_motivation": "motivation",
            "cl_environment": "environment", "cl_strengths": "strengths",
            "cl_impact": "impact", "cl_context": "context",
            "cl_industries": "industries", "cl_always_convey": "always_convey",
        }
        cover_letter_context = {
            profile_key: self._cl_texts[var_key].get("1.0", "end").strip()
            for var_key, profile_key in cl_keys.items()
        }

        existing = _load_yaml_profile(PROFILE_PATH)

        return {
            "personal": {
                "full_name": sv("p_full_name"),
                "email": sv("p_email"),
                "phone": sv("p_phone"),
                "city": sv("p_city"),
                "state": sv("p_state"),
                "country": sv("p_country") or "US",
                "linkedin_url": sv("p_linkedin"),
                "github_url": sv("p_github"),
                "portfolio_url": sv("p_portfolio"),
            },
            "visa": visa,
            "employment": {
                "notice_period_days": notice_days,
                "earliest_start_date": sv("earliest_start") or "immediately",
            },
            "target": {
                "roles": roles,
                "seniority": seniority,
                "job_type": job_type or ["full-time"],
                "remote_preference": remote_preference,
                "willing_to_relocate": bv("relocate"),
                "locations": locations,
                "salary_min": salary_min,
                "company_size": company_size,
                "industries_excluded": _csv_list("industries_excl"),
                "companies_excluded": _csv_list("companies_excl"),
            },
            "skills": {
                "years_experience": int(sv("years_exp")) if sv("years_exp").isdigit() else 0,
                "education": {
                    "degree": sv("edu_degree"),
                    "school": sv("edu_school"),
                    "graduation_year": sv("edu_grad_year"),
                },
                "primary": existing.get("skills", {}).get("primary", []),
                "secondary": existing.get("skills", {}).get("secondary", []),
                "certifications": existing.get("skills", {}).get("certifications", []),
            },
            "cover_letter_context": cover_letter_context,
            "network": {
                "linkedin_csv_path": sv("linkedin_csv"),
                "manual_contacts": existing.get("network", {}).get("manual_contacts", []),
            },
            "learned_answers": existing.get("learned_answers", {}),
        }


# ---------------------------------------------------------------------------
# Onboarding
# ---------------------------------------------------------------------------

def _run_onboarding() -> bool:
    """Show the Tkinter profile wizard. Returns True if user completed or skipped."""
    wizard = _ProfileWizardWindow()
    return wizard.completed

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


# ... (existing imports and classes) ...

def main() -> None:
    if not _run_prereq_checks():
        return

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
        
        # --- NEW SCHEDULER LOGIC ---
        sched = _SchedulerDialog()
        if sched.enabled:
            _setup_scheduler(sched.time)
        # ---------------------------

    _launch()

if __name__ == "__main__":
    main()
