# ==============================================================================
# File: phronesis_app/tests/test_p0_backup.py
# Description: VN-A05 backup export/restore/clear and S-41 secrets scrub tests
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-21
# Last Update: 2026-07-21
# ==============================================================================
"""Backup — secrets-safe export, full/productivity restore and clear."""

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from phronesis_app.models import (
    AppSettings,
    CalendarIntegration,
    ExecutionItem,
    SystemEnums,
    WorkspaceContainer,
)
from phronesis_app.services.backup import (
    build_backup_dict,
    clear_owner_data,
    export_backup_bytes,
    parse_backup_bytes,
    restore_backup,
)


class BackupServiceTests(TestCase):
    """Engine-level export scrub and scoped restore/clear."""

    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        self.solo = AppSettings.get_solo()
        self.solo.google_oauth_client_secret = "SECRET_GOOGLE"
        self.solo.microsoft_oauth_client_secret = "SECRET_MS"
        self.solo.openweather_api_key = "OWKEY"
        self.solo.notification_webhook_token = "WHTOK"
        self.solo.google_oauth_client_id = "cid-keep"
        self.solo.timezone = "America/Phoenix"
        self.solo.save()
        CalendarIntegration.objects.update_or_create(
            provider=SystemEnums.CalendarProvider.GOOGLE,
            user_email="owner@example.com",
            defaults={
                "credentials_json": {"token": "atk", "refresh_token": "rr"},
                "sync_enabled": True,
            },
        )

    def test_export_excludes_secrets_s41(self):
        raw = export_backup_bytes().decode("utf-8")
        self.assertNotIn("SECRET_GOOGLE", raw)
        self.assertNotIn("SECRET_MS", raw)
        self.assertNotIn("OWKEY", raw)
        self.assertNotIn("WHTOK", raw)
        self.assertNotIn("atk", raw)
        self.assertNotIn("refresh_token", raw)
        self.assertIn("cid-keep", raw)
        payload = build_backup_dict()
        self.assertEqual(payload["format"], "phronesis_backup")
        self.assertIn(ExecutionItem._meta.label_lower, payload["tables"])
        self.assertGreater(len(payload["tables"][ExecutionItem._meta.label_lower]), 0)

    def test_full_restore_round_trip_preserves_user_password(self):
        User = get_user_model()
        owner = User.objects.get(username="owner")
        before_hash = owner.password
        items_before = ExecutionItem.objects.count()
        containers_before = WorkspaceContainer.objects.count()
        payload = build_backup_dict()

        clear_owner_data("full")
        self.assertEqual(ExecutionItem.objects.count(), 0)
        # Solo row gone until restore / get_solo
        self.assertFalse(AppSettings.objects.filter(pk=1).exists())

        result = restore_backup(payload, scope="full")
        self.assertTrue(result.ok)
        self.assertEqual(ExecutionItem.objects.count(), items_before)
        self.assertEqual(WorkspaceContainer.objects.count(), containers_before)
        owner.refresh_from_db()
        self.assertEqual(owner.password, before_hash)
        # Full restore must not reintroduce secrets from file
        solo = AppSettings.get_solo()
        self.assertEqual(solo.google_oauth_client_secret, "")
        self.assertEqual(solo.google_oauth_client_id, "cid-keep")

    def test_productivity_clear_keeps_config_and_tokens(self):
        items_before = ExecutionItem.objects.count()
        self.assertGreater(items_before, 0)
        result = clear_owner_data("productivity")
        self.assertTrue(result.ok)
        self.assertEqual(ExecutionItem.objects.count(), 0)
        self.assertEqual(WorkspaceContainer.objects.count(), 0)
        solo = AppSettings.get_solo()
        self.assertEqual(solo.timezone, "America/Phoenix")
        self.assertEqual(solo.google_oauth_client_id, "cid-keep")
        self.assertEqual(solo.google_oauth_client_secret, "SECRET_GOOGLE")
        ci = CalendarIntegration.objects.get(user_email="owner@example.com")
        self.assertEqual(ci.credentials_json.get("token"), "atk")

    def test_productivity_restore_does_not_clobber_local_settings(self):
        payload = build_backup_dict()
        self.solo.timezone = "UTC"
        self.solo.google_oauth_client_id = "local-cid"
        self.solo.save()
        items_before = ExecutionItem.objects.count()

        clear_owner_data("productivity")
        restore_backup(payload, scope="productivity")

        self.assertEqual(ExecutionItem.objects.count(), items_before)
        solo = AppSettings.get_solo()
        self.assertEqual(solo.timezone, "UTC")
        self.assertEqual(solo.google_oauth_client_id, "local-cid")
        self.assertEqual(solo.google_oauth_client_secret, "SECRET_GOOGLE")

    def test_parse_rejects_garbage(self):
        with self.assertRaises(ValueError):
            parse_backup_bytes(b"not-json")
        with self.assertRaises(ValueError):
            parse_backup_bytes(b'{"format":"nope","version":1,"tables":{}}')


class BackupViewTests(TestCase):
    """Settings Backup tab export / restore / clear endpoints."""

    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        self.client = Client()
        self.client.login(username="owner", password="ownerpass")

    def test_backup_tab_renders(self):
        response = self.client.get(reverse("canvas-settings"), {"tab": "backup"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-testid="backup-export"')
        self.assertContains(response, 'data-testid="backup-restore-form"')
        self.assertContains(response, 'data-testid="backup-clear-form"')

    def test_export_download_is_json_without_secrets(self):
        solo = AppSettings.get_solo()
        solo.google_oauth_client_secret = "SECRET_GOOGLE"
        solo.save()
        response = self.client.get(reverse("settings-backup-export"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])
        body = response.content.decode("utf-8")
        self.assertNotIn("SECRET_GOOGLE", body)
        self.assertIn("phronesis_backup", body)

    def test_clear_productivity_via_post(self):
        self.assertGreater(ExecutionItem.objects.count(), 0)
        response = self.client.post(
            reverse("settings-backup-clear"),
            {"scope": "productivity", "confirm_text": "CLEAR", "settings_tab": "backup"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ExecutionItem.objects.count(), 0)
        self.assertTrue(AppSettings.objects.filter(pk=1).exists())
