# ==============================================================================
# File: phronesis_app/tests/test_p0_standalone_paths.py
# Description: VN-B01 PHRONESIS_DATA_DIR / SQLite URL resolution tests
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-21
# Last Update: 2026-07-31
# ==============================================================================
"""Standalone data-dir helpers for Windows launcher."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from phronesis_django.data_paths import (
    default_database_url,
    ensure_data_dir,
    get_phronesis_data_dir,
    load_runtime_dotenv,
    sqlite_url_for_path,
)


class StandalonePathTests(SimpleTestCase):
    """Pure helpers — no DB required."""

    def test_get_phronesis_data_dir_unset(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PHRONESIS_DATA_DIR", None)
            self.assertIsNone(get_phronesis_data_dir())

    def test_default_database_url_uses_data_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "Phronesis"
            url = default_database_url(base_dir=Path(tmp) / "repo", data_dir=data)
            self.assertTrue(data.exists())
            self.assertIn("db.sqlite3", url)
            self.assertTrue(url.startswith("sqlite:///"))
            self.assertTrue((data / "db.sqlite3").parent.exists())

    def test_default_database_url_falls_back_to_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            url = default_database_url(base_dir=base, data_dir=None)
            self.assertEqual(url, sqlite_url_for_path(base / "db.sqlite3"))

    def test_ensure_data_dir_creates_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            ensure_data_dir(data)
            self.assertTrue((data / "logs").is_dir())

    def test_standalone_dotenv_drops_checkout_database_url(self):
        """Regression: AppData launch must not keep repo Postgres DATABASE_URL."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "repo"
            data = Path(tmp) / "Phronesis"
            base.mkdir()
            data.mkdir()
            (base / ".env").write_text(
                "SECRET_KEY=repo-secret\nDATABASE_URL=postgres://checkout/db\n",
                encoding="utf-8",
            )
            (data / ".env").write_text(
                "SECRET_KEY=appdata-secret\nDEBUG=False\n",
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("DATABASE_URL", None)
                os.environ.pop("SECRET_KEY", None)
                load_runtime_dotenv(base_dir=base, data_dir=data)
                self.assertNotIn("DATABASE_URL", os.environ)
                self.assertEqual(os.environ.get("SECRET_KEY"), "appdata-secret")

    def test_standalone_dotenv_keeps_explicit_data_dir_database_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "repo"
            data = Path(tmp) / "Phronesis"
            base.mkdir()
            data.mkdir()
            (base / ".env").write_text(
                "SECRET_KEY=repo\nDATABASE_URL=postgres://checkout/db\n",
                encoding="utf-8",
            )
            (data / ".env").write_text(
                "SECRET_KEY=app\nDATABASE_URL=postgres://appdata/db\n",
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {}, clear=False):
                load_runtime_dotenv(base_dir=base, data_dir=data)
                self.assertEqual(os.environ.get("DATABASE_URL"), "postgres://appdata/db")

    def test_standalone_dotenv_keeps_orchestrator_database_url(self):
        """Railway/Compose DATABASE_URL must survive PHRONESIS_DATA_DIR volumes."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "repo"
            data = Path(tmp) / "Phronesis"
            base.mkdir()
            data.mkdir()
            (base / ".env").write_text(
                "SECRET_KEY=repo\nDATABASE_URL=postgres://checkout/db\n",
                encoding="utf-8",
            )
            (data / ".env").write_text("SECRET_KEY=app\nDEBUG=False\n", encoding="utf-8")
            with mock.patch.dict(
                os.environ,
                {"DATABASE_URL": "postgresql://neondb_owner@neon/db?sslmode=require"},
                clear=False,
            ):
                load_runtime_dotenv(base_dir=base, data_dir=data)
                self.assertEqual(
                    os.environ.get("DATABASE_URL"),
                    "postgresql://neondb_owner@neon/db?sslmode=require",
                )
