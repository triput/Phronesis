# ==============================================================================
# File: phronesis_app/management/commands/encrypt_calendar_credentials.py
# Description: VN-E05 one-shot (re)encrypt CalendarIntegration.credentials_json
# Component: Core / Management
# Version: 1.0 (Gold Master)
# Created: 2026-07-22
# Last Update: 2026-07-22
# ==============================================================================
"""Re-save calendar OAuth rows so plaintext upgrades and key rotation re-encrypt.

Reads decrypt transparently (including ``PHRONESIS_CREDENTIALS_KEY_PREVIOUS``);
writes always encrypt with the current primary key. Safe to re-run.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import connection

from phronesis_app.encrypted_json import is_encrypted_credentials
from phronesis_app.models import CalendarIntegration


def _raw_looks_encrypted(raw_db) -> bool:
    """Best-effort detect Fernet envelope in raw SQLite/Postgres JSON text/dict."""
    if raw_db is None:
        return False
    if isinstance(raw_db, dict):
        return is_encrypted_credentials(raw_db)
    if isinstance(raw_db, (bytes, bytearray)):
        raw_db = raw_db.decode("utf-8", errors="replace")
    if isinstance(raw_db, str):
        return "__phronesis_enc__" in raw_db
    return False


class Command(BaseCommand):
    help = (
        "Encrypt (or re-encrypt) CalendarIntegration.credentials_json at rest "
        "(VN-E05). Lazy upgrade also happens on normal save."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report which rows would be written without saving.",
        )

    def handle(self, *args, **options):
        dry = bool(options["dry_run"])
        upgraded = 0
        reencrypted = 0
        skipped = 0
        table = CalendarIntegration._meta.db_table

        for row in CalendarIntegration.objects.all().iterator():
            payload = row.credentials_json
            if payload is None or payload == {}:
                skipped += 1
                continue

            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT credentials_json FROM {table} WHERE id = %s",
                    [row.pk],
                )
                db_row = cursor.fetchone()
            was_plain = not _raw_looks_encrypted(db_row[0] if db_row else None)

            if dry:
                label = "upgrade plaintext" if was_plain else "re-encrypt"
                self.stdout.write(f"  would {label}: pk={row.pk} {row}")
            else:
                row.credentials_json = payload
                row.save(update_fields=["credentials_json", "updated_at"])

            if was_plain:
                upgraded += 1
            else:
                reencrypted += 1

        action = "Would touch" if dry else "Updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action}: {upgraded} plaintext->encrypted, "
                f"{reencrypted} re-encrypted, {skipped} empty skipped."
            )
        )
