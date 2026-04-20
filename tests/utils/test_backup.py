"""Tests for backup/restore utility."""

from __future__ import annotations

import sqlite3
import zipfile
from pathlib import Path

import pytest

from src.utils.backup import create_backup, restore_backup


class TestCreateBackup:
    def test_returns_zip_path(self, tmp_path):
        db = tmp_path / "tracking.db"
        db.write_bytes(b"SQLite")
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        backups_dir = tmp_path / "backups"

        result = create_backup(db_path=db, data_dir=data_dir, backups_dir=backups_dir)

        assert result.suffix == ".zip"
        assert result.exists()

    def test_zip_contains_db(self, tmp_path):
        db = tmp_path / "tracking.db"
        db.write_bytes(b"SQLite data")
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        backups_dir = tmp_path / "backups"

        result = create_backup(db_path=db, data_dir=data_dir, backups_dir=backups_dir)

        with zipfile.ZipFile(result) as zf:
            names = zf.namelist()
        assert any("tracking.db" in n for n in names)

    def test_zip_contains_data_files(self, tmp_path):
        db = tmp_path / "tracking.db"
        db.write_bytes(b"SQLite")
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "report.md").write_text("hello")
        backups_dir = tmp_path / "backups"

        result = create_backup(db_path=db, data_dir=data_dir, backups_dir=backups_dir)

        with zipfile.ZipFile(result) as zf:
            names = zf.namelist()
        assert any("report.md" in n for n in names)

    def test_filename_contains_date(self, tmp_path):
        db = tmp_path / "tracking.db"
        db.write_bytes(b"SQLite")
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        backups_dir = tmp_path / "backups"

        result = create_backup(db_path=db, data_dir=data_dir, backups_dir=backups_dir)

        assert "job_bot_backup_" in result.name

    def test_creates_backups_dir_if_missing(self, tmp_path):
        db = tmp_path / "tracking.db"
        db.write_bytes(b"SQLite")
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        backups_dir = tmp_path / "backups"
        assert not backups_dir.exists()

        create_backup(db_path=db, data_dir=data_dir, backups_dir=backups_dir)

        assert backups_dir.exists()

    def test_missing_db_raises(self, tmp_path):
        db = tmp_path / "nonexistent.db"
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        backups_dir = tmp_path / "backups"

        with pytest.raises(FileNotFoundError):
            create_backup(db_path=db, data_dir=data_dir, backups_dir=backups_dir)

    def test_nested_data_files_included(self, tmp_path):
        db = tmp_path / "tracking.db"
        db.write_bytes(b"SQLite")
        data_dir = tmp_path / "data"
        sub = data_dir / "reports"
        sub.mkdir(parents=True)
        (sub / "analysis.md").write_text("report")
        backups_dir = tmp_path / "backups"

        result = create_backup(db_path=db, data_dir=data_dir, backups_dir=backups_dir)

        with zipfile.ZipFile(result) as zf:
            names = zf.namelist()
        assert any("analysis.md" in n for n in names)


class TestRestoreBackup:
    def _make_backup_zip(self, tmp_path: Path) -> tuple[Path, Path]:
        """Return (zip_path, original_db_path)."""
        source = tmp_path / "source"
        source.mkdir()
        db = source / "tracking.db"

        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.execute("INSERT INTO t VALUES (42)")
        conn.commit()
        conn.close()

        data_dir = source / "data"
        data_dir.mkdir()
        (data_dir / "note.txt").write_text("preserved")

        backups_dir = tmp_path / "backups"
        zip_path = create_backup(db_path=db, data_dir=data_dir, backups_dir=backups_dir)
        return zip_path, db

    def test_restores_db_content(self, tmp_path):
        zip_path, original_db = self._make_backup_zip(tmp_path)
        restore_dir = tmp_path / "restore"
        restore_dir.mkdir()
        restored_db = restore_dir / "tracking.db"
        restored_data = restore_dir / "data"

        restore_backup(zip_path=zip_path, db_path=restored_db, data_dir=restored_data)

        conn = sqlite3.connect(str(restored_db))
        row = conn.execute("SELECT x FROM t").fetchone()
        conn.close()
        assert row[0] == 42

    def test_restores_data_files(self, tmp_path):
        zip_path, _ = self._make_backup_zip(tmp_path)
        restore_dir = tmp_path / "restore"
        restore_dir.mkdir()
        restored_db = restore_dir / "tracking.db"
        restored_data = restore_dir / "data"

        restore_backup(zip_path=zip_path, db_path=restored_db, data_dir=restored_data)

        assert (restored_data / "note.txt").exists()
        assert (restored_data / "note.txt").read_text() == "preserved"

    def test_missing_zip_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            restore_backup(
                zip_path=tmp_path / "nope.zip",
                db_path=tmp_path / "db.db",
                data_dir=tmp_path / "data",
            )

    def test_invalid_zip_raises(self, tmp_path):
        bad_zip = tmp_path / "bad.zip"
        bad_zip.write_bytes(b"not a zip")

        with pytest.raises(zipfile.BadZipFile):
            restore_backup(
                zip_path=bad_zip,
                db_path=tmp_path / "db.db",
                data_dir=tmp_path / "data",
            )
