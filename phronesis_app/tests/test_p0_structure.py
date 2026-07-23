# ==============================================================================
# File: phronesis_app/tests/test_p0_structure.py
# Description: VN-A09 Simple structure create — container / domain + Matrix UI
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-22
# Last Update: 2026-07-22
# ==============================================================================
"""Coverage for Matrix New container without Bulk/Templates."""

from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from phronesis_app.models import DomainCategory, SystemEnums, WorkspaceContainer
from phronesis_app.services.modules import apply_preset, is_enabled
from phronesis_app.services.structure import create_container, create_domain


class StructureServiceTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush")

    def test_create_container_list_with_existing_domain(self):
        domain = DomainCategory.objects.get(slug="home")
        result = create_container(
            "Weekend errands",
            container_type="LIST",
            domain_id=domain.pk,
        )
        self.assertTrue(result.ok)
        self.assertIsNotNone(result.container)
        self.assertEqual(result.container.title, "Weekend errands")
        self.assertEqual(result.container.slug, "weekend-errands")
        self.assertEqual(result.container.container_type, SystemEnums.ContainerType.LIST)
        self.assertEqual(result.container.domain_id, domain.pk)

    def test_create_container_with_new_domain(self):
        before = DomainCategory.objects.count()
        result = create_container(
            "Garden beds",
            container_type="PROJECT",
            new_domain_name="Yard",
        )
        self.assertTrue(result.ok)
        self.assertEqual(DomainCategory.objects.count(), before + 1)
        self.assertEqual(result.container.domain.name, "Yard")
        self.assertTrue(DomainCategory.objects.filter(slug="yard").exists())

    def test_create_domain_rejects_duplicate_name(self):
        first = create_domain("Side hustle")
        second = create_domain("side hustle")
        self.assertTrue(first.ok)
        self.assertFalse(second.ok)

    def test_cannot_create_inbox_type(self):
        result = create_container("Nope", container_type="INBOX")
        self.assertFalse(result.ok)

    def test_create_under_parent(self):
        parent = WorkspaceContainer.objects.get(slug="p0-foundation")
        result = create_container(
            "Nested list",
            container_type="LIST",
            parent_id=parent.pk,
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.container.parent_id, parent.pk)


class MatrixStructureUITests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        apply_preset("simple")
        self.client = Client()
        self.client.login(username="owner", password="ownerpass")

    def test_simple_matrix_shows_create_hides_bulk_add(self):
        self.assertFalse(is_enabled("mod.bulk"))
        response = self.client.get(reverse("canvas-matrix"))
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("New container", body)
        self.assertIn('name="title"', body)
        self.assertIn('name="new_domain_name"', body)
        self.assertNotIn("Bulk add…", body)

    def test_matrix_create_post_creates_container(self):
        before = WorkspaceContainer.objects.count()
        response = self.client.post(
            reverse("matrix-container-create"),
            {
                "title": "Manual verify list",
                "container_type": "LIST",
                "new_domain_name": "Verify",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(WorkspaceContainer.objects.count(), before + 1)
        container = WorkspaceContainer.objects.get(slug="manual-verify-list")
        self.assertEqual(container.domain.name, "Verify")
        self.assertIn("matrix-reload", response["HX-Trigger"])

    def test_full_preset_still_shows_bulk_add(self):
        apply_preset("full")
        response = self.client.get(reverse("canvas-matrix"))
        self.assertContains(response, "Bulk add…")
