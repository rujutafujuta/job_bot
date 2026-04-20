"""Backup and restore — zip data/tracking.db + data/ directory."""

from __future__ import annotations

import zipfile
from datetime import datetime
from pathlib import Path

_DEFAULT_DB = Path("data/tracking.db")
_DEFAULT_DATA = Path("data")
_DEFAULT_BACKUPS = Path("backups")


def create_backup(
    db_path: Path = _DEFAULT_DB,
    data_dir: Path = _DEFAULT_DATA,
    backups_dir: Path = _DEFAULT_BACKUPS,
) -> Path:
    """Zip db_path + data_dir into backups_dir/job_bot_backup_<timestamp>.zip.

    Returns the path to the created zip file.
    Raises FileNotFoundError if db_path does not exist.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    backups_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    zip_path = backups_dir / f"job_bot_backup_{timestamp}.zip"

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(db_path, arcname=f"db/{db_path.name}")
        if data_dir.exists():
            for file in data_dir.rglob("*"):
                if file.is_file():
                    zf.write(file, arcname=f"data/{file.relative_to(data_dir)}")

    return zip_path


def restore_backup(
    zip_path: Path,
    db_path: Path = _DEFAULT_DB,
    data_dir: Path = _DEFAULT_DATA,
) -> None:
    """Extract zip_path, replacing db_path and data_dir in-place.

    Raises FileNotFoundError if zip_path does not exist.
    Raises zipfile.BadZipFile if zip_path is not a valid zip.
    """
    if not zip_path.exists():
        raise FileNotFoundError(f"Backup file not found: {zip_path}")

    with zipfile.ZipFile(zip_path, "r") as zf:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        data_dir.mkdir(parents=True, exist_ok=True)

        for member in zf.namelist():
            if member.startswith("db/"):
                target = db_path.parent / Path(member).name
                target.write_bytes(zf.read(member))
            elif member.startswith("data/"):
                relative = member[len("data/"):]
                if not relative:
                    continue
                target = data_dir / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(member))
