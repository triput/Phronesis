# ==============================================================================
# File: phronesis_app/tests/test_p0_truncated_today.py
# Description: VX-16 Truncated Today density tests
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-30
# Last Update: 2026-07-30
# ==============================================================================
"""Truncated Today — show next N, expand, persist limit."""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from phronesis_app.models import AppSettings, ExecutionItem, ItemContainerLink, SystemEnums, WorkspaceContainer
from phronesis_app.services.today import (
    clamp_today_visible_limit,
    plan_today,
    set_today_visible_limit,
    today_panel_items,
)


class TruncatedTodayServiceTests(TestCase):
    def setUp(self):
        WorkspaceContainer.objects.get_or_create(
            slug="today",
            defaults={
                "title": "Today",
                "container_type": SystemEnums.ContainerType.LIST,
            },
        )
        for i in range(8):
            item = ExecutionItem.objects.create(
                title=f"Task {i}",
                status=SystemEnums.ItemStatus.PLANNED,
                priority=SystemEnums.PriorityLevel.NORMAL,
            )
            plan_today(item_ids=[item.pk])

    def test_clamp_band(self):
        self.assertEqual(clamp_today_visible_limit(0), 1)
        self.assertEqual(clamp_today_visible_limit(99), 20)
        self.assertEqual(clamp_today_visible_limit(5), 5)

    def test_panel_truncates_unless_show_all(self):
        set_today_visible_limit(3)
        visible, total, limit, truncated = today_panel_items(show_all=False)
        self.assertEqual(total, 8)
        self.assertEqual(limit, 3)
        self.assertTrue(truncated)
        self.assertEqual(len(visible), 3)

        visible_all, total2, _, truncated2 = today_panel_items(show_all=True)
        self.assertEqual(total2, 8)
        self.assertFalse(truncated2)
        self.assertEqual(len(visible_all), 8)


class TruncatedTodayViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_superuser("owner", "o@ex.com", "OwnerPass123!")
        self.client = Client()
        self.client.force_login(self.owner)
        WorkspaceContainer.objects.get_or_create(
            slug="today",
            defaults={
                "title": "Today",
                "container_type": SystemEnums.ContainerType.LIST,
            },
        )
        for i in range(6):
            item = ExecutionItem.objects.create(
                title=f"Day {i}",
                status=SystemEnums.ItemStatus.PLANNED,
            )
            plan_today(item_ids=[item.pk])
        set_today_visible_limit(2)

    def test_plan_page_truncates(self):
        response = self.client.get(reverse("canvas-plan"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Show all 6")
        self.assertContains(response, "2/6")

    def test_expand_and_collapse(self):
        expanded = self.client.post(reverse("today-expand"), {"show_all": "1"})
        self.assertEqual(expanded.status_code, 200)
        self.assertContains(expanded, "Focus next 2")
        self.assertNotContains(expanded, "Show all 6")

        collapsed = self.client.post(reverse("today-expand"), {"show_all": "0"})
        self.assertContains(collapsed, "Show all 6")

    def test_visible_limit_persists(self):
        response = self.client.post(reverse("today-visible-limit"), {"limit": "4"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(AppSettings.get_solo().today_visible_limit, 4)
        self.assertContains(response, "Show all 6")
        self.assertContains(response, "4/6")
