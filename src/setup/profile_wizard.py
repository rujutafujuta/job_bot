"""
Profile Setup Wizard — guided CLI to build config/user_profile.yaml.

Usage:
    python -m src.setup.onboarding          # First run
    python -m src.setup.onboarding --update # Update existing profile
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml
from ruamel.yaml import YAML as _RYAML

# ── colour helpers ────────────────────────────────────────────────────────────

_NO_COLOR = not sys.stdout.isatty() or os.environ.get("NO_COLOR")

def _c(text: str, code: str) -> str:
    return text if _NO_COLOR else f"\033[{code}m{text}\033[0m"

def bold(t: str)   -> str: return _c(t, "1")
def cyan(t: str)   -> str: return _c(t, "96")
def green(t: str)  -> str: return _c(t, "92")
def yellow(t: str) -> str: return _c(t, "93")
def dim(t: str)    -> str: return _c(t, "2")

# ── prompt helpers ────────────────────────────────────────────────────────────

def _ask(prompt: str, default: Any = "") -> str:
    default_str = str(default) if default not in ("", None) else ""
    suffix = f" [{dim(default_str)}]" if default_str else ""
    try:
        raw = input(f"  {prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)
    return raw or default_str


def _ask_list(prompt: str, default: list[str] | None = None) -> list[str]:
    default_str = ", ".join(default) if default else ""
    raw = _ask(prompt + " (comma-separated)", default=default_str)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _ask_menu(prompt: str, options: list[str], default: str = "") -> str:
    print(f"  {prompt}")
    for i, opt in enumerate(options, 1):
        marker = green("*") if opt == default else " "
        print(f"    {marker} {i}. {opt}")
    while True:
        raw = _ask("Enter number", default=default)
        if raw in options:
            return raw
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                return options[idx]
        except ValueError:
            pass
        print(f"  {yellow('Please enter a number 1–' + str(len(options)))}")


def _ask_bool(prompt: str, default: bool = False) -> bool:
    raw = _ask(f"{prompt} (y/n)", default="y" if default else "n").lower()
    return raw in ("y", "yes", "true", "1")


def _ask_multiline(prompt: str, default: str = "") -> str:
    if default:
        print(dim(f"  Existing: {default[:120]}{'...' if len(default) > 120 else ''}"))
    print(dim(f"  {prompt} (press Enter twice when done):"))
    lines = []
    while True:
        try:
            line = input("  ")
        except (EOFError, KeyboardInterrupt):
            break
        if line == "" and lines and lines[-1] == "":
            break
        lines.append(line)
    raw = "\n".join(lines).strip()
    return raw if raw else default


def _section(title: str, n: int, total: int) -> None:
    print()
    print(cyan("─" * 72))
    print(cyan(f"  SECTION {n}/{total}: {title.upper()}"))
    print(cyan("─" * 72))


def _load_yaml(path: Path) -> dict:
    if path.exists():
        with path.open(encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def _write_yaml(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ryaml = _RYAML()
    ryaml.preserve_quotes = True
    tmp = path.with_suffix(".yaml.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        ryaml.dump(data, f)
    tmp.replace(path)


# ── Sections ──────────────────────────────────────────────────────────────────

_TOTAL = 8


def _personal(ex: dict) -> dict:
    _section("Personal Information", 1, _TOTAL)
    p = ex.get("personal", {})
    return {
        "full_name":     _ask("Full legal name",              p.get("full_name", "")),
        "email":         _ask("Email address",                p.get("email", "")),
        "phone":         _ask("Phone (with country code)",    p.get("phone", "")),
        "city":          _ask("City",                         p.get("city", "")),
        "state":         _ask("State / Province",             p.get("state", "")),
        "country":       _ask("Country",                      p.get("country", "US")),
        "linkedin_url":  _ask("LinkedIn URL",                 p.get("linkedin_url", "")),
        "github_url":    _ask("GitHub URL (optional)",        p.get("github_url", "")),
        "portfolio_url": _ask("Portfolio/website (optional)", p.get("portfolio_url", "")),
    }


def _visa(ex: dict) -> dict:
    """Work authorization — outputs canonical visa.* keys."""
    _section("Work Authorization", 2, _TOTAL)
    v = ex.get("visa", {})
    auth_type = _ask_menu(
        "Authorization type:",
        ["US Citizen", "Green Card", "H1B", "OPT", "CPT", "TN", "Need Sponsorship", "Other"],
        default=v.get("status", "OPT"),
    )
    expiry = ""
    if auth_type in ("OPT", "CPT", "H1B", "TN"):
        expiry = _ask("Expiry date (YYYY-MM-DD, leave blank if N/A)", v.get("work_auth_expiry", ""))
    requires_sponsorship = auth_type == "Need Sponsorship"
    return {
        "status": auth_type,
        "requires_sponsorship": requires_sponsorship,
        "authorized_to_work": True,
        "work_auth_expiry": expiry,
    }


def _target_and_employment(ex: dict) -> tuple[dict, dict]:
    """Job preferences + employment — outputs canonical target.* and employment.* keys."""
    _section("Job Preferences", 3, _TOTAL)
    t = ex.get("target", {})
    emp = ex.get("employment", {})

    # --- target.roles (was entirely missing) ---
    roles = _ask_list(
        "Target job titles (e.g. Software Engineer, ML Engineer)",
        t.get("roles", []),
    )
    seniority = _ask_list(
        "Seniority levels (e.g. mid, senior, staff)",
        t.get("seniority", ["mid", "senior"]),
    )

    job_type = _ask_list(
        "Job types wanted (e.g. full-time, contract)",
        t.get("job_type", ["full-time"]),
    )
    remote_pref = _ask_menu(
        "Remote preference:",
        ["remote", "hybrid", "onsite", "any"],
        default=t.get("remote_preference", "remote"),
    )
    relocate = _ask_bool("Willing to relocate?", t.get("willing_to_relocate", False))

    print(dim("  Leave blank to search anywhere in the country (no location filter)."))
    locations = _ask_list("Target locations (e.g. San Francisco CA, New York NY)", t.get("locations", []))

    salary_min_raw = _ask("Minimum acceptable salary (USD/year)", t.get("salary_min", ""))
    salary_min = int(salary_min_raw) if str(salary_min_raw).isdigit() else (salary_min_raw or 0)

    company_size = _ask_list(
        "Company sizes (startup, mid, enterprise — or leave blank for any)",
        t.get("company_size", []),
    )

    industries_excluded = _ask_list(
        "Industries to avoid (e.g. gambling, defense)",
        t.get("industries_excluded", []),
    )

    notice_raw = _ask("Notice period in days (0 if not currently employed)", emp.get("notice_period_days", 0))
    notice_days = int(notice_raw) if str(notice_raw).isdigit() else 0
    earliest_start = _ask("Earliest start date (YYYY-MM-DD or 'immediately')", emp.get("earliest_start_date", "immediately"))

    target = {
        "roles": roles,
        "seniority": seniority,
        "job_type": job_type,
        "remote_preference": remote_pref,
        "willing_to_relocate": relocate,
        "locations": locations,
        "salary_min": salary_min,
        "company_size": company_size or ["any"],
        "industries_excluded": industries_excluded,
    }
    employment = {
        "notice_period_days": notice_days,
        "earliest_start_date": earliest_start,
    }
    return target, employment


def _skills(ex: dict) -> dict:
    """Education + experience — outputs canonical skills.* keys."""
    _section("Education & Experience", 4, _TOTAL)
    s = ex.get("skills", {})
    edu = s.get("education", {})

    years_raw = _ask("Years of professional experience", s.get("years_experience", ""))
    years = int(years_raw) if str(years_raw).isdigit() else (years_raw or 0)

    degree = _ask("Highest degree + field (e.g. BS Computer Science)", edu.get("degree", ""))
    school = _ask("University name",    edu.get("school", ""))
    grad_year = _ask("Graduation year", edu.get("graduation_year", ""))

    return {
        "years_experience": years,
        "education": {
            "degree": degree,
            "school": school,
            "graduation_year": grad_year,
        },
        "primary": s.get("primary", []),
        "secondary": s.get("secondary", []),
        "certifications": s.get("certifications", []),
    }


def _cover_letter_context(ex: dict) -> dict:
    _section("Cover Letter Context", 5, _TOTAL)
    print(dim("  These answers help Claude write personalized cover letters for each job."))
    c = ex.get("cover_letter_context", {})

    questions = [
        ("goals",         "What are your career goals for the next 2–3 years?"),
        ("motivation",    "What motivates you most in your work?"),
        ("environment",   "What type of work environment do you thrive in? (e.g. fast startup, structured org, research)"),
        ("strengths",     "What do you consider your strongest professional strengths?"),
        ("impact",        "What kind of impact do you want to have in your next role?"),
        ("context",       "Anything in your background to contextualize? (gaps, switches, unconventional path)"),
        ("industries",    "What industries or problem spaces excite you most?"),
        ("always_convey", "Anything you always want to convey in applications? (values, style, things to never mention)"),
    ]

    result = {}
    for key, question in questions:
        print()
        result[key] = _ask_multiline(question, c.get(key, ""))

    return result


def _exclusions_and_network(ex: dict) -> tuple[dict, dict]:
    """Exclusions folded into target; network section."""
    _section("Network Setup (LinkedIn Contacts)", 6, _TOTAL)
    print(dim("  The bot checks if you know anyone at a company and flags it in evaluations."))
    print()
    print("  To export your LinkedIn connections:")
    print(dim("  Settings → Data privacy → Get a copy of your data → Connections"))
    print()

    n = ex.get("network", {})
    csv_path = _ask("Path to LinkedIn connections CSV (leave blank to skip)", n.get("linkedin_csv_path", ""))

    manual_contacts = list(n.get("manual_contacts", []))
    add_manual = _ask_bool("Add any contacts manually?", default=False)
    while add_manual:
        name    = _ask("Contact name")
        company = _ask("Company")
        title   = _ask("Their title (optional)", "")
        if name and company:
            manual_contacts.append({"name": name, "company": company, "title": title})
        add_manual = _ask_bool("Add another?", default=False)

    network = {
        "linkedin_csv_path": csv_path,
        "manual_contacts":   manual_contacts,
    }

    # companies exclusion (was in separate _exclusions section)
    _section("Company Exclusions", 7, _TOTAL)
    e = ex.get("exclusions", ex.get("target", {}))
    companies_excluded = _ask_list(
        "Companies to never apply to (leave blank if none)",
        e.get("companies", []) if "companies" in e else [],
    )

    return network, companies_excluded


def _task_scheduler_setup() -> None:
    _section("Windows Task Scheduler (Optional)", 8, _TOTAL)
    print(dim("  Sets up a daily 3am run of the pipeline so you wake up to fresh jobs."))
    print()

    if not _ask_bool("Set up Windows Task Scheduler to run pipeline at 3am?", default=True):
        print(dim("  Skipped. You can run the pipeline manually: python -m src.pipeline.orchestrator --phase scrape"))
        return

    python_exe = sys.executable
    task_name  = "JobBotDailyPipeline"

    cmd = [
        "schtasks", "/create", "/tn", task_name,
        "/tr", f'"{python_exe}" -m src.pipeline.orchestrator --phase scrape',
        "/sc", "daily",
        "/st", "03:00",
        "/sd", "01/01/2026",
        "/f",
        "/rl",  "HIGHEST",
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(green(f"  ✓ Task '{task_name}' created — runs daily at 3:00 AM"))
        else:
            print(yellow(f"  Could not create task: {result.stderr.strip()}"))
            print(dim("  Try running this prompt as Administrator, or create the task manually."))
    except FileNotFoundError:
        print(yellow("  schtasks not found — not running on Windows or missing PATH"))


# ── Main wizard ───────────────────────────────────────────────────────────────

def run_wizard(
    profile_path: Path = Path("config/user_profile.yaml"),
    update: bool = False,
) -> dict:
    print()
    print(bold(cyan("=" * 72)))
    print(bold(cyan("  JOB BOT SETUP WIZARD")))
    print(bold(cyan("=" * 72)))

    print(yellow("\n  [NOTE] All fields below are OPTIONAL."))
    print(dim("  If you're not sure, just press Enter to skip."))
    print(dim("  You can change these anytime in Dashboard -> Settings.\n"))
    print(dim("  Press Enter to keep existing default values shown in [brackets]."))
    print(dim("  Press Ctrl+C at any time to cancel without saving."))
    print()

    existing = _load_yaml(profile_path)
    if existing:
        print()
        print(green(f"  Existing profile found at {profile_path}"))

    target, employment = _target_and_employment(existing)
    network, companies_excluded = _exclusions_and_network(existing)

    # Merge companies_excluded into target
    target["companies_excluded"] = companies_excluded

    profile = {
        "personal":             _personal(existing),
        "visa":                 _visa(existing),
        "employment":           employment,
        "target":               target,
        "skills":               _skills(existing),
        "cover_letter_context": _cover_letter_context(existing),
        "network":              network,
        "learned_answers":      existing.get("learned_answers", {}),
    }

    print()
    print(cyan("─" * 72))
    print()
    if not _ask_bool("Save profile and continue?", default=True):
        print(yellow("  Cancelled — nothing saved."))
        return {}

    _write_yaml(profile, profile_path)
    print()
    print(bold(green(f"  ✓ Profile saved to {profile_path}")))

    _task_scheduler_setup()

    print()
    print(bold("  Setup complete. Next steps:"))
    print(dim("  1. Place your master CV at data/cv.md"))
    print(dim("  2. Add API keys to .env (APIFY_TOKEN, ADZUNA_APP_ID, ADZUNA_API_KEY)"))
    print(dim("  3. Run: python -m src.pipeline.orchestrator --phase scrape --dry-run"))
    print(dim("  4. Start the dashboard: uvicorn src.web.app:app --reload"))
    print()

    return profile
