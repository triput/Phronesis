# ==============================================================================
# File: phronesis_app/tests/test_p0_credentials_encrypt.py
# Description: VN-E05 Fernet credentials_json roundtrip + backup redaction (S-31/S-41)
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-22
# Last Update: 2026-07-22
# ==============================================================================
"""Encrypt calendar OAuth credentials at rest; backup must still scrub secrets."""

from __future__ import annotations

import json
import os

from cryptography.fernet import Fernet, InvalidToken
from django.db import connection
from django.test import TestCase, override_settings
from django.core.management import call_command

from phronesis_app.encrypted_json import (
    ENC_MARKER,
    decrypt_credentials_payload,
    encrypt_credentials_payload,
    is_encrypted_credentials,
)
from phronesis_app.models import CalendarIntegration, SystemEnums
from phronesis_app.services.backup import build_backup_dict, export_backup_bytes


class CredentialsCryptoUnitTests(TestCase):
    """Pure encrypt/decrypt helpers."""

    def test_roundtrip_dict(self):
        payload = {"token": "atk", "refresh_token": "rr", "client_id": "cid"}
        envelope = encrypt_credentials_payload(payload)
        self.assertTrue(is_encrypted_credentials(envelope))
        self.assertNotIn("atk", json.dumps(envelope))
        self.assertEqual(decrypt_credentials_payload(envelope), payload)

    def test_empty_passthrough(self):
        self.assertIsNone(encrypt_credentials_payload(None))
        self.assertEqual(encrypt_credentials_payload({}), {})

    def test_plaintext_decrypt_passthrough(self):
        plain = {"token": "x"}
        self.assertEqual(decrypt_credentials_payload(plain), plain)


class CredentialsFieldPersistenceTests(TestCase):
    """ORM field encrypts on write; app reads plaintext dicts."""

    def test_save_encrypts_at_rest(self):
        row = CalendarIntegration.objects.create(
            provider=SystemEnums.CalendarProvider.GOOGLE,
            user_email="enc@example.com",
            credentials_json={"token": "SECRET_TOKEN", "refresh_token": "SECRET_REFRESH"},
        )
        table = CalendarIntegration._meta.db_table
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT credentials_json FROM {table} WHERE id = %s",
                [row.pk],
            )
            raw = cursor.fetchone()[0]
        raw_text = raw if isinstance(raw, str) else json.dumps(raw)
        self.assertIn(ENC_MARKER, raw_text)
        self.assertNotIn("SECRET_TOKEN", raw_text)
        self.assertNotIn("SECRET_REFRESH", raw_text)

        row.refresh_from_db()
        self.assertEqual(row.credentials_json["token"], "SECRET_TOKEN")
        self.assertEqual(row.credentials_json["refresh_token"], "SECRET_REFRESH")

    def test_lazy_upgrade_from_plaintext_row(self):
        """Simulate a pre-E05 plaintext row, then save → encrypted."""
        row = CalendarIntegration.objects.create(
            provider=SystemEnums.CalendarProvider.GOOGLE,
            user_email="lazy@example.com",
            credentials_json={},
        )
        table = CalendarIntegration._meta.db_table
        plain = json.dumps({"token": "PLAIN_TOK", "refresh_token": "PLAIN_REF"})
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {table} SET credentials_json = %s WHERE id = %s",
                [plain, row.pk],
            )

        row.refresh_from_db()
        self.assertEqual(row.credentials_json["token"], "PLAIN_TOK")

        row.save(update_fields=["credentials_json", "updated_at"])
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT credentials_json FROM {table} WHERE id = %s",
                [row.pk],
            )
            raw = cursor.fetchone()[0]
        raw_text = raw if isinstance(raw, str) else json.dumps(raw)
        self.assertIn(ENC_MARKER, raw_text)
        self.assertNotIn("PLAIN_TOK", raw_text)

    def test_management_command_upgrades_plaintext(self):
        row = CalendarIntegration.objects.create(
            provider=SystemEnums.CalendarProvider.MICROSOFT,
            user_email="cmd@example.com",
            credentials_json={},
        )
        table = CalendarIntegration._meta.db_table
        plain = json.dumps({"token": "CMD_TOK"})
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {table} SET credentials_json = %s WHERE id = %s",
                [plain, row.pk],
            )
        call_command("encrypt_calendar_credentials")
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT credentials_json FROM {table} WHERE id = %s",
                [row.pk],
            )
            raw = cursor.fetchone()[0]
        raw_text = raw if isinstance(raw, str) else json.dumps(raw)
        self.assertIn(ENC_MARKER, raw_text)
        row.refresh_from_db()
        self.assertEqual(row.credentials_json["token"], "CMD_TOK")


class CredentialsBackupRedactionTests(TestCase):
    """S-41 still holds after encryption — export never leaks tokens."""

    def test_backup_export_redacts_credentials(self):
        CalendarIntegration.objects.create(
            provider=SystemEnums.CalendarProvider.GOOGLE,
            user_email="backup@example.com",
            credentials_json={
                "token": "BACKUP_TOKEN_XYZ",
                "refresh_token": "BACKUP_REFRESH_XYZ",
            },
        )
        raw = export_backup_bytes().decode("utf-8")
        self.assertNotIn("BACKUP_TOKEN_XYZ", raw)
        self.assertNotIn("BACKUP_REFRESH_XYZ", raw)
        self.assertNotIn("refresh_token", raw)

        payload = build_backup_dict()
        label = CalendarIntegration._meta.label_lower
        rows = payload["tables"].get(label, [])
        self.assertTrue(rows)
        for item in rows:
            if item.get("fields", {}).get("user_email") == "backup@example.com":
                self.assertEqual(item["fields"].get("credentials_json"), {})
                break
        else:
            self.fail("expected CalendarIntegration row in backup")


class CredentialsKeyRotationTests(TestCase):
    """Dedicated key + previous key decrypt path."""

    def test_previous_key_decrypts_after_rotation(self):
        old_key = Fernet.generate_key().decode("ascii")
        new_key = Fernet.generate_key().decode("ascii")
        payload = {"token": "rotate-me"}

        with override_settings(SECRET_KEY="test-secret-for-derive-unused"):
            os.environ["PHRONESIS_CREDENTIALS_KEY"] = old_key
            try:
                envelope = encrypt_credentials_payload(payload)
            finally:
                os.environ.pop("PHRONESIS_CREDENTIALS_KEY", None)

            os.environ["PHRONESIS_CREDENTIALS_KEY"] = new_key
            os.environ["PHRONESIS_CREDENTIALS_KEY_PREVIOUS"] = old_key
            try:
                self.assertEqual(decrypt_credentials_payload(envelope), payload)
                # New writes use primary; previous alone cannot decrypt new envelopes
                new_envelope = encrypt_credentials_payload(payload)
            finally:
                os.environ.pop("PHRONESIS_CREDENTIALS_KEY", None)
                os.environ.pop("PHRONESIS_CREDENTIALS_KEY_PREVIOUS", None)

            os.environ["PHRONESIS_CREDENTIALS_KEY"] = old_key
            try:
                with self.assertRaises(InvalidToken):
                    decrypt_credentials_payload(new_envelope)
            finally:
                os.environ.pop("PHRONESIS_CREDENTIALS_KEY", None)
