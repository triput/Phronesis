# ==============================================================================
# File: phronesis_app/tests/test_p0_sync_pack.py
# Description: VN-D02 sync-pack LWW, tombstones, secrets strip, idempotent import
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-22
# Last Update: 2026-07-22
# ==============================================================================
"""Cable sync-pack — export scrub, LWW matrix, tombstones, re-import."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from phronesis_app.models import (
    AppSettings,
    ExecutionItem,
    SystemEnums,
    WorkspaceContainer,
)
from phronesis_app.services.sync_pack import (
    SYNC_PACK_FORMAT,
    apply_sync_pack,
    build_sync_pack_dict,
    export_sync_pack_bytes,
    force_accept_remote,
    parse_sync_pack_bytes,
    shape_conflict_report,
)


class SyncPackServiceTests(TestCase):
    """Engine-level pack export / LWW apply."""

    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        self.solo = AppSettings.get_solo()
        self.solo.google_oauth_client_secret = "SECRET_GOOGLE"
        self.solo.openweather_api_key = "OWKEY"
        self.solo.notification_webhook_token = "WHTOK"
        self.solo.timezone = "America/Phoenix"
        self.solo.save()

    def test_export_format_and_excludes_secrets(self):
        raw = export_sync_pack_bytes().decode("utf-8")
        self.assertNotIn("SECRET_GOOGLE", raw)
        self.assertNotIn("OWKEY", raw)
        self.assertNotIn("WHTOK", raw)
        payload = build_sync_pack_dict()
        self.assertEqual(payload["format"], SYNC_PACK_FORMAT)
        self.assertEqual(payload["version"], 0)
        self.assertIn("source_device_id", payload)
        settings = payload["entities"]["settings"]
        self.assertEqual(settings["timezone"], "America/Phoenix")
        self.assertNotIn("google_oauth_client_secret", settings)
        self.assertNotIn("openweather_api_key", settings)
        self.assertGreater(len(payload["entities"]["items"]), 0)

    def test_lww_newer_pack_wins(self):
        item = ExecutionItem.objects.filter(is_deleted=False).first()
        self.assertIsNotNone(item)
        sync_id = str(item.sync_id)
        old_title = item.title
        pack = build_sync_pack_dict()
        # Make pack claim a newer update
        for row in pack["entities"]["items"]:
            if row["sync_id"] == sync_id:
                row["title"] = "Pack Wins Title"
                row["updated_at"] = (timezone.now() + timedelta(hours=1)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
                break
        # Local is older
        ExecutionItem.objects.filter(pk=item.pk).update(
            updated_at=timezone.now() - timedelta(days=1)
        )
        result = apply_sync_pack(pack)
        self.assertTrue(result.ok)
        item.refresh_from_db()
        self.assertEqual(item.title, "Pack Wins Title")
        self.assertNotEqual(item.title, old_title)

    def test_lww_local_newer_kept(self):
        item = ExecutionItem.objects.filter(is_deleted=False).first()
        sync_id = str(item.sync_id)
        item.title = "Local Kept"
        item.save()
        ExecutionItem.objects.filter(pk=item.pk).update(
            updated_at=timezone.now() + timedelta(hours=2)
        )
        pack = build_sync_pack_dict()
        for row in pack["entities"]["items"]:
            if row["sync_id"] == sync_id:
                row["title"] = "Stale Pack"
                row["updated_at"] = (timezone.now() - timedelta(days=1)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
                break
        result = apply_sync_pack(pack)
        self.assertTrue(any(c["sync_id"] == sync_id for c in result.skipped_conflicts))
        conflict = next(c for c in result.skipped_conflicts if c["sync_id"] == sync_id)
        self.assertEqual(conflict["title"], "Local Kept")
        self.assertEqual(conflict["entity"], "items")
        self.assertEqual(conflict["reason"], "local_newer")
        item.refresh_from_db()
        self.assertEqual(item.title, "Local Kept")

    def test_shape_conflict_report_fills_title(self):
        item = ExecutionItem.objects.filter(is_deleted=False).first()
        shaped = shape_conflict_report(
            [{"entity": "items", "sync_id": str(item.sync_id), "reason": "local_newer"}],
            enrich_titles=True,
        )
        self.assertEqual(shaped[0]["title"], item.title)

    def test_force_accept_remote_applies_pack(self):
        item = ExecutionItem.objects.filter(is_deleted=False).first()
        sync_id = str(item.sync_id)
        item.title = "Local Kept"
        item.save()
        ExecutionItem.objects.filter(pk=item.pk).update(
            updated_at=timezone.now() + timedelta(hours=2)
        )
        pack = build_sync_pack_dict()
        for row in pack["entities"]["items"]:
            if row["sync_id"] == sync_id:
                row["title"] = "Remote Wins"
                row["updated_at"] = (timezone.now() - timedelta(days=1)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
                break
        first = apply_sync_pack(pack)
        self.assertTrue(any(c["sync_id"] == sync_id for c in first.skipped_conflicts))
        forced = force_accept_remote([sync_id])
        self.assertTrue(forced.ok)
        item.refresh_from_db()
        self.assertEqual(item.title, "Remote Wins")
        # Forced id should not remain a conflict after accept
        self.assertFalse(any(c["sync_id"] == sync_id for c in forced.skipped_conflicts))

    def test_tombstone_wins_over_stale_upsert(self):
        item = ExecutionItem.objects.filter(is_deleted=False).first()
        sync_id = str(item.sync_id)
        # Local row is older than the tombstone timestamp
        ExecutionItem.objects.filter(pk=item.pk).update(
            updated_at=timezone.now() - timedelta(days=3)
        )
        deleted_at = (timezone.now() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        pack = {
            "format": SYNC_PACK_FORMAT,
            "version": 0,
            "exported_at": timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source_device_id": str(uuid.uuid4()),
            "entities": {
                "domains": [],
                "tags": [],
                "containers": [],
                "items": [
                    {
                        "sync_id": sync_id,
                        "updated_at": (timezone.now() - timedelta(days=2)).strftime(
                            "%Y-%m-%dT%H:%M:%SZ"
                        ),
                        "title": "Should Not Revive",
                        "status": "INBOX",
                        "priority": 3,
                        "urgency": "NORMAL",
                        "item_type": "TASK",
                        "due_at": None,
                        "estimated_minutes": 30,
                        "fuzzy_timeframe": "NONE",
                        "parent_item_sync_id": None,
                        "is_deleted": False,
                        "notes": "",
                    }
                ],
                "item_container_links": [],
                "item_dependencies": [],
                "focus_sessions": [],
                "settings": None,
            },
            "tombstones": [
                {
                    "entity": "items",
                    "sync_id": sync_id,
                    "deleted_at": deleted_at,
                }
            ],
        }
        result = apply_sync_pack(pack)
        self.assertGreaterEqual(result.tombstones_applied, 1)
        item.refresh_from_db()
        self.assertTrue(item.is_deleted)

    def test_idempotent_reimport(self):
        pack = build_sync_pack_dict()
        first = apply_sync_pack(pack)
        count_items = ExecutionItem.objects.count()
        count_containers = WorkspaceContainer.objects.count()
        second = apply_sync_pack(pack)
        self.assertTrue(first.ok and second.ok)
        self.assertEqual(ExecutionItem.objects.count(), count_items)
        self.assertEqual(WorkspaceContainer.objects.count(), count_containers)

    def test_settings_secrets_in_pack_ignored(self):
        pack = build_sync_pack_dict()
        pack["entities"]["settings"] = {
            "sync_id": str(self.solo.sync_id),
            "updated_at": (timezone.now() + timedelta(hours=1)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "timezone": "UTC",
            "theme_slug": "hybrid_dark",
            "ui_preset": "simple",
            "modules_enabled": {},
            "google_oauth_client_secret": "EVIL",
            "openweather_api_key": "EVILKEY",
        }
        apply_sync_pack(pack)
        solo = AppSettings.get_solo()
        self.assertEqual(solo.timezone, "UTC")
        self.assertEqual(solo.google_oauth_client_secret, "SECRET_GOOGLE")
        self.assertEqual(solo.openweather_api_key, "OWKEY")

    def test_android_status_maps_on_import(self):
        sync_id = str(uuid.uuid4())
        pack = {
            "format": SYNC_PACK_FORMAT,
            "version": 0,
            "exported_at": timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source_device_id": str(uuid.uuid4()),
            "entities": {
                "domains": [],
                "tags": [],
                "containers": [],
                "items": [
                    {
                        "sync_id": sync_id,
                        "updated_at": timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "title": "From Phone",
                        "status": "inbox",
                        "priority": 3,
                        "urgency": 0,
                        "item_type": "task",
                        "due_at": "2026-07-25",
                        "estimated_minutes": None,
                        "fuzzy_timeframe": None,
                        "parent_item_sync_id": None,
                        "is_deleted": False,
                        "notes": "hi",
                    }
                ],
                "item_container_links": [],
                "item_dependencies": [],
                "focus_sessions": [],
                "settings": None,
            },
            "tombstones": [],
        }
        apply_sync_pack(pack)
        item = ExecutionItem.objects.get(sync_id=sync_id)
        self.assertEqual(item.status, SystemEnums.ItemStatus.INBOX)
        self.assertEqual(item.item_type, SystemEnums.ItemType.TASK)
        self.assertEqual(item.notes, "hi")


class SyncPackViewTests(TestCase):
    """Settings Sync tab export / import."""

    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        self.client = Client()
        self.assertTrue(self.client.login(username="owner", password="ownerpass"))

    def test_export_download(self):
        resp = self.client.get(reverse("settings-sync-export"))
        self.assertEqual(resp.status_code, 200)
        payload = parse_sync_pack_bytes(resp.content)
        self.assertEqual(payload["format"], SYNC_PACK_FORMAT)

    def test_import_upload(self):
        pack_bytes = export_sync_pack_bytes()
        upload = SimpleUploadedFile(
            "pack.json",
            pack_bytes,
            content_type="application/json",
        )
        resp = self.client.post(
            reverse("settings-sync-import"),
            {"sync_pack_file": upload},
        )
        self.assertEqual(resp.status_code, 200)
        solo = AppSettings.get_solo()
        self.assertIsNotNone(solo.last_sync_at)
        self.assertIn("applied", solo.last_sync_summary)

    def test_sync_tab_renders(self):
        resp = self.client.get(reverse("canvas-settings") + "?tab=sync")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Cable sync")
        self.assertContains(resp, "data-testid=\"sync-export\"")
        self.assertContains(resp, "data-testid=\"lan-pair-panel\"")

    def test_accept_remote_view_requires_selection(self):
        resp = self.client.post(reverse("settings-sync-accept-remote"), {})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Select at least one conflict")
