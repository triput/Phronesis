# ==============================================================================
# File: phronesis_app/tests/test_p0_app_label_rename.py
# Description: VN-H01 in-place lifeos_app → phronesis_app adopt tests
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-22
# Last Update: 2026-07-22
# ==============================================================================
"""Verify app-label adopt renames tables and migration rows without wipe."""

from django.db import connection
from django.test import TestCase

from phronesis_app.services.app_label_rename import (
    NEW_LABEL,
    OLD_LABEL,
    adopt_phronesis_app_label,
    legacy_artifacts_present,
)


class AppLabelAdoptTests(TestCase):
    """SQLite-level rename of synthetic lifeos_app artifacts."""

    def test_fresh_phronesis_db_is_already_adopted(self):
        """Test DB is created under current label — adopt is a no-op."""
        self.assertFalse(legacy_artifacts_present())
        result = adopt_phronesis_app_label()
        self.assertTrue(result.already_adopted)

    def test_renames_legacy_table_and_migration_row(self):
        with connection.cursor() as cursor:
            cursor.execute(
                f'CREATE TABLE "{OLD_LABEL}_scratch" (id INTEGER PRIMARY KEY, note TEXT)'
            )
            cursor.execute(
                f'INSERT INTO "{OLD_LABEL}_scratch" (note) VALUES (%s)',
                ["keep-me"],
            )
            cursor.execute(
                "INSERT INTO django_migrations (app, name, applied) VALUES (%s, %s, CURRENT_TIMESTAMP)",
                [OLD_LABEL, "9999_scratch_fake"],
            )
            cursor.execute(
                "INSERT INTO django_content_type (app_label, model) VALUES (%s, %s)",
                [OLD_LABEL, "scratch"],
            )

        self.assertTrue(legacy_artifacts_present())
        result = adopt_phronesis_app_label()
        self.assertFalse(result.already_adopted)
        self.assertTrue(any("scratch" in row for row in result.tables_renamed))

        with connection.cursor() as cursor:
            tables = set(connection.introspection.table_names(cursor))
            self.assertIn(f"{NEW_LABEL}_scratch", tables)
            self.assertNotIn(f"{OLD_LABEL}_scratch", tables)
            cursor.execute(f'SELECT note FROM "{NEW_LABEL}_scratch"')
            self.assertEqual(cursor.fetchone()[0], "keep-me")
            cursor.execute(
                "SELECT COUNT(*) FROM django_migrations WHERE app = %s AND name = %s",
                [NEW_LABEL, "9999_scratch_fake"],
            )
            self.assertEqual(cursor.fetchone()[0], 1)
            cursor.execute(
                "SELECT COUNT(*) FROM django_migrations WHERE app = %s",
                [OLD_LABEL],
            )
            self.assertEqual(cursor.fetchone()[0], 0)
            cursor.execute(
                "SELECT COUNT(*) FROM django_content_type WHERE app_label = %s AND model = %s",
                [NEW_LABEL, "scratch"],
            )
            self.assertEqual(cursor.fetchone()[0], 1)

        self.assertFalse(legacy_artifacts_present())
