"""Tests for src/contacts/importer.py — LinkedIn CSV import."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from src.contacts.importer import import_linkedin_csv
from src.tracking.db import init_db, list_contacts


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


def _write_linkedin_csv(path: Path, rows: list[dict], include_metadata: bool = True) -> None:
    """Write a minimal LinkedIn Connections CSV to a file."""
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if include_metadata:
            writer.writerow(["Notes", "LinkedIn connections export"])
            writer.writerow([""])
            writer.writerow([""])
        writer.writerow(["First Name", "Last Name", "URL", "Email Address", "Company", "Position", "Connected On"])
        for row in rows:
            writer.writerow([
                row.get("first", ""),
                row.get("last", ""),
                row.get("url", ""),
                row.get("email", ""),
                row.get("company", ""),
                row.get("position", ""),
                row.get("connected", "2024-01-01"),
            ])


class TestImportLinkedInCsv:
    def test_imports_basic_contacts(self, tmp_path, db):
        csv_path = tmp_path / "Connections.csv"
        _write_linkedin_csv(csv_path, [
            {"first": "Alice", "last": "Smith", "company": "Acme Corp", "position": "Engineer"},
            {"first": "Bob", "last": "Jones", "company": "Widget Co", "position": "PM"},
        ])
        count = import_linkedin_csv(csv_path, db)
        assert count == 2
        contacts = list_contacts(db)
        assert len(contacts) == 2

    def test_returns_imported_count(self, tmp_path, db):
        csv_path = tmp_path / "Connections.csv"
        _write_linkedin_csv(csv_path, [
            {"first": "Carol", "last": "White", "company": "Startup Inc", "position": "CTO"},
        ])
        count = import_linkedin_csv(csv_path, db)
        assert count == 1

    def test_sets_source_to_linkedin_csv(self, tmp_path, db):
        csv_path = tmp_path / "Connections.csv"
        _write_linkedin_csv(csv_path, [
            {"first": "Dave", "last": "Brown", "company": "Tech Corp", "position": "VP"},
        ])
        import_linkedin_csv(csv_path, db)
        contacts = list_contacts(db)
        assert contacts[0]["source"] == "linkedin_csv"

    def test_skips_rows_with_no_name_or_company(self, tmp_path, db):
        csv_path = tmp_path / "Connections.csv"
        _write_linkedin_csv(csv_path, [
            {"first": "", "last": "", "company": "Acme", "position": "Dev"},
            {"first": "Eve", "last": "Black", "company": "", "position": "Dev"},
            {"first": "Frank", "last": "Gray", "company": "Valid Co", "position": "Dev"},
        ])
        count = import_linkedin_csv(csv_path, db)
        assert count == 1

    def test_deduplicates_same_name_company(self, tmp_path, db):
        csv_path = tmp_path / "Connections.csv"
        _write_linkedin_csv(csv_path, [
            {"first": "Grace", "last": "Hall", "company": "Acme", "position": "Dev"},
            {"first": "Grace", "last": "Hall", "company": "Acme", "position": "Senior Dev"},
        ])
        count = import_linkedin_csv(csv_path, db)
        assert count == 2  # both parsed; DB upserts on (name, company)
        contacts = list_contacts(db)
        assert len(contacts) == 1
        assert contacts[0]["title"] == "Senior Dev"

    def test_raises_file_not_found(self, tmp_path, db):
        with pytest.raises(FileNotFoundError):
            import_linkedin_csv(tmp_path / "nonexistent.csv", db)

    def test_raises_on_missing_header(self, tmp_path, db):
        csv_path = tmp_path / "bad.csv"
        csv_path.write_text("col1,col2,col3\nval1,val2,val3\n")
        with pytest.raises(ValueError, match="First Name"):
            import_linkedin_csv(csv_path, db)

    def test_works_without_metadata_rows(self, tmp_path, db):
        csv_path = tmp_path / "Connections.csv"
        _write_linkedin_csv(csv_path, [
            {"first": "Henry", "last": "Ford", "company": "Ford", "position": "Founder"},
        ], include_metadata=False)
        count = import_linkedin_csv(csv_path, db)
        assert count == 1

    def test_stores_full_name(self, tmp_path, db):
        csv_path = tmp_path / "Connections.csv"
        _write_linkedin_csv(csv_path, [
            {"first": "Jane", "last": "Doe", "company": "Acme", "position": "PM"},
        ])
        import_linkedin_csv(csv_path, db)
        contacts = list_contacts(db)
        assert contacts[0]["name"] == "Jane Doe"
