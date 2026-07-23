# ==============================================================================
# File: phronesis_app/tests/test_p0_trash.py
# Description: VN-A07 Trash surface restore / empty tests
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-21
# Last Update: 2026-07-21
# ==============================================================================
"""Trash — soft-delete restore, archive restore, empty items."""

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from phronesis_app.models import ExecutionItem, SystemEnums, WorkspaceContainer
from phronesis_app.services.trash import empty_trash_items, restore_container, restore_item


class TrashServiceTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")

    def test_restore_soft_deleted_item(self):
        item = ExecutionItem.objects.filter(is_deleted=True).first()
        if not item:
            item = ExecutionItem.objects.filter(is_deleted=False).first()
            item.is_deleted = True
            item.save(update_fields=["is_deleted"])
        pk = item.pk
        result = restore_item(pk)
        self.assertTrue(result.ok)
        item.refresh_from_db()
        self.assertFalse(item.is_deleted)

    def test_restore_archived_container(self):
        container = WorkspaceContainer.objects.filter(is_archived=True).first()
        self.assertIsNotNone(container)
        result = restore_container(container.pk)
        self.assertTrue(result.ok)
        container.refresh_from_db()
        self.assertFalse(container.is_archived)
        self.assertNotEqual(container.para_state, SystemEnums.PARACategory.ARCHIVE)

    def test_empty_trash_hard_deletes_items_only(self):
        item = ExecutionItem.objects.filter(is_deleted=False).first()
        item.is_deleted = True
        item.save(update_fields=["is_deleted"])
        archived = WorkspaceContainer.objects.filter(is_archived=True).count()
        result = empty_trash_items()
        self.assertTrue(result.ok)
        self.assertFalse(ExecutionItem.objects.filter(pk=item.pk).exists())
        self.assertEqual(WorkspaceContainer.objects.filter(is_archived=True).count(), archived)


class TrashViewTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        self.client = Client()
        self.client.login(username="owner", password="ownerpass")

    def test_trash_surface_lists_seed_deleted_and_archived(self):
        response = self.client.get(reverse("canvas-trash"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-testid="trash-surface"')
        # seed includes soft-deleted spike notes + archived old-blog
        self.assertContains(response, "Obsolete spike notes")
        self.assertContains(response, "Retired Blog Migration")
        self.assertContains(response, reverse("canvas-trash"))

    def test_restore_item_via_post(self):
        item = ExecutionItem.objects.get(title="Obsolete spike notes (soft-deleted)")
        self.assertTrue(item.is_deleted)
        response = self.client.post(reverse("trash-restore-item", args=[item.pk]))
        self.assertEqual(response.status_code, 302)
        item.refresh_from_db()
        self.assertFalse(item.is_deleted)

    def test_rail_includes_trash_on_home(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, reverse("canvas-trash"))
        self.assertContains(response, ">Trash<")
