# ==============================================================================
# File: phronesis_django/data_paths.py
# Description: VN-B01 standalone data directory and SQLite URL helpers
# Component: Core / Settings
# Version: 1.0 (Gold Master)
# Created: 2026-07-21
# Last Update: 2026-07-21
# ==============================================================================
"""Resolve PHRONESIS_DATA_DIR and default SQLite locations for Windows standalone."""

from __future__ import annotations

import os
from pathlib import Path


def get_phronesis_data_dir() -> Path | None:
    """Return configured data directory, or None when unset."""
    raw = (os.environ.get("PHRONESIS_DATA_DIR") or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def ensure_data_dir(data_dir: Path) -> Path:
    """Create the data directory (and logs/) if needed; return the path."""
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "logs").mkdir(parents=True, exist_ok=True)
    return data_dir


def sqlite_url_for_path(db_file: Path) -> str:
    """Build a dj-database-url-compatible SQLite URL for an absolute file path."""
    resolved = db_file.resolve()
    # Windows: sqlite:///C:/path/to/db.sqlite3
    return f"sqlite:///{resolved.as_posix()}"


def default_database_url(*, base_dir: Path, data_dir: Path | None = None) -> str:
    """SQLite URL: AppData when PHRONESIS_DATA_DIR set, else repo db.sqlite3."""
    if data_dir is None:
        data_dir = get_phronesis_data_dir()
    if data_dir is not None:
        ensure_data_dir(data_dir)
        return sqlite_url_for_path(data_dir / "db.sqlite3")
    return sqlite_url_for_path(base_dir / "db.sqlite3")


def load_runtime_dotenv(*, base_dir: Path, data_dir: Path | None) -> None:
    """Load .env files for Django settings.

    Repo ``.env`` is loaded first. When ``data_dir`` is set (standalone), drop
    any checkout ``DATABASE_URL`` then load data-dir ``.env`` with override so
    AppData SQLite wins unless that file explicitly sets ``DATABASE_URL``.
    """
    from dotenv import load_dotenv

    load_dotenv(base_dir / ".env")
    if data_dir is None:
        return
    os.environ.pop("DATABASE_URL", None)
    load_dotenv(data_dir / ".env", override=True)
