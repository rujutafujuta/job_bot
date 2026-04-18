"""Form field learning — prompts user for unknown fields and saves answers to profile."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_PROFILE_PATH = Path("config/user_profile.yaml")

# Common form field labels mapped to profile keys for auto-lookup
_KNOWN_FIELD_MAP: dict[str, str] = {
    # Application fields → profile path (dot-notation)
    "full name": "personal.full_name",
    "first name": "personal.full_name",      # Split handled in applicator
    "last name": "personal.full_name",
    "email": "personal.email",
    "phone": "personal.phone",
    "linkedin": "personal.linkedin_url",
    "github": "personal.github_url",
    "website": "personal.portfolio_url",
    "portfolio": "personal.portfolio_url",
    "address": "personal.address",
    "city": "personal.address",
    "location": "personal.address",
    "salary": "target.desired_salary",
    "desired salary": "target.desired_salary",
    "expected salary": "target.desired_salary",
    "authorized to work": "visa.authorized_to_work",
    "work authorization": "visa.status",
    "visa": "visa.status",
    "sponsorship": "visa.requires_sponsorship",
    "currently employed": "employment.currently_employed",
    "notice period": "employment.notice_period_days",
    "start date": "employment.earliest_start_date",
    "willing to relocate": "target.willing_to_relocate",
    "disability": "eeo.disability_status",
    "veteran": "eeo.veteran_status",
    "race": "eeo.race_ethnicity",
    "ethnicity": "eeo.race_ethnicity",
}

# Fields saved to learned_answers (not a fixed profile field)
_LEARNED_FIELDS = {
    "driver's license",
    "driver license",
    "how did you hear",
    "how did you find",
    "refer",
    "source",
    "gender",
    "pronouns",
    "overtime",
    "travel",
    "background check",
    "drug test",
}


def _get_nested(data: dict, dotpath: str) -> str | None:
    """Retrieve a nested dict value using dot-notation path."""
    keys = dotpath.split(".")
    for key in keys:
        if not isinstance(data, dict) or key not in data:
            return None
        data = data[key]
    return str(data) if data is not None else None


def lookup_field(label: str, profile: dict) -> str | None:
    """
    Try to find a value for a form field label from the user profile.

    Args:
        label: The form field label text (case-insensitive).
        profile: The loaded user profile dict.

    Returns:
        String value if found, None if unknown.
    """
    label_lower = label.lower().strip()

    for key_fragment, dotpath in _KNOWN_FIELD_MAP.items():
        if key_fragment in label_lower:
            value = _get_nested(profile, dotpath)
            if value is not None:
                return value

    # Check learned_answers — keys are stored with underscores, normalize label to match
    label_normalized = re.sub(r"[^\w]", "_", label_lower).strip("_")
    learned = profile.get("learned_answers", {})
    for key, val in learned.items():
        if key == label_normalized and val is not None:
            return str(val)

    return None


def prompt_and_learn(label: str, profile: dict, profile_path: Path = _PROFILE_PATH) -> str:
    """
    Ask the user to fill in an unknown field, then save the answer if it's a common field.

    Args:
        label: The form field label the bot couldn't answer.
        profile: The loaded profile dict (mutated in-place for learned_answers).
        profile_path: Path to user_profile.yaml to persist the answer.

    Returns:
        The answer the user typed.
    """
    print(f"\n[form] Unknown field: '{label}'")
    answer = input(f"  Please fill in '{label}': ").strip()

    label_lower = label.lower()
    is_learnable = any(fragment in label_lower for fragment in _LEARNED_FIELDS)

    if is_learnable and answer:
        # Normalize key: lowercase, replace spaces with underscores
        key = re.sub(r"[^\w]", "_", label_lower).strip("_")
        if "learned_answers" not in profile:
            profile["learned_answers"] = {}
        profile["learned_answers"][key] = answer

        # Persist to YAML
        try:
            with profile_path.open(encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
            if "learned_answers" not in raw:
                raw["learned_answers"] = {}
            raw["learned_answers"][key] = answer
            with profile_path.open("w", encoding="utf-8") as f:
                yaml.dump(raw, f, allow_unicode=True, default_flow_style=False)
            print(f"  [form] Saved '{key}' to learned_answers in user_profile.yaml")
        except Exception as e:
            print(f"  [form] Warning: could not persist answer to profile: {e}")

    return answer


