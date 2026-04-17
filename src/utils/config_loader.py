"""Config loader — load and validate user_profile.yaml and .env."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

_REQUIRED_PERSONAL = ["full_name", "email", "phone"]
_REQUIRED_WORK_AUTH = ["type"]
_REQUIRED_JOB_PREFS = ["job_types", "remote_preference"]


def load_env(env_path: str | Path = ".env") -> None:
    """Load .env into environment. Call before validate_env."""
    load_dotenv(dotenv_path=str(env_path))


def load_profile(config_path: str | Path = "config/user_profile.yaml") -> dict:
    """
    Load user_profile.yaml.

    Returns the profile dict. Raises FileNotFoundError if missing.
    Does NOT validate required fields — onboarding wizard ensures completeness.
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(
            f"User profile not found at {path}. "
            "Run `python -m src.setup.onboarding` to complete setup first."
        )
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_roles(roles_path: str | Path = "config/target_roles.yaml") -> dict:
    """Load target_roles.yaml. Returns empty dict if missing."""
    path = Path(roles_path)
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def validate_env() -> None:
    """
    Check that required environment variables are set.

    Required: none by default (Apify/Adzuna are optional).
    Warns about optional vars that improve functionality.
    """
    optional_with_warnings = {
        "APIFY_TOKEN": "Apify scraper will be skipped (covers LinkedIn, Indeed, Glassdoor)",
        "ADZUNA_APP_ID": "Adzuna scraper will be skipped",
        "ADZUNA_API_KEY": "Adzuna scraper will be skipped",
    }
    for key, msg in optional_with_warnings.items():
        if not os.environ.get(key):
            print(f"[config] Warning: {key} not set — {msg}")
