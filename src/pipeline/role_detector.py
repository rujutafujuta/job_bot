"""
Role detector — reads cv.md via Claude Code subprocess and writes target_roles.yaml.

Runs once at first setup and whenever cv.md modification time changes.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from src.utils.claude_runner import run_claude

_PROMPT_TEMPLATE = """You are a career advisor. Read the candidate's master CV below and generate a YAML list of job roles they should search for.

Return ONLY valid YAML in this exact format — no explanation, no markdown fences:

generated_from: cv.md
generated_at: {today}
resume_based:
  - title: "Role Title Here"
    queries:
      - "role title remote"
      - "role title variant remote"
exploratory:
  - title: "Adjacent Role Title"
    queries:
      - "adjacent role remote"

Rules:
- resume_based: roles the candidate is clearly qualified for based on their experience
- exploratory: adjacent roles they could reasonably target with their background
- Each role should have 2-3 search query variants (include "remote" for remote-friendly roles)
- 3-6 resume_based roles, 2-4 exploratory roles
- No duplicate titles
- Use common job board search terms

=== MASTER CV ===
{cv_content}
"""


def needs_regeneration(cv_path: Path, roles_path: Path) -> bool:
    """
    Return True if target_roles.yaml should be regenerated.

    True when: roles file doesn't exist, cv.md doesn't exist (forces regeneration
    attempt which will fail fast), or cv.md is newer than roles file.
    """
    if not roles_path.exists():
        return True
    if not cv_path.exists():
        return True
    return cv_path.stat().st_mtime > roles_path.stat().st_mtime


def generate_roles(
    cv_path: Path,
    roles_path: Path,
    dry_run: bool = False,
    force: bool = False,
) -> dict:
    """
    Generate target_roles.yaml from cv.md using Claude Code CLI.

    Args:
        cv_path: Path to cv.md.
        roles_path: Path to write target_roles.yaml.
        dry_run: If True, run Claude but don't write the file.
        force: If False, skip Claude call when roles file is already up to date.

    Returns:
        Parsed roles dict.

    Raises:
        FileNotFoundError: If cv_path does not exist.
    """
    if not cv_path.exists():
        raise FileNotFoundError(f"CV not found: {cv_path}")

    if not force and not needs_regeneration(cv_path, roles_path):
        return yaml.safe_load(roles_path.read_text(encoding="utf-8")) or {}

    from datetime import date
    cv_content = cv_path.read_text(encoding="utf-8")
    prompt = _PROMPT_TEMPLATE.format(
        today=date.today().isoformat(),
        cv_content=cv_content,
    )

    raw_yaml = run_claude(prompt, timeout=60)

    # Strip any accidental markdown fences Claude might add
    raw_yaml = raw_yaml.strip()
    if raw_yaml.startswith("```"):
        lines = raw_yaml.splitlines()
        raw_yaml = "\n".join(
            line for line in lines if not line.startswith("```")
        )

    roles = yaml.safe_load(raw_yaml) or {}

    if not dry_run:
        roles_path.parent.mkdir(parents=True, exist_ok=True)
        roles_path.write_text(raw_yaml, encoding="utf-8")
        print(f"[role_detector] Wrote {roles_path}")

    return roles
