"""Entry point for the setup wizard. Run with: python -m src.setup.onboarding"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.setup.profile_wizard import run_wizard


def main() -> None:
    parser = argparse.ArgumentParser(description="Job Bot Setup Wizard")
    parser.add_argument("--update", action="store_true", help="Update existing profile")
    parser.add_argument(
        "--profile",
        default="config/user_profile.yaml",
        help="Path to user_profile.yaml",
    )
    args = parser.parse_args()
    run_wizard(profile_path=Path(args.profile), update=args.update)


if __name__ == "__main__":
    main()
