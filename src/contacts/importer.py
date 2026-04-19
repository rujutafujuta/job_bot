"""LinkedIn Connections.csv importer — populates the contacts table."""

from __future__ import annotations

import csv
from pathlib import Path

from src.tracking.db import add_contact, _DEFAULT_DB


def import_linkedin_csv(csv_path: Path, db_path: Path = _DEFAULT_DB) -> int:
    """
    Parse a LinkedIn Connections.csv export and upsert into the contacts table.

    LinkedIn CSV format (after 3 header metadata rows):
        First Name, Last Name, URL, Email Address, Company, Position, Connected On

    Args:
        csv_path: Path to the Connections.csv file.
        db_path: SQLite database path.

    Returns:
        Number of contacts imported (duplicates skipped gracefully).

    Raises:
        ValueError: If the file does not look like a LinkedIn CSV.
        FileNotFoundError: If csv_path does not exist.
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))

    # Find the data header row — LinkedIn prepends 3 lines of metadata
    header_idx: int | None = None
    for i, row in enumerate(rows):
        normalised = [c.strip().lower().replace(" ", "") for c in row]
        if "firstname" in normalised or "first name" in [c.strip().lower() for c in row]:
            header_idx = i
            break

    if header_idx is None:
        raise ValueError(
            "Could not find header row in CSV. "
            "Expected a 'First Name' column. Is this a LinkedIn Connections export?"
        )

    header = [h.strip() for h in rows[header_idx]]

    def _col(*names: str) -> int | None:
        for name in names:
            for i, h in enumerate(header):
                if h.lower().replace(" ", "") == name.lower().replace(" ", ""):
                    return i
        return None

    first_idx = _col("First Name", "FirstName")
    last_idx = _col("Last Name", "LastName")
    company_idx = _col("Company")
    position_idx = _col("Position")

    if first_idx is None:
        raise ValueError("CSV missing 'First Name' column.")

    count = 0
    for row in rows[header_idx + 1:]:
        if not row:
            continue

        def _get(idx: int | None) -> str:
            return row[idx].strip() if idx is not None and idx < len(row) else ""

        first = _get(first_idx)
        last = _get(last_idx)
        name = f"{first} {last}".strip()
        company = _get(company_idx)
        title = _get(position_idx)

        if not name or not company:
            continue

        add_contact(name=name, company=company, title=title, source="linkedin_csv", db_path=db_path)
        count += 1

    return count
