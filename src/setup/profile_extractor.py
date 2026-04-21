"""
Profile extractor — reads cv.md via Claude and fills missing fields in user_profile.yaml.

Runs automatically during the scrape phase when cv.md exists but profile fields are sparse.
Only fills fields that are currently empty/zero — never overwrites user-set values.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from ruamel.yaml import YAML as _RYAML

from src.utils.claude_runner import run_claude

_PROMPT_TEMPLATE = """You are a resume parser. Read the candidate's CV below and extract structured profile data.

Return ONLY valid YAML — no explanation, no markdown fences, no extra text.

Use exactly this structure (omit any field you cannot confidently extract):

personal:
  full_name: ""
  email: ""
  phone: ""
  city: ""
  state: ""
  country: "US"
  linkedin_url: ""
  github_url: ""
  portfolio_url: ""

skills:
  primary:
    - ""
  secondary:
    - ""
  years_experience: 0
  education:
    degree: ""
    school: ""
    graduation_year: ""

cover_letter_context:
  goals: ""
  motivation: ""
  strengths: ""

Rules:
- primary skills: programming languages, ML frameworks, core technical tools the candidate uses regularly (max 10)
- secondary skills: supporting tools, platforms, libraries (max 10)
- years_experience: sum of all professional/research experience in years (internships + full-time + research), rounded to 1 decimal
- education: most recent/highest degree only
- goals/motivation/strengths: 1-3 sentences inferred from their experience and focus areas
- If a field is not mentioned in the CV, omit it entirely (don't guess)
- For URLs, include the full https:// form

=== CV ===
{cv_content}
"""


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _save_yaml(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ryaml = _RYAML()
    ryaml.preserve_quotes = True
    tmp = path.with_suffix(".yaml.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        ryaml.dump(data, f)
    tmp.replace(path)


def _is_empty(value) -> bool:
    """Return True if a profile field is effectively unset."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (int, float)):
        return value == 0
    if isinstance(value, list):
        return len(value) == 0
    if isinstance(value, dict):
        return all(_is_empty(v) for v in value.values())
    return False


def _merge(existing: dict, extracted: dict) -> tuple[dict, list[str]]:
    """
    Deep-merge extracted into existing, only filling empty fields.

    Returns (merged_dict, list_of_filled_keys).
    """
    filled: list[str] = []
    result = dict(existing)

    for key, ext_val in extracted.items():
        cur_val = result.get(key)

        if isinstance(ext_val, dict) and isinstance(cur_val, dict):
            sub_merged, sub_filled = _merge(cur_val, ext_val)
            result[key] = sub_merged
            filled.extend(f"{key}.{k}" for k in sub_filled)
        elif _is_empty(cur_val) and not _is_empty(ext_val):
            result[key] = ext_val
            filled.append(key)

    return result, filled


def needs_extraction(profile: dict) -> bool:
    """
    Return True if the profile is missing enough fields to warrant CV extraction.

    Triggers when skills are empty OR years_experience is 0.
    """
    skills = profile.get("skills", {})
    return (
        _is_empty(skills.get("primary"))
        or _is_empty(skills.get("years_experience"))
    )


def extract_and_merge(
    cv_path: Path,
    profile_path: Path,
) -> list[str]:
    """
    Extract profile fields from cv.md and merge into user_profile.yaml.

    Only fills fields that are currently empty. Returns list of field names filled.
    Raises FileNotFoundError if cv_path does not exist.
    """
    if not cv_path.exists():
        raise FileNotFoundError(f"CV not found: {cv_path}")

    cv_content = cv_path.read_text(encoding="utf-8")
    prompt = _PROMPT_TEMPLATE.format(cv_content=cv_content)

    raw = run_claude(prompt, timeout=60)

    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(l for l in lines if not l.startswith("```"))

    extracted = yaml.safe_load(raw) or {}
    if not isinstance(extracted, dict):
        print("[profile_extractor] Claude returned non-dict — skipping merge")
        return []

    existing = _load_yaml(profile_path)
    merged, filled = _merge(existing, extracted)

    if filled:
        _save_yaml(merged, profile_path)

    return filled
